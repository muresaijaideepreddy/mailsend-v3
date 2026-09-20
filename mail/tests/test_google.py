import base64
import hashlib
import time
from email.message import EmailMessage
from unittest.mock import Mock, patch
from urllib.parse import parse_qs, urlparse

import requests
from cryptography.fernet import Fernet
from django.contrib.auth import get_user_model
from django.core.exceptions import ImproperlyConfigured, PermissionDenied
from django.test import TestCase, override_settings
from django.urls import reverse
from google.auth.exceptions import TransportError

from mail.google_api import (
    SEND_SCOPE, SEND_URL, TOKEN_URL, decrypt_credentials, encrypt_credentials,
    oauth_configured, send_gmail, subject_hash,
)
from mail.models import GoogleCredential, Membership, Workspace
from mail.oauth_views import SESSION_KEY
from mail.services import DeliveryRejected


GOOGLE_SETTINGS = {
    "GOOGLE_CLIENT_ID": "test-client.apps.googleusercontent.com",
    "GOOGLE_CLIENT_SECRET": "test-client-secret-not-live",
    "GOOGLE_REDIRECT_URI": "https://mail.example.test/accounts/google/callback/",
    "MAILSEND_TOKEN_ENCRYPTION_KEY": Fernet.generate_key().decode("ascii"),
}


@override_settings(**GOOGLE_SETTINGS)
class GoogleTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        User = get_user_model()
        cls.executive = User.objects.create_user("google-exec", email="exec@example.com", password="a-long-local-password")
        cls.assistant = User.objects.create_user("google-assistant", email="assistant@example.com")
        cls.other = User.objects.create_user("google-other", email="other@example.com")
        cls.workspace = Workspace.objects.create(name="Lab", executive=cls.executive)
        cls.other_workspace = Workspace.objects.create(name="Other", executive=cls.other)
        Membership.objects.create(user=cls.executive, workspace=cls.workspace, role="executive")
        Membership.objects.create(user=cls.assistant, workspace=cls.workspace, role="assistant")
        Membership.objects.create(user=cls.other, workspace=cls.other_workspace, role="executive")

    def tokens(self, **changes):
        values = dict(access_token="test-access-token", refresh_token="test-refresh-token", expires_at=time.time() + 3600, scope="openid email profile " + SEND_SCOPE, sub="subject-123", email="exec@example.com")
        values.update(changes)
        return values

    def connection(self, user=None, **changes):
        user = user or self.executive
        data = self.tokens(email=user.email, **changes)
        return GoogleCredential.objects.create(user=user, encrypted_data=encrypt_credentials(data), subject_hash=subject_hash(data["sub"]))

    def response(self, status=200, data=None):
        result = Mock(status_code=status)
        result.json.return_value = data if data is not None else {"id": "gmail-message-id"}
        return result


class CredentialTests(GoogleTestCase):
    def test_credentials_are_encrypted_and_can_be_decrypted(self):
        data = self.tokens()
        encrypted = encrypt_credentials(data)
        self.assertNotIn("test-access-token", encrypted)
        self.assertNotIn("exec@example.com", encrypted)
        self.assertEqual(decrypt_credentials(encrypted), data)

    def test_corrupt_ciphertext_is_rejected(self):
        with self.assertRaises(ValueError):
            decrypt_credentials("not-valid-ciphertext")

    @override_settings(MAILSEND_TOKEN_ENCRYPTION_KEY="")
    def test_no_fallback_to_django_secret_for_token_encryption(self):
        self.assertFalse(oauth_configured())
        with self.assertRaises(ImproperlyConfigured):
            encrypt_credentials(self.tokens())

    @override_settings(DEBUG=False, GOOGLE_REDIRECT_URI="http://mail.example.com/callback/")
    def test_production_requires_secure_redirect_uri(self):
        self.assertFalse(oauth_configured())


class OAuthFlowTests(GoogleTestCase):
    def begin(self):
        response = self.client.get(reverse("mail:google_login"))
        self.assertEqual(response.status_code, 302)
        self.assertEqual(urlparse(response.url).hostname, "accounts.google.com")
        return self.client.session[SESSION_KEY], parse_qs(urlparse(response.url).query)

    def callback(self, flow, email="new-executive@example.com", sub="new-subject", claims_changes=None, token_changes=None):
        tokens = dict(access_token="new-access", refresh_token="new-refresh", id_token="signed-id-token", token_type="Bearer", expires_in=3600, scope="openid email profile " + SEND_SCOPE)
        tokens.update(token_changes or {})
        claims = dict(iss="https://accounts.google.com", sub=sub, email=email, email_verified=True, nonce=flow["nonce"], given_name="Daniel")
        claims.update(claims_changes or {})
        with patch("mail.oauth_views.requests.post", return_value=self.response(data=tokens)) as post, patch("mail.oauth_views.id_token.verify_oauth2_token", return_value=claims) as verify:
            response = self.client.get(reverse("mail:google_callback"), {"state": flow["state"], "code": "one-use-code"})
        return response, post, verify

    def test_anonymous_authorization_has_state_nonce_pkce_and_identity_only_scope(self):
        flow, query = self.begin()
        self.assertEqual(query["state"], [flow["state"]])
        self.assertEqual(query["nonce"], [flow["nonce"]])
        expected = base64.urlsafe_b64encode(hashlib.sha256(flow["verifier"].encode("ascii")).digest()).decode("ascii").rstrip("=")
        self.assertEqual(query["code_challenge"], [expected])
        self.assertEqual(query["code_challenge_method"], ["S256"])
        self.assertSetEqual(set(query["scope"][0].split()), {"openid", "email", "profile"})
        self.assertNotIn("access_type", query)
        self.assertNotIn("include_granted_scopes", query)
        self.assertNotIn("client_secret", query)

    def test_authenticated_executive_connect_requests_minimal_send_scope(self):
        self.client.force_login(self.executive)
        _, query = self.begin()
        self.assertSetEqual(set(query["scope"][0].split()), {"openid", "email", "profile", SEND_SCOPE})
        self.assertEqual(query["access_type"], ["offline"])
        self.assertEqual(query["include_granted_scopes"], ["false"])

    def test_new_google_user_gets_own_executive_workspace(self):
        flow, _ = self.begin()
        response, _, _ = self.callback(flow)
        self.assertEqual(urlparse(response.url).hostname, "accounts.google.com")
        self.assertFalse(get_user_model().objects.filter(email="new-executive@example.com").exists())
        self.assertFalse(GoogleCredential.objects.exists())
        flow = self.client.session[SESSION_KEY]
        response, post, verify = self.callback(flow)
        self.assertRedirects(response, reverse("mail:dashboard"), fetch_redirect_response=False)
        user = get_user_model().objects.get(email="new-executive@example.com")
        self.assertEqual(user.membership.role, "executive")
        self.assertEqual(user.membership.workspace.executive, user)
        self.assertFalse(user.has_usable_password())
        worker = user.owned_workspace.memberships.get(role='assistant').user
        self.assertEqual(worker.username, f'worker-{user.pk}')
        self.assertEqual(worker.email, '')
        self.assertFalse(worker.has_usable_password())
        record = GoogleCredential.objects.get(user=user)
        self.assertTrue(record.connected)
        self.assertEqual(decrypt_credentials(record)["sub"], "new-subject")
        self.assertNotIn(SESSION_KEY, self.client.session)
        self.assertEqual(post.call_args.kwargs["data"]["code_verifier"], flow["verifier"])
        self.assertEqual(verify.call_args.kwargs["audience"], GOOGLE_SETTINGS["GOOGLE_CLIENT_ID"])

    def test_callback_state_mismatch_is_rejected_without_network(self):
        self.begin()
        with patch("mail.oauth_views.requests.post") as post:
            self.client.get(reverse("mail:google_callback"), {"state": "incorrect", "code": "code"})
        post.assert_not_called()
        self.assertNotIn(SESSION_KEY, self.client.session)
        self.assertFalse(GoogleCredential.objects.exists())

    def test_expired_flow_is_rejected_without_network(self):
        flow, _ = self.begin()
        session = self.client.session
        flow["started_at"] = time.time() - 601
        session[SESSION_KEY] = flow
        session.save()
        with patch("mail.oauth_views.requests.post") as post:
            self.client.get(reverse("mail:google_callback"), {"state": flow["state"], "code": "code"})
        post.assert_not_called()

    def test_callback_is_single_use(self):
        flow, _ = self.begin()
        self.callback(flow)
        with patch("mail.oauth_views.requests.post") as post:
            self.client.get(reverse("mail:google_callback"), {"state": flow["state"], "code": "one-use-code"})
        post.assert_not_called()

    def test_google_denial_is_handled_without_exchange(self):
        flow, _ = self.begin()
        with patch("mail.oauth_views.requests.post") as post:
            response = self.client.get(reverse("mail:google_callback"), {"state": flow["state"], "error": "access_denied"})
        self.assertEqual(response.status_code, 302)
        post.assert_not_called()

    def test_invalid_nonce_issuer_or_unverified_email_creates_nothing(self):
        for claims in ({"nonce": "bad"}, {"iss": "https://attacker.test"}, {"email_verified": False}, {"email_verified": "true"}):
            with self.subTest(claims=claims):
                flow, _ = self.begin()
                self.callback(flow, claims_changes=claims)
                self.assertFalse(get_user_model().objects.filter(email="new-executive@example.com").exists())
                self.assertFalse(GoogleCredential.objects.exists())

    def test_missing_send_permission_rolls_back_new_account(self):
        flow, _ = self.begin()
        self.callback(flow, token_changes={"scope": "openid email profile"})
        self.assertNotIn("_auth_user_id", self.client.session)
        flow = self.client.session[SESSION_KEY]
        self.callback(flow, token_changes={"scope": "openid email profile"})
        self.assertFalse(get_user_model().objects.filter(email="new-executive@example.com").exists())
        self.assertFalse(GoogleCredential.objects.exists())

    def test_anonymous_email_collision_never_links_local_account(self):
        flow, _ = self.begin()
        self.callback(flow, email=self.executive.email)
        self.assertNotIn("_auth_user_id", self.client.session)
        self.assertFalse(GoogleCredential.objects.exists())

    def test_authenticated_executive_connects_matching_email_only(self):
        self.client.force_login(self.executive)
        flow, _ = self.begin()
        self.callback(flow, email="wrong@example.com")
        self.assertFalse(GoogleCredential.objects.exists())
        flow, _ = self.begin()
        self.callback(flow, email=self.executive.email)
        self.assertTrue(GoogleCredential.objects.filter(user=self.executive, connected=True).exists())

    def test_assistant_cannot_connect_or_disconnect_google(self):
        self.client.force_login(self.assistant)
        self.assertEqual(self.client.get(reverse("mail:google_login")).status_code, 403)
        self.assertEqual(self.client.post(reverse("mail:google_disconnect")).status_code, 403)

    def test_changed_authenticated_user_invalidates_flow(self):
        self.client.force_login(self.executive)
        flow, _ = self.begin()
        self.client.force_login(self.other)
        session = self.client.session
        session[SESSION_KEY] = flow
        session.save()
        with patch("mail.oauth_views.requests.post") as post:
            self.client.get(reverse("mail:google_callback"), {"state": flow["state"], "code": "code"})
        post.assert_not_called()

    def test_existing_google_login_matches_subject_and_preserves_refresh_token(self):
        record = self.connection()
        original = record.encrypted_data
        flow, _ = self.begin()
        self.callback(flow, email=self.executive.email, sub="subject-123", token_changes={"refresh_token": ""})
        self.assertEqual(int(self.client.session["_auth_user_id"]), self.executive.pk)
        record.refresh_from_db()
        self.assertEqual(record.encrypted_data, original)
        self.assertEqual(decrypt_credentials(record)["refresh_token"], "test-refresh-token")

    def test_authenticated_reconnect_preserves_an_omitted_refresh_token(self):
        record = self.connection()
        self.client.force_login(self.executive)
        flow, _ = self.begin()
        self.callback(flow, email=self.executive.email, sub="subject-123", token_changes={"refresh_token": ""})
        record.refresh_from_db()
        self.assertEqual(decrypt_credentials(record)["access_token"], "new-access")
        self.assertEqual(decrypt_credentials(record)["refresh_token"], "test-refresh-token")

    def test_different_google_subject_cannot_replace_existing_identity(self):
        record = self.connection()
        self.client.force_login(self.executive)
        flow, _ = self.begin()
        self.callback(flow, email=self.executive.email, sub="different-subject")
        record.refresh_from_db()
        self.assertEqual(decrypt_credentials(record)["sub"], "subject-123")

    def test_disconnect_removes_tokens_preserving_google_login_identity(self):
        record = self.connection()
        self.client.force_login(self.executive)
        self.assertEqual(self.client.get(reverse("mail:google_disconnect")).status_code, 405)
        response = self.client.post(reverse("mail:google_disconnect"))
        self.assertEqual(response.status_code, 302)
        record.refresh_from_db()
        self.assertFalse(record.connected)
        self.assertEqual(decrypt_credentials(record), {"sub": "subject-123", "email": self.executive.email})
        self.client.logout()
        flow, _ = self.begin()
        self.callback(flow, email=self.executive.email, sub="subject-123")
        self.assertNotIn("_auth_user_id", self.client.session)
        record.refresh_from_db()
        self.assertFalse(record.connected)
        flow = self.client.session[SESSION_KEY]
        self.callback(flow, email=self.executive.email, sub="subject-123")
        self.assertEqual(int(self.client.session["_auth_user_id"]), self.executive.pk)

    def test_certificate_transport_failure_is_graceful(self):
        flow, _ = self.begin()
        token_response = {"id_token": "signed-token"}
        with patch("mail.oauth_views.requests.post", return_value=self.response(data=token_response)), patch("mail.oauth_views.id_token.verify_oauth2_token", side_effect=TransportError("network unavailable")):
            response = self.client.get(reverse("mail:google_callback"), {"state": flow["state"], "code": "code"})
        self.assertEqual(response.status_code, 302)
        self.assertFalse(GoogleCredential.objects.exists())

    def test_corrupt_tokens_can_reconnect_only_to_same_verified_identity(self):
        record = self.connection()
        GoogleCredential.objects.filter(pk=record.pk).update(encrypted_data="corrupt-ciphertext", connected=False)
        flow, _ = self.begin()
        self.callback(flow, email=self.executive.email, sub="wrong-subject")
        self.assertNotIn("_auth_user_id", self.client.session)
        record.refresh_from_db()
        self.assertFalse(record.connected)
        flow, _ = self.begin()
        self.callback(flow, email=self.executive.email, sub="subject-123")
        self.assertNotIn("_auth_user_id", self.client.session)
        flow = self.client.session[SESSION_KEY]
        self.callback(flow, email=self.executive.email, sub="subject-123")
        record.refresh_from_db()
        self.assertTrue(record.connected)
        self.assertEqual(decrypt_credentials(record)["access_token"], "new-access")
        self.assertEqual(int(self.client.session["_auth_user_id"]), self.executive.pk)


class GmailTests(GoogleTestCase):
    def email(self):
        outgoing = EmailMessage()
        outgoing["From"] = self.executive.email
        outgoing["To"] = "recipient@example.com"
        outgoing["Subject"] = "Research update"
        outgoing.set_content("Message")
        return outgoing

    def test_gmail_posts_base64_mime_once_and_returns_receipt(self):
        self.connection()
        outgoing = self.email()
        with patch("mail.google_api.requests.post", return_value=self.response()) as post:
            result = send_gmail(self.executive, outgoing)
        self.assertEqual(result, "gmail-message-id")
        post.assert_called_once()
        self.assertEqual(post.call_args.args[0], SEND_URL)
        self.assertEqual(base64.urlsafe_b64decode(post.call_args.kwargs["json"]["raw"]), outgoing.as_bytes())
        self.assertFalse(post.call_args.kwargs["allow_redirects"])

    def test_missing_connection_and_assistant_are_rejected_before_network(self):
        with patch("mail.google_api.requests.post") as post:
            with self.assertRaises(DeliveryRejected):
                send_gmail(self.executive, self.email())
            with self.assertRaises(PermissionDenied):
                send_gmail(self.assistant, self.email())
        post.assert_not_called()

    def test_sender_spoofing_is_rejected_before_network(self):
        self.connection()
        outgoing = self.email()
        outgoing.replace_header("From", "other@example.com")
        with patch("mail.google_api.requests.post") as post:
            with self.assertRaises(DeliveryRejected):
                send_gmail(self.executive, outgoing)
        post.assert_not_called()

    def test_expired_token_refreshes_before_single_send(self):
        record = self.connection(expires_at=time.time() - 1)
        refreshed = self.response(data={"access_token": "refreshed-access", "expires_in": 3600})
        with patch("mail.google_api.requests.post", side_effect=[refreshed, self.response()]) as post:
            self.assertEqual(send_gmail(self.executive, self.email()), "gmail-message-id")
        self.assertEqual([call.args[0] for call in post.call_args_list], [TOKEN_URL, SEND_URL])
        self.assertEqual(post.call_args_list[1].kwargs["headers"]["Authorization"], "Bearer refreshed-access")
        record.refresh_from_db()
        self.assertEqual(decrypt_credentials(record)["refresh_token"], "test-refresh-token")

    def test_refresh_failure_is_safe_rejection_and_never_calls_send(self):
        self.connection(expires_at=time.time() - 1)
        with patch("mail.google_api.requests.post", side_effect=requests.Timeout("refresh timeout")) as post:
            with self.assertRaises(DeliveryRejected):
                send_gmail(self.executive, self.email())
        post.assert_called_once()
        self.assertEqual(post.call_args.args[0], TOKEN_URL)

    def test_provider_4xx_is_definitive_but_408_and_5xx_are_ambiguous(self):
        self.connection()
        for status in (400, 401, 403, 429):
            with self.subTest(status=status), patch("mail.google_api.requests.post", return_value=self.response(status=status)) as post:
                with self.assertRaises(DeliveryRejected):
                    send_gmail(self.executive, self.email())
                post.assert_called_once()
        for status in (408, 500, 503):
            with self.subTest(status=status), patch("mail.google_api.requests.post", return_value=self.response(status=status)) as post:
                with self.assertRaises(RuntimeError):
                    send_gmail(self.executive, self.email())
                post.assert_called_once()

    def test_send_timeout_is_not_retried_or_marked_definitive(self):
        self.connection()
        with patch("mail.google_api.requests.post", side_effect=requests.Timeout("send timeout")) as post:
            with self.assertRaises(requests.Timeout):
                send_gmail(self.executive, self.email())
        post.assert_called_once()

    def test_success_without_provider_id_is_ambiguous(self):
        self.connection()
        with patch("mail.google_api.requests.post", return_value=self.response(data={"unexpected": "response"})):
            with self.assertRaises(RuntimeError):
                send_gmail(self.executive, self.email())
