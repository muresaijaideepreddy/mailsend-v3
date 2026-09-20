from django.test import TestCase
from django.contrib.auth import get_user_model
from django.urls import reverse
from mail.models import Workspace, Membership
from mail.models import GoogleCredential

class AccountManagementTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.owner = User.objects.create_user('owner', 'owner@example.com', 'Initial-Password!2026')
        self.worker = User.objects.create_user('worker', 'worker@example.com', 'Initial-Password!2026')
        self.workspace = Workspace.objects.create(executive=self.owner, name='Lab')
        Membership.objects.create(user=self.owner, workspace=self.workspace, role='executive')
        self.membership = Membership.objects.create(user=self.worker, workspace=self.workspace, role='assistant')
        self.url = reverse('mail:assistant_password', args=[self.membership.pk])
    def test_owner_can_reset_worker_password(self):
        self.client.force_login(self.owner)
        response = self.client.post(self.url, {'new_password1': 'Fresh-Strong-Pass!2026', 'new_password2': 'Fresh-Strong-Pass!2026'})
        self.assertEqual(response.status_code, 302)
        self.worker.refresh_from_db()
        self.assertTrue(self.worker.check_password('Fresh-Strong-Pass!2026'))
    def test_assistant_cannot_reset_another_account(self):
        self.client.force_login(self.worker)
        self.assertEqual(self.client.post(self.url, {}).status_code, 403)
    def test_other_workspace_cannot_reset(self):
        owner = get_user_model().objects.create_user('other', 'other@example.com')
        workspace = Workspace.objects.create(executive=owner, name='Other')
        Membership.objects.create(user=owner, workspace=workspace, role='executive')
        self.client.force_login(owner)
        self.assertEqual(self.client.post(self.url, {}).status_code, 404)
    def test_password_must_match_and_be_strong(self):
        self.client.force_login(self.owner)
        response = self.client.post(self.url, {'new_password1': '123', 'new_password2': '123'})
        self.assertEqual(response.status_code, 200)
        self.worker.refresh_from_db()
        self.assertTrue(self.worker.check_password('Initial-Password!2026'))

    def test_named_worker_username_is_visible_in_team_and_password_form(self):
        self.worker.first_name = 'Named Assistant'
        self.worker.save(update_fields=['first_name'])
        self.client.force_login(self.owner)
        self.assertContains(self.client.get(reverse('mail:team')), 'Username: <strong>worker</strong>', html=True)
        self.assertContains(self.client.get(self.url), 'Login username: <strong>worker</strong>')

    def test_executive_can_set_worker_real_email_without_changing_login_username(self):
        self.worker.email = ''
        self.worker.save(update_fields=['email'])
        self.client.force_login(self.owner)
        url = reverse('mail:assistant_profile', args=[self.membership.pk])
        response = self.client.post(url, {'first_name': 'Taylor', 'email': 'Taylor@example.com'})
        self.assertEqual(response.status_code, 302)
        self.worker.refresh_from_db()
        self.assertEqual(self.worker.email, 'taylor@example.com')
        self.assertEqual(self.worker.first_name, 'Taylor')
        self.assertEqual(self.worker.username, 'worker')

    def test_worker_profile_change_rejects_duplicate_email_and_other_roles(self):
        url = reverse('mail:assistant_profile', args=[self.membership.pk])
        self.client.force_login(self.owner)
        response = self.client.post(url, {'first_name': 'Taylor', 'email': self.owner.email.upper()})
        self.assertContains(response, 'An account with this email already exists.')
        self.worker.refresh_from_db()
        self.assertEqual(self.worker.email, 'worker@example.com')
        self.client.force_login(self.worker)
        self.assertEqual(self.client.post(url, {'email': 'change@example.com'}).status_code, 403)
        outsider = get_user_model().objects.create_user('outside-owner')
        outside_workspace = Workspace.objects.create(executive=outsider, name='Other workspace')
        Membership.objects.create(user=outsider, workspace=outside_workspace, role='executive')
        self.client.force_login(outsider)
        self.assertEqual(self.client.get(url).status_code, 404)

    def test_linked_google_email_cannot_be_silently_reassigned(self):
        # No token decryption is needed to know an identity has been linked.
        GoogleCredential.objects.create(user=self.worker, encrypted_data='identity', subject_hash='a' * 64, connected=False)
        self.client.force_login(self.owner)
        url = reverse('mail:assistant_profile', args=[self.membership.pk])
        response = self.client.post(url, {'first_name': 'Taylor', 'email': 'different@example.com'})
        self.assertContains(response, 'This account is linked to Google.')
        self.worker.refresh_from_db()
        self.assertEqual(self.worker.email, 'worker@example.com')
        response = self.client.post(url, {'first_name': 'Taylor', 'email': self.worker.email})
        self.assertEqual(response.status_code, 302)
        self.worker.refresh_from_db()
        self.assertEqual(self.worker.first_name, 'Taylor')
