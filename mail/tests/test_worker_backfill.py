"""Older workspaces get their V3 worker account through executive setup."""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

from django.contrib.auth import get_user_model
from django.db import close_old_connections, connection
from django.test import Client, TestCase, TransactionTestCase
from django.urls import reverse

from mail.models import GoogleCredential, Membership, Workspace


class WorkerBackfillTests(TestCase):
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
        self.assertEqual(Membership.objects.filter(role=Membership.Role.ASSISTANT).count(), 0)
        self.assertEqual(get_user_model().objects.count(), 2)

    def test_older_empty_workspace_gets_one_worker_with_no_usable_password(self):
        self.client.force_login(self.owner)
        response = self.client.get(reverse('mail:team'))
        self.assertEqual(response.status_code, 200)
        membership = self.workspace.memberships.get(role=Membership.Role.ASSISTANT)
        worker = membership.user
        self.assertEqual(worker.username, f'worker-{self.owner.pk}')
        self.assertEqual(worker.email, '')
        self.assertFalse(worker.has_usable_password())
        self.assertFalse(worker.check_password('MailSend-Demo-2026!'))
        self.assertFalse(GoogleCredential.objects.filter(user=worker).exists())
        self.assertContains(response, f'Username: <strong>{worker.username}</strong>', html=True)
        self.assertContains(response, reverse('mail:assistant_password', args=[membership.pk]))
        self.assertContains(response, 'Set a password')
        self.assertFalse(self.other_workspace.memberships.filter(role=Membership.Role.ASSISTANT).exists())

    def test_repeated_worker_page_visits_preserve_same_single_account(self):
        self.client.force_login(self.owner)
        self.client.get(reverse('mail:team'))
        first = self.workspace.memberships.get(role=Membership.Role.ASSISTANT)
        original = (first.pk, first.user_id, first.user.username, first.user.password)
        self.client.get(reverse('mail:team'))
        current = self.workspace.memberships.get(role=Membership.Role.ASSISTANT)
        self.assertEqual((current.pk, current.user_id, current.user.username, current.user.password), original)
        self.assertEqual(get_user_model().objects.count(), 3)

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

    def test_assistant_cannot_open_worker_setup_or_provision_accounts(self):
        membership = self.worker()
        original_users = list(get_user_model().objects.values_list('pk', flat=True))
        self.client.force_login(membership.user)
        self.assertEqual(self.client.get(reverse('mail:team')).status_code, 403)
        self.assertEqual(self.client.post(reverse('mail:team'), {}).status_code, 403)
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

    def test_executive_role_without_workspace_ownership_is_denied_before_backfill(self):
        # Deliberately inconsistent old data must not confer owner privileges.
        Membership.objects.filter(user=self.other).delete()
        Membership.objects.filter(user=self.owner).update(workspace=self.other_workspace)
        self.client.force_login(self.owner)
        self.assertEqual(self.client.get(reverse('mail:team')).status_code, 403)
        self.assert_empty_workspaces()

    def test_workspace_query_cannot_provision_a_different_executives_workspace(self):
        self.client.force_login(self.owner)
        response = self.client.get(reverse('mail:team'), {'workspace': self.other_workspace.pk, 'workspace_id': self.other_workspace.pk})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.workspace.memberships.filter(role=Membership.Role.ASSISTANT).count(), 1)
        self.assertFalse(self.other_workspace.memberships.filter(role=Membership.Role.ASSISTANT).exists())

    def test_executive_sets_password_then_worker_can_login_with_that_username(self):
        self.client.force_login(self.owner)
        self.client.get(reverse('mail:team'))
        membership = self.workspace.memberships.get(role=Membership.Role.ASSISTANT)
        worker = membership.user
        worker_client = Client()
        self.assertFalse(worker_client.login(username=worker.username, password='MailSend-Demo-2026!'))
        password = 'Fresh-Worker-Access!2026'
        response = self.client.post(reverse('mail:assistant_password', args=[membership.pk]), {
            'new_password1': password, 'new_password2': password,
        })
        self.assertRedirects(response, reverse('mail:team'), fetch_redirect_response=False)
        worker.refresh_from_db()
        self.assertTrue(worker.check_password(password))
        response = worker_client.post(reverse('mail:login'), {'username': worker.username, 'password': password})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(int(worker_client.session['_auth_user_id']), worker.pk)
        self.assertEqual(worker.membership.role, Membership.Role.ASSISTANT)
        self.assertEqual(worker_client.get(reverse('mail:team')).status_code, 403)
        self.assertEqual(worker_client.post(reverse('mail:send_current')).status_code, 403)

    def test_existing_username_collision_provisions_a_distinct_worker(self):
        collision = get_user_model().objects.create_user(f'worker-{self.owner.pk}', password='Unrelated-Account!2026')
        original = collision.password
        self.client.force_login(self.owner)
        self.client.get(reverse('mail:team'))
        worker = self.workspace.memberships.get(role=Membership.Role.ASSISTANT).user
        self.assertEqual(worker.username, f'worker-{self.owner.pk}-2')
        self.assertNotEqual(worker.pk, collision.pk)
        self.assertFalse(worker.has_usable_password())
        collision.refresh_from_db()
        self.assertEqual(collision.password, original)


class ConcurrentWorkerBackfillTests(TransactionTestCase):
    def test_simultaneous_first_visits_create_only_one_worker_and_retry_safely(self):
        owner = get_user_model().objects.create_user('concurrent-worker-owner')
        workspace = Workspace.objects.create(name='Concurrent empty workspace', executive=owner)
        Membership.objects.create(user=owner, workspace=workspace, role=Membership.Role.EXECUTIVE)
        clients = [Client(), Client()]
        for client in clients:
            client.force_login(owner)
        barrier = Barrier(2, timeout=10)

        def visit(client):
            close_old_connections()
            synchronized = False

            def synchronize_first_write(execute, sql, params, many, context):
                nonlocal synchronized
                # Both requests have observed an empty workspace when they
                # reach its first write, so the race cannot pass by accident.
                if not synchronized and sql.lstrip().upper().startswith('UPDATE "MAIL_WORKSPACE"'):
                    synchronized = True
                    barrier.wait()
                return execute(sql, params, many, context)

            try:
                with connection.execute_wrapper(synchronize_first_write):
                    return client.get(reverse('mail:team')).status_code
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=2) as executor:
            statuses = list(executor.map(visit, clients))
        # File SQLite waits for a writer; shared-memory SQLite can immediately
        # return SQLITE_LOCKED. Either must remain a safe, retryable outcome.
        self.assertIn(sorted(statuses), ([200, 200], [200, 409]))
        membership = workspace.memberships.get(role=Membership.Role.ASSISTANT)
        self.assertFalse(membership.user.has_usable_password())
        for client in clients:
            self.assertEqual(client.get(reverse('mail:team')).status_code, 200)
        self.assertEqual(workspace.memberships.get(role=Membership.Role.ASSISTANT).pk, membership.pk)
        self.assertEqual(get_user_model().objects.count(), 2)
