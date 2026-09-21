"""Worker accounts are created explicitly, never by visiting the Team page."""

from django.contrib.auth import get_user_model
from django.db import connection
from django.test import Client, TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from mail.models import AuditEvent, GoogleCredential, Membership, Workspace


class ExplicitWorkerSetupTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        User = get_user_model()
        cls.owner = User.objects.create_user('older-workspace-owner', email='owner@example.test')
        cls.other = User.objects.create_user('other-workspace-owner', email='other@example.test')
        cls.workspace = Workspace.objects.create(name='Older empty workspace', executive=cls.owner)
        cls.other_workspace = Workspace.objects.create(name='Other empty workspace', executive=cls.other)
        Membership.objects.create(user=cls.owner, workspace=cls.workspace, role=Membership.Role.EXECUTIVE)
        Membership.objects.create(user=cls.other, workspace=cls.other_workspace, role=Membership.Role.EXECUTIVE)

    def worker(self, **values):
        defaults = dict(username='existing-worker', email='worker@example.test', first_name='Existing Worker', password='Existing-Worker-Pass!2026')
        defaults.update(values)
        user = get_user_model().objects.create_user(**defaults)
        return Membership.objects.create(user=user, workspace=self.workspace, role=Membership.Role.ASSISTANT)

    def assert_empty_workspaces(self):
        self.assertFalse(Membership.objects.filter(role=Membership.Role.ASSISTANT).exists())
        self.assertEqual(get_user_model().objects.count(), 2)
        self.assertEqual(Membership.objects.count(), 2)
        self.assertFalse(AuditEvent.objects.exists())

    def test_empty_worker_page_displays_manual_creation_without_database_writes(self):
        self.client.force_login(self.owner)
        with CaptureQueriesContext(connection) as queries:
            response = self.client.get(reverse('mail:team'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'No assistant accounts yet.')
        self.assertContains(response, 'Create assistant account')
        writes = [query['sql'] for query in queries if query['sql'].lstrip().upper().startswith(('INSERT ', 'UPDATE ', 'DELETE '))]
        self.assertEqual(writes, [])
        self.assert_empty_workspaces()

    def test_repeated_worker_page_visits_leave_workspace_executive_only(self):
        self.client.force_login(self.owner)
        for _ in range(3):
            self.assertEqual(self.client.get(reverse('mail:team')).status_code, 200)
            self.assert_empty_workspaces()

    def test_invalid_worker_submission_creates_neither_requested_nor_default_account(self):
        self.client.force_login(self.owner)
        for data in ({}, {'username': 'requested-worker'}, {'username': 'requested-worker', 'password': '123'}):
            with self.subTest(data=data):
                response = self.client.post(reverse('mail:team'), data)
                self.assertEqual(response.status_code, 200)
                self.assertTrue(response.context['form'].errors)
                self.assertContains(response, 'No assistant accounts yet.')
                self.assert_empty_workspaces()

    def test_valid_submission_creates_only_the_requested_worker_in_owners_workspace(self):
        self.client.force_login(self.owner)
        password = 'Requested-Worker-Password!2026'
        response = self.client.post(reverse('mail:team'), {
            'username': 'requested-worker', 'first_name': 'Requested Worker', 'password': password,
            'workspace': self.other_workspace.pk, 'workspace_id': self.other_workspace.pk,
        })
        self.assertRedirects(response, reverse('mail:team'))
        membership = self.workspace.memberships.get(role=Membership.Role.ASSISTANT)
        worker = membership.user
        self.assertEqual(worker.username, 'requested-worker')
        self.assertEqual(worker.first_name, 'Requested Worker')
        self.assertEqual(worker.email, '')
        self.assertTrue(worker.check_password(password))
        self.assertFalse(GoogleCredential.objects.filter(user=worker).exists())
        self.assertEqual(get_user_model().objects.count(), 3)
        self.assertEqual(Membership.objects.filter(role=Membership.Role.ASSISTANT).count(), 1)
        self.assertFalse(self.other_workspace.memberships.filter(role=Membership.Role.ASSISTANT).exists())
        event = AuditEvent.objects.get(action='assistant.created')
        self.assertEqual(event.workspace_id, self.workspace.pk)
        self.assertEqual(event.actor_id, self.owner.pk)

    def test_existing_assistant_details_and_password_are_not_replaced(self):
        membership = self.worker()
        before = get_user_model().objects.get(pk=membership.user_id)
        original = (before.username, before.email, before.first_name, before.password)
        self.client.force_login(self.owner)
        response = self.client.get(reverse('mail:team'))
        self.assertEqual(response.status_code, 200)
        after = self.workspace.memberships.get(role=Membership.Role.ASSISTANT).user
        self.assertEqual(after.pk, before.pk)
        self.assertEqual((after.username, after.email, after.first_name, after.password), original)
        self.assertEqual(get_user_model().objects.count(), 3)

    def test_existing_default_named_worker_is_preserved_without_creating_another(self):
        membership = self.worker(username=f'worker-{self.owner.pk}', password=None)
        self.client.force_login(self.owner)
        for _ in range(2):
            response = self.client.get(reverse('mail:team'))
            self.assertContains(response, f'Username: <strong>{membership.user.username}</strong>', html=True)
            self.assertContains(response, reverse('mail:assistant_password', args=[membership.pk]))
        self.assertEqual(self.workspace.memberships.get(role=Membership.Role.ASSISTANT).pk, membership.pk)
        membership.user.refresh_from_db()
        self.assertFalse(membership.user.has_usable_password())
        self.assertEqual(get_user_model().objects.count(), 3)

    def test_assistant_cannot_open_worker_setup_or_create_accounts(self):
        membership = self.worker()
        original_users = list(get_user_model().objects.values_list('pk', flat=True))
        self.client.force_login(membership.user)
        self.assertEqual(self.client.get(reverse('mail:team')).status_code, 403)
        self.assertEqual(self.client.post(reverse('mail:team'), {
            'username': 'unauthorized-worker', 'password': 'No-Worker-Creation!2026',
        }).status_code, 403)
        self.assertEqual(list(get_user_model().objects.values_list('pk', flat=True)), original_users)
        self.assertEqual(Membership.objects.filter(role=Membership.Role.ASSISTANT).count(), 1)
        self.assertFalse(self.other_workspace.memberships.filter(role=Membership.Role.ASSISTANT).exists())

    def test_anonymous_worker_page_or_registration_post_creates_no_accounts(self):
        for method in (self.client.get, self.client.post):
            response = method(reverse('mail:team'), {
                'username': 'public-registration-attempt', 'password': 'No-Public-Registration!2026',
            })
            self.assertEqual(response.status_code, 302)
            self.assertTrue(response.url.startswith(reverse('mail:login')))
            self.assert_empty_workspaces()

    def test_executive_role_without_workspace_ownership_is_denied(self):
        # Deliberately inconsistent old data must not confer owner privileges.
        Membership.objects.filter(user=self.other).delete()
        Membership.objects.filter(user=self.owner).update(workspace=self.other_workspace)
        self.client.force_login(self.owner)
        self.assertEqual(self.client.get(reverse('mail:team')).status_code, 403)
        self.assertFalse(Membership.objects.filter(role=Membership.Role.ASSISTANT).exists())
        self.assertEqual(get_user_model().objects.count(), 2)

    def test_workspace_query_cannot_create_accounts_in_either_workspace(self):
        self.client.force_login(self.owner)
        response = self.client.get(reverse('mail:team'), {'workspace': self.other_workspace.pk, 'workspace_id': self.other_workspace.pk})
        self.assertEqual(response.status_code, 200)
        self.assert_empty_workspaces()

    def test_executive_can_reset_an_existing_workers_password(self):
        membership = self.worker()
        worker = membership.user
        worker_client = Client()
        self.assertTrue(worker_client.login(username=worker.username, password='Existing-Worker-Pass!2026'))
        self.client.force_login(self.owner)
        password = 'Fresh-Worker-Access!2026'
        response = self.client.post(reverse('mail:assistant_password', args=[membership.pk]), {
            'new_password1': password, 'new_password2': password,
        })
        self.assertRedirects(response, reverse('mail:team'), fetch_redirect_response=False)
        worker.refresh_from_db()
        self.assertTrue(worker.check_password(password))
        self.assertFalse(worker.check_password('Existing-Worker-Pass!2026'))
        self.assertEqual(worker_client.get(reverse('mail:dashboard')).status_code, 302)
        self.assertNotIn('_auth_user_id', worker_client.session)
        response = worker_client.post(reverse('mail:login'), {'username': worker.username, 'password': password})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(int(worker_client.session['_auth_user_id']), worker.pk)
        self.assertEqual(worker.membership.role, Membership.Role.ASSISTANT)
        self.assertEqual(worker_client.get(reverse('mail:team')).status_code, 403)
        self.assertEqual(worker_client.post(reverse('mail:send_current')).status_code, 403)

    def test_existing_unassigned_default_username_is_neither_adopted_nor_changed(self):
        collision = get_user_model().objects.create_user(f'worker-{self.owner.pk}', password='Unrelated-Account!2026')
        original = collision.password
        self.client.force_login(self.owner)
        self.assertEqual(self.client.get(reverse('mail:team')).status_code, 200)
        self.assertFalse(Membership.objects.filter(role=Membership.Role.ASSISTANT).exists())
        self.assertFalse(Membership.objects.filter(user=collision).exists())
        self.assertEqual(get_user_model().objects.count(), 3)
        collision.refresh_from_db()
        self.assertEqual(collision.password, original)
