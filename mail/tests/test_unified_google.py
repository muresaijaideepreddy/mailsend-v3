"""Public one-button Google flow, using synthetic identities and mocked Google.

The first verified identity selects the persisted role. A later Gmail grant must
remain tied to that identity and may only connect an executive account.
"""

import time
from html.parser import HTMLParser
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied
from django.urls import reverse

from mail.google_api import IDENTITY_SCOPES, SEND_SCOPE, decrypt_credentials, encrypt_credentials, subject_hash
from mail.models import GoogleCredential, Membership, Workspace
from mail.oauth_views import SESSION_KEY
from mail.services import require_executive
from mail.tests.test_google import GoogleTestCase


class _GoogleLinkParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.google_links = []

    def handle_starttag(self, tag, attrs):
        href = dict(attrs).get('href', '')
        if tag == 'a' and href.startswith('/accounts/google/'):
            self.google_links.append(href)


class UnifiedGoogleTests(GoogleTestCase):
    new_email = 'new-unified-executive@example.com'
    new_sub = 'new-unified-executive-subject'

    def setUp(self):
        # An unmocked OAuth exchange must fail this test, never use a network.
        self.enterContext(patch('mail.oauth_views.requests.post', side_effect=AssertionError('Unexpected network request')))

    def begin(self, **query):
        response = self.client.get(reverse('mail:google_signin'), query)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(urlparse(response.url).hostname, 'accounts.google.com')
        return self.client.session[SESSION_KEY], parse_qs(urlparse(response.url).query)

    def callback(self, flow, *, email=None, sub=None, send=False, token_changes=None, claims_changes=None, **query):
        tokens = {
            'id_token': 'verified-synthetic-id-token', 'access_token': 'synthetic-access-token',
            'expires_in': 3600, 'token_type': 'Bearer', 'scope': ' '.join(IDENTITY_SCOPES),
        }
        if send:
            tokens.update(scope=' '.join((*IDENTITY_SCOPES, SEND_SCOPE)), refresh_token='synthetic-refresh-token')
        tokens.update(token_changes or {})
        claims = {
            'iss': 'https://accounts.google.com', 'sub': sub or self.new_sub,
            'email': email or self.new_email, 'email_verified': True,
            'nonce': flow['nonce'], 'given_name': 'Unified',
        }
        claims.update(claims_changes or {})
        with patch('mail.oauth_views.requests.post', return_value=self.response(data=tokens)) as post, patch(
            'mail.oauth_views.id_token.verify_oauth2_token', return_value=claims,
        ):
            response = self.client.get(reverse('mail:google_callback'), {
                'state': flow['state'], 'code': 'synthetic-code', **query,
            })
        self.assertEqual(response.status_code, 302)
        return response, post

    def identity_link(self, user=None, sub='assistant-unified-subject'):
        user = user or self.assistant
        return GoogleCredential.objects.create(
            user=user, subject_hash=subject_hash(sub), connected=False,
            encrypted_data=encrypt_credentials({'sub': sub, 'email': user.email}),
        )

    def assert_no_new_account(self):
        self.assertFalse(get_user_model().objects.filter(email=self.new_email).exists())
        self.assertEqual(Workspace.objects.count(), 2)
        self.assertEqual(get_user_model().objects.count(), 3)
        self.assertNotIn('_auth_user_id', self.client.session)

    def assert_send_redirect(self, response):
        self.assertEqual(urlparse(response.url).hostname, 'accounts.google.com')
        query = parse_qs(urlparse(response.url).query)
        self.assertEqual(set(query['scope'][0].split()), {*IDENTITY_SCOPES, SEND_SCOPE})
        self.assertEqual(query['access_type'], ['offline'])
        return self.client.session[SESSION_KEY], query

    def begin_second_grant(self, *, email=None, sub=None):
        first, _ = self.begin()
        response, _ = self.callback(first, email=email, sub=sub)
        second, query = self.assert_send_redirect(response)
        self.assertNotEqual(first['state'], second['state'])
        self.assertNotEqual(first['nonce'], second['nonce'])
        self.assertNotEqual(first['verifier'], second['verifier'])
        return second, query

    def test_login_page_has_exactly_one_google_button_and_keeps_password_fields(self):
        response = self.client.get(reverse('mail:login'))
        parser = _GoogleLinkParser()
        parser.feed(response.content.decode())
        self.assertEqual(parser.google_links, [reverse('mail:google_signin')])
        self.assertContains(response, 'Sign in with Google', count=1)
        self.assertContains(response, 'name="username"')
        self.assertContains(response, 'name="password"')
        self.assertNotContains(response, 'Executive: sign in with Google')
        self.assertNotContains(response, 'Assistant: sign in with Google')

    def test_anonymous_entry_requests_only_identity_despite_role_or_mode_query(self):
        flow, query = self.begin(role='executive', mode='send', scope=SEND_SCOPE)
        self.assertEqual(set(query['scope'][0].split()), set(IDENTITY_SCOPES))
        self.assertNotIn('access_type', query)
        self.assertNotIn('include_granted_scopes', query)
        self.assertEqual(query['state'], [flow['state']])
        self.assertEqual(query['nonce'], [flow['nonce']])
        self.assertEqual(query['code_challenge_method'], ['S256'])
        self.assert_no_new_account()

    def test_linked_assistant_logs_in_without_sending_grant_or_new_workspace(self):
        record = self.identity_link()
        original = record.encrypted_data
        flow, _ = self.begin()
        response, _ = self.callback(flow, email=self.assistant.email, sub='assistant-unified-subject', send=True, role='executive', mode='send')
        self.assertRedirects(response, reverse('mail:dashboard'), fetch_redirect_response=False)
        self.assertEqual(int(self.client.session['_auth_user_id']), self.assistant.pk)
        self.assertNotIn(SESSION_KEY, self.client.session)
        record.refresh_from_db()
        self.assertEqual(record.encrypted_data, original)
        self.assertFalse(record.connected)
        self.assertEqual(self.assistant.membership.role, Membership.Role.ASSISTANT)
        self.assertEqual(Workspace.objects.count(), 2)
        with self.assertRaises(PermissionDenied):
            require_executive(self.assistant)
        self.assertEqual(self.client.get(reverse('mail:google_login')).status_code, 403)
        self.assertEqual(self.client.post(reverse('mail:google_disconnect')).status_code, 403)
        self.assertEqual(self.client.post(reverse('mail:send_current')).status_code, 403)

    def test_authenticated_assistant_can_link_using_shared_button_without_api_tokens(self):
        self.client.force_login(self.assistant)
        flow, query = self.begin(mode='send', role='executive')
        self.assertEqual(set(query['scope'][0].split()), set(IDENTITY_SCOPES))
        self.callback(flow, email=self.assistant.email, sub='assistant-unified-subject', send=True)
        record = GoogleCredential.objects.get(user=self.assistant)
        self.assertFalse(record.connected)
        self.assertEqual(decrypt_credentials(record), {'sub': 'assistant-unified-subject', 'email': self.assistant.email})

    def test_authenticated_assistant_cannot_link_a_different_email(self):
        self.client.force_login(self.assistant)
        flow, _ = self.begin()
        self.callback(flow, email=self.other.email, sub='other-unified-subject')
        self.assertFalse(GoogleCredential.objects.filter(user=self.assistant).exists())
        self.assertEqual(int(self.client.session['_auth_user_id']), self.assistant.pk)

    def test_existing_local_email_never_silently_links_or_becomes_an_executive(self):
        for user in (self.assistant, self.executive):
            with self.subTest(role=user.membership.role):
                flow, _ = self.begin()
                response, _ = self.callback(flow, email=user.email)
                self.assertRedirects(response, reverse('mail:login'), fetch_redirect_response=False)
                self.assertNotIn(SESSION_KEY, self.client.session)
                self.assertFalse(GoogleCredential.objects.filter(user=user).exists())
                self.assert_no_new_account()

    def test_healthy_linked_executive_signin_preserves_sending_credentials(self):
        record = self.connection()
        original, updated_at = record.encrypted_data, record.updated_at
        flow, _ = self.begin()
        response, _ = self.callback(flow, email=self.executive.email, sub='subject-123')
        self.assertRedirects(response, reverse('mail:dashboard'), fetch_redirect_response=False)
        self.assertEqual(int(self.client.session['_auth_user_id']), self.executive.pk)
        self.assertNotIn(SESSION_KEY, self.client.session)
        record.refresh_from_db()
        self.assertEqual(record.encrypted_data, original)
        self.assertEqual(record.updated_at, updated_at)
        self.assertTrue(record.connected)

    def test_disconnected_executive_reauthenticates_before_sending_is_restored(self):
        record = self.identity_link(self.executive, sub='subject-123')
        original = record.encrypted_data
        second, query = self.begin_second_grant(email=self.executive.email, sub='subject-123')
        self.assertIn(query['login_hint'][0], (self.executive.email, 'subject-123'))
        self.assertNotIn('_auth_user_id', self.client.session)
        record.refresh_from_db()
        self.assertFalse(record.connected)
        self.assertEqual(record.encrypted_data, original)
        response, _ = self.callback(second, email=self.executive.email, sub='subject-123', send=True)
        self.assertRedirects(response, reverse('mail:dashboard'), fetch_redirect_response=False)
        self.assertEqual(int(self.client.session['_auth_user_id']), self.executive.pk)
        record.refresh_from_db()
        self.assertTrue(record.connected)
        self.assertEqual(decrypt_credentials(record)['refresh_token'], 'synthetic-refresh-token')
        self.assertEqual(Workspace.objects.count(), 2)

    def test_corrupt_executive_tokens_can_recover_only_after_verified_second_grant(self):
        record = self.connection()
        GoogleCredential.objects.filter(pk=record.pk).update(encrypted_data='corrupt-ciphertext', connected=True)
        second, _ = self.begin_second_grant(email=self.executive.email, sub='subject-123')
        self.assertNotIn('_auth_user_id', self.client.session)
        self.callback(second, email=self.executive.email, sub='subject-123', send=True)
        record.refresh_from_db()
        self.assertEqual(decrypt_credentials(record)['sub'], 'subject-123')
        self.assertTrue(record.connected)
        self.assertEqual(int(self.client.session['_auth_user_id']), self.executive.pk)

    def test_executive_without_send_scope_must_grant_it_after_identity(self):
        self.connection(scope=' '.join(IDENTITY_SCOPES))
        second, _ = self.begin_second_grant(email=self.executive.email, sub='subject-123')
        self.assertNotIn('_auth_user_id', self.client.session)
        self.callback(second, email=self.executive.email, sub='subject-123', send=True)
        self.assertIn(SEND_SCOPE, decrypt_credentials(GoogleCredential.objects.get(user=self.executive))['scope'].split())

    def test_new_executive_is_provisioned_only_after_same_identity_grants_sending(self):
        second, query = self.begin_second_grant()
        self.assertIn(query['login_hint'][0], (self.new_email, self.new_sub))
        self.assert_no_new_account()
        self.assertFalse(GoogleCredential.objects.exists())
        response, _ = self.callback(second, send=True)
        self.assertRedirects(response, reverse('mail:dashboard'), fetch_redirect_response=False)
        user = get_user_model().objects.get(email=self.new_email)
        self.assertEqual(user.membership.role, Membership.Role.EXECUTIVE)
        self.assertEqual(user.membership.workspace.executive_id, user.pk)
        self.assertFalse(user.has_usable_password())
        worker = user.membership.workspace.memberships.get(role=Membership.Role.ASSISTANT).user
        self.assertFalse(worker.has_usable_password())
        self.assertEqual(worker.email, '')
        self.assertEqual(int(self.client.session['_auth_user_id']), user.pk)
        self.assertNotIn(SESSION_KEY, self.client.session)
        self.assertEqual(Workspace.objects.count(), 3)
        self.assertTrue(GoogleCredential.objects.get(user=user).connected)

    def test_new_identity_cannot_skip_second_grant_by_returning_send_tokens_early(self):
        first, _ = self.begin()
        response, _ = self.callback(first, send=True, mode='send', role='executive')
        self.assert_send_redirect(response)
        self.assert_no_new_account()
        self.assertFalse(GoogleCredential.objects.exists())

    def test_second_grant_rejects_subject_swap_and_email_swap(self):
        for changes in ({'sub': 'different-subject'}, {'email': 'different@example.com'}):
            with self.subTest(changes=changes):
                second, _ = self.begin_second_grant()
                response, _ = self.callback(second, send=True, **changes)
                self.assertRedirects(response, reverse('mail:login'), fetch_redirect_response=False)
                self.assert_no_new_account()
                self.assertFalse(GoogleCredential.objects.exists())
                self.assertNotIn(SESSION_KEY, self.client.session)

    def test_second_grant_cannot_switch_to_an_existing_linked_executive(self):
        record = self.connection()
        original = record.encrypted_data
        second, _ = self.begin_second_grant()
        self.callback(second, email=self.executive.email, sub='subject-123', send=True)
        self.assert_no_new_account()
        record.refresh_from_db()
        self.assertEqual(record.encrypted_data, original)

    def test_second_grant_denial_creates_nothing_and_does_not_exchange_code(self):
        second, _ = self.begin_second_grant()
        with patch('mail.oauth_views.requests.post') as post:
            self.client.get(reverse('mail:google_callback'), {'state': second['state'], 'error': 'access_denied'})
        post.assert_not_called()
        self.assert_no_new_account()
        self.assertNotIn(SESSION_KEY, self.client.session)
        self.assertFalse(GoogleCredential.objects.exists())

    def test_second_grant_without_send_scope_or_refresh_token_creates_nothing(self):
        for changes in ({'scope': ' '.join(IDENTITY_SCOPES)}, {'refresh_token': ''}):
            with self.subTest(changes=changes):
                second, _ = self.begin_second_grant()
                self.callback(second, send=True, token_changes=changes)
                self.assert_no_new_account()
                self.assertFalse(GoogleCredential.objects.exists())
                self.assertNotIn(SESSION_KEY, self.client.session)

    def test_second_grant_invalid_or_unverified_claims_create_nothing(self):
        for changes in ({'nonce': 'wrong-nonce'}, {'email_verified': False}, {'iss': 'https://wrong-issuer.example'}):
            with self.subTest(changes=changes):
                second, _ = self.begin_second_grant()
                self.callback(second, send=True, claims_changes=changes)
                self.assert_no_new_account()
                self.assertFalse(GoogleCredential.objects.exists())

    def test_second_grant_expiry_and_state_mismatch_fail_before_network(self):
        for failure in ('expired', 'state-mismatch'):
            with self.subTest(failure=failure):
                second, _ = self.begin_second_grant()
                if failure == 'expired':
                    session = self.client.session
                    second['started_at'] = time.time() - 601
                    session[SESSION_KEY] = second
                    session.save()
                with patch('mail.oauth_views.requests.post') as post:
                    self.client.get(reverse('mail:google_callback'), {
                        'state': second['state'] if failure == 'expired' else 'different-state', 'code': 'synthetic-code',
                    })
                post.assert_not_called()
                self.assert_no_new_account()
                self.assertNotIn(SESSION_KEY, self.client.session)

    def test_second_grant_callback_cannot_be_replayed(self):
        second, _ = self.begin_second_grant()
        self.callback(second, send=True)
        user_count, workspace_count = get_user_model().objects.count(), Workspace.objects.count()
        with patch('mail.oauth_views.requests.post') as post:
            self.client.get(reverse('mail:google_callback'), {'state': second['state'], 'code': 'synthetic-code'})
        post.assert_not_called()
        self.assertEqual(get_user_model().objects.count(), user_count)
        self.assertEqual(Workspace.objects.count(), workspace_count)

    def test_second_grant_is_invalidated_if_local_user_signs_in_during_google_flow(self):
        second, _ = self.begin_second_grant()
        self.client.force_login(self.assistant)
        session = self.client.session
        session[SESSION_KEY] = second
        session.save()
        with patch('mail.oauth_views.requests.post') as post:
            self.client.get(reverse('mail:google_callback'), {'state': second['state'], 'code': 'synthetic-code'})
        post.assert_not_called()
        self.assertFalse(get_user_model().objects.filter(email=self.new_email).exists())
        self.assertFalse(GoogleCredential.objects.exists())
        self.assertEqual(int(self.client.session['_auth_user_id']), self.assistant.pk)

    def test_disconnected_executive_second_grant_cannot_switch_to_other_account(self):
        record = self.identity_link(self.executive, sub='subject-123')
        original = record.encrypted_data
        second, _ = self.begin_second_grant(email=self.executive.email, sub='subject-123')
        self.callback(second, send=True)
        record.refresh_from_db()
        self.assertFalse(record.connected)
        self.assertEqual(record.encrypted_data, original)
        self.assert_no_new_account()

    def test_inactive_linked_user_cannot_use_shared_google_signin(self):
        for user, sub in ((self.assistant, 'assistant-unified-subject'), (self.executive, 'subject-123')):
            with self.subTest(role=user.membership.role):
                self.identity_link(user, sub=sub)
                get_user_model().objects.filter(pk=user.pk).update(is_active=False)
                flow, _ = self.begin()
                response, _ = self.callback(flow, email=user.email, sub=sub)
                self.assertRedirects(response, reverse('mail:login'), fetch_redirect_response=False)
                self.assertNotIn('_auth_user_id', self.client.session)
                self.assertNotIn(SESSION_KEY, self.client.session)
                self.assertEqual(Workspace.objects.count(), 2)

    def test_executive_disabled_during_second_grant_cannot_sign_in_or_reconnect(self):
        record = self.identity_link(self.executive, sub='subject-123')
        original = record.encrypted_data
        second, _ = self.begin_second_grant(email=self.executive.email, sub='subject-123')
        get_user_model().objects.filter(pk=self.executive.pk).update(is_active=False)
        self.callback(second, email=self.executive.email, sub='subject-123', send=True)
        record.refresh_from_db()
        self.assertFalse(record.connected)
        self.assertEqual(record.encrypted_data, original)
        self.assertNotIn('_auth_user_id', self.client.session)

    def test_executive_role_revoked_during_second_grant_cannot_reconnect(self):
        record = self.identity_link(self.executive, sub='subject-123')
        original = record.encrypted_data
        second, _ = self.begin_second_grant(email=self.executive.email, sub='subject-123')
        Membership.objects.filter(user=self.executive).update(role=Membership.Role.ASSISTANT)
        self.callback(second, email=self.executive.email, sub='subject-123', send=True)
        record.refresh_from_db()
        self.assertFalse(record.connected)
        self.assertEqual(record.encrypted_data, original)
        self.assertNotIn('_auth_user_id', self.client.session)

    def test_executive_link_deleted_during_second_grant_cannot_create_replacement(self):
        record = self.identity_link(self.executive, sub='subject-123')
        second, _ = self.begin_second_grant(email=self.executive.email, sub='subject-123')
        record.delete()
        self.callback(second, email=self.executive.email, sub='subject-123', send=True)
        self.assertFalse(GoogleCredential.objects.exists())
        self.assertNotIn('_auth_user_id', self.client.session)
        self.assertEqual(Workspace.objects.count(), 2)
        self.assertEqual(get_user_model().objects.count(), 3)

    def test_new_identity_linked_elsewhere_during_second_grant_cannot_change_target(self):
        second, _ = self.begin_second_grant()
        record = self.identity_link(self.other, sub=self.new_sub)
        original = record.encrypted_data
        self.callback(second, send=True)
        record.refresh_from_db()
        self.assertEqual(record.encrypted_data, original)
        self.assertFalse(record.connected)
        self.assert_no_new_account()

    def test_local_email_registered_during_second_grant_is_not_auto_linked(self):
        second, _ = self.begin_second_grant()
        local = get_user_model().objects.create_user('locally-created-during-consent', email=self.new_email)
        self.callback(second, send=True)
        self.assertFalse(GoogleCredential.objects.filter(user=local).exists())
        self.assertEqual(get_user_model().objects.filter(email=self.new_email).count(), 1)
        self.assertEqual(Workspace.objects.count(), 2)
        self.assertNotIn('_auth_user_id', self.client.session)
