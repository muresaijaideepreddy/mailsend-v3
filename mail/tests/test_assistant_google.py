"""Assistants use passwords; historical Google links and callbacks are denied."""

import time
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

from django.contrib.auth import get_user_model
from django.urls import reverse

from mail.google_api import IDENTITY_SCOPES, SEND_SCOPE, encrypt_credentials, subject_hash
from mail.models import GoogleCredential, Membership, Workspace
from mail.oauth_views import SESSION_KEY
from mail.provisioning import ensure_initial_worker
from mail.tests.test_google import GoogleTestCase


class AssistantGoogleTests(GoogleTestCase):
    def begin_identity(self):
        response = self.client.get(reverse('mail:google_identity_login'))
        self.assertEqual(response.status_code, 302)
        return self.client.session[SESSION_KEY], parse_qs(urlparse(response.url).query)

    def finish_identity(self, flow, *, email=None, sub='assistant-sub', tokens=None, **extra_query):
        email = email or self.assistant.email
        claims = {'iss': 'https://accounts.google.com', 'sub': sub, 'email': email, 'email_verified': True, 'nonce': flow['nonce']}
        response_tokens = {'id_token': 'verified-test-id', 'access_token': 'discard-this-token', 'scope': ' '.join(IDENTITY_SCOPES), 'expires_in': 3600}
        response_tokens.update(tokens or {})
        with patch('mail.oauth_views.requests.post', return_value=self.response(data=response_tokens)), patch('mail.oauth_views.id_token.verify_oauth2_token', return_value=claims):
            return self.client.get(reverse('mail:google_callback'), {'state': flow['state'], 'code': 'test-code', **extra_query})

    def legacy_assistant_link(self):
        return GoogleCredential.objects.create(
            user=self.assistant, subject_hash=subject_hash('assistant-sub'), connected=False,
            encrypted_data=encrypt_credentials({'sub': 'assistant-sub', 'email': self.assistant.email}),
        )

    def test_local_assistant_cannot_start_legacy_identity_link(self):
        self.client.force_login(self.assistant)
        self.assertEqual(self.client.get(reverse('mail:google_identity_login')).status_code, 403)
        self.assertNotIn(SESSION_KEY, self.client.session)
        self.assertFalse(GoogleCredential.objects.exists())

    def test_anonymous_email_match_cannot_link_existing_assistant(self):
        flow, _ = self.begin_identity()
        self.finish_identity(flow)
        self.assertNotIn('_auth_user_id', self.client.session)
        self.assertFalse(GoogleCredential.objects.filter(user=self.assistant).exists())
        self.assertEqual(Workspace.objects.count(), 2)

    def test_legacy_linked_assistant_is_denied_for_every_persisted_callback_mode(self):
        record = self.legacy_assistant_link()
        original = record.encrypted_data
        for mode in ('identity', 'send', 'auto'):
            with self.subTest(mode=mode):
                flow, _ = self.begin_identity()
                session = self.client.session
                flow['mode'] = mode
                session[SESSION_KEY] = flow
                session.save()
                response = self.finish_identity(flow, tokens={
                    'scope': ' '.join((*IDENTITY_SCOPES, SEND_SCOPE)), 'refresh_token': 'discard-refresh',
                })
                self.assertRedirects(response, reverse('mail:login'), fetch_redirect_response=False)
                self.assertNotIn('_auth_user_id', self.client.session)
                self.assertNotIn(SESSION_KEY, self.client.session)
                record.refresh_from_db()
                self.assertEqual(record.encrypted_data, original)
                self.assertFalse(record.connected)
                self.assertEqual(GoogleCredential.objects.count(), 1)
                self.assertEqual(Workspace.objects.count(), 2)
                self.assertEqual(get_user_model().objects.count(), 3)

    def test_identity_login_keeps_executive_mail_credentials_exactly_unchanged(self):
        record = self.connection()
        original = record.encrypted_data
        self.client.logout()
        flow, _ = self.begin_identity()
        self.finish_identity(flow, email=self.executive.email, sub='subject-123')
        record.refresh_from_db()
        self.assertEqual(int(self.client.session['_auth_user_id']), self.executive.pk)
        self.assertEqual(record.encrypted_data, original)
        self.assertTrue(record.connected)

    def test_identity_login_does_not_reconnect_disconnected_sending(self):
        record = self.connection()
        self.client.force_login(self.executive)
        self.client.post(reverse('mail:google_disconnect'))
        record.refresh_from_db()
        original = record.encrypted_data
        self.client.logout()
        flow, _ = self.begin_identity()
        self.finish_identity(flow, email=self.executive.email, sub='subject-123')
        record.refresh_from_db()
        self.assertFalse(record.connected)
        self.assertEqual(record.encrypted_data, original)

    def test_inactive_linked_assistant_cannot_sign_in(self):
        self.legacy_assistant_link()
        get_user_model().objects.filter(pk=self.assistant.pk).update(is_active=False)
        flow, _ = self.begin_identity()
        self.finish_identity(flow)
        self.assertNotIn('_auth_user_id', self.client.session)

    def test_in_progress_assistant_callback_is_denied_before_token_exchange(self):
        self.client.force_login(self.assistant)
        # A server-side flow started before the password-only deployment must
        # stop even though its state, time and logged-in account still match.
        for mode in ('identity', 'send', 'auto'):
            with self.subTest(mode=mode):
                session = self.client.session
                session[SESSION_KEY] = {
                    'state': 'old-flow-state', 'nonce': 'old-nonce', 'verifier': 'old-verifier',
                    'started_at': time.time(), 'user_id': self.assistant.pk, 'mode': mode,
                }
                session.save()
                with patch('mail.oauth_views.requests.post') as post:
                    response = self.client.get(reverse('mail:google_callback'), {
                        'state': 'old-flow-state', 'code': 'old-code', 'mode': 'send',
                    })
                post.assert_not_called()
                self.assertRedirects(response, reverse('mail:dashboard'), fetch_redirect_response=False)
                self.assertNotIn(SESSION_KEY, self.client.session)
                self.assertEqual(int(self.client.session['_auth_user_id']), self.assistant.pk)
                self.assertFalse(GoogleCredential.objects.exists())

    def test_worker_password_login_still_works_after_google_login_is_removed(self):
        self.assistant.set_password('Assistant-local-password-2026!')
        self.assistant.save(update_fields=['password'])
        self.legacy_assistant_link()
        response = self.client.post(reverse('mail:login'), {
            'username': self.assistant.username, 'password': 'Assistant-local-password-2026!',
        })
        self.assertRedirects(response, reverse('mail:dashboard'), fetch_redirect_response=False)
        self.assertEqual(int(self.client.session['_auth_user_id']), self.assistant.pk)

    def test_unknown_assistant_google_signin_does_not_create_executive_or_workspace(self):
        flow, _ = self.begin_identity()
        self.finish_identity(flow, email='new-manager@example.com', sub='new-manager-sub')
        self.assertNotIn('_auth_user_id', self.client.session)
        self.assertFalse(get_user_model().objects.filter(email='new-manager@example.com').exists())
        self.assertEqual(Workspace.objects.count(), 2)
        self.assertFalse(GoogleCredential.objects.exists())


class InitialWorkerTests(GoogleTestCase):
    def test_provisioning_preserves_existing_worker_account(self):
        worker = ensure_initial_worker(self.workspace)
        self.assertEqual(worker.user_id, self.assistant.pk)
        self.assertEqual(self.workspace.memberships.filter(role='assistant').count(), 1)

    def test_new_worker_has_no_usable_password_email_or_assumed_google_identity(self):
        owner = get_user_model().objects.create_user('new-owner')
        workspace = Workspace.objects.create(name='New workspace', executive=owner)
        get_user_model().objects.create_user(f'worker-{owner.pk}')
        worker = ensure_initial_worker(workspace)
        self.assertEqual(worker.user.username, f'worker-{owner.pk}-2')
        self.assertEqual(worker.user.email, '')
        self.assertFalse(worker.user.has_usable_password())
        self.assertFalse(GoogleCredential.objects.filter(user=worker.user).exists())
        self.assertEqual(ensure_initial_worker(workspace).pk, worker.pk)
