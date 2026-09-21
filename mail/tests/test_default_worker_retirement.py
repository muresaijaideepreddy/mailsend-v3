"""The default-worker cleanup preserves configured accounts and is reversible."""

from importlib import import_module
from types import SimpleNamespace

from django.contrib.auth import get_user_model
from django.contrib.auth.backends import ModelBackend
from django.contrib.auth.models import Group, Permission
from django.db import connection
from django.db.migrations.loader import MigrationLoader
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from mail.models import AuditEvent, GoogleCredential, Membership, MergeReceipt, Message, Workspace


migration = import_module("mail.migrations.0006_retire_unused_default_workers")


class DefaultWorkerRetirementTests(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.historical_apps = MigrationLoader(connection).project_state(
            [("mail", "0005_message_date_ordering")]
        ).apps

    def setUp(self):
        self.owner = get_user_model().objects.create_user("retirement-owner")
        self.workspace = Workspace.objects.create(name="Retirement test", executive=self.owner)
        Membership.objects.create(user=self.owner, workspace=self.workspace, role="executive")
        self.editor = SimpleNamespace(connection=connection)
        self.counter = 1

    def worker(self, **fields):
        suffix = "" if self.counter == 1 else f"-{self.counter}"
        self.counter += 1
        fields.setdefault("username", f"worker-{self.owner.pk}{suffix}")
        worker = get_user_model().objects.create_user(**fields)
        Membership.objects.create(user=worker, workspace=self.workspace, role="assistant")
        return worker

    def forward(self):
        migration.retire_unused_defaults(self.historical_apps, self.editor)

    def backward(self):
        migration.restore_unused_defaults(self.historical_apps, self.editor)

    def marker(self, worker):
        return AuditEvent.objects.filter(action=migration.ACTION, detail=f"User {worker.pk}")

    def test_unused_worker_disappears_from_team_and_authentication_without_deletion(self):
        worker = self.worker()
        membership = worker.membership
        original_user = get_user_model().objects.values().get(pk=worker.pk)
        self.assertIsNotNone(ModelBackend().get_user(worker.pk))
        self.client.force_login(self.owner)
        self.assertContains(self.client.get(reverse("mail:team")), worker.username)

        self.forward()

        worker.refresh_from_db()
        self.assertFalse(worker.is_active)
        self.assertIsNone(ModelBackend().get_user(worker.pk))
        self.assertNotContains(self.client.get(reverse("mail:team")), worker.username)
        self.assertEqual(Membership.objects.get(pk=membership.pk).user_id, worker.pk)
        self.assertEqual(Membership.objects.get(pk=membership.pk).workspace_id, self.workspace.pk)
        original_user["is_active"] = False
        self.assertEqual(get_user_model().objects.values().get(pk=worker.pk), original_user)
        marker = self.marker(worker).get()
        self.assertIsNone(marker.actor_id)
        self.assertIsNone(marker.message_id)
        self.assertEqual(marker.workspace_id, self.workspace.pk)

    def test_numeric_collision_suffixes_are_retired_but_other_names_are_preserved(self):
        retired = [self.worker() for _ in range(12)]
        preserved = [self.worker(username=name) for name in (
            "worker", f"worker-{self.owner.pk}-1", f"worker-{self.owner.pk}-02",
            f"worker-{self.owner.pk}-2-extra", "worker-9999999",
        )]
        self.forward()
        self.assertFalse(get_user_model().objects.filter(pk__in=[u.pk for u in retired], is_active=True).exists())
        self.assertEqual(get_user_model().objects.filter(pk__in=[u.pk for u in preserved], is_active=True).count(), len(preserved))

    def test_configured_accounts_are_preserved(self):
        workers = [self.worker(**fields) for fields in (
            {"email": "worker@example.test"}, {"first_name": "Named"}, {"last_name": "Worker"},
            {"password": "Configured-Password!2026"}, {"last_login": timezone.now()},
            {"is_staff": True}, {"is_superuser": True},
        )]
        grouped, permitted = self.worker(), self.worker()
        grouped.groups.add(Group.objects.create(name="Kept worker group"))
        permitted.user_permissions.add(Permission.objects.first())
        workers.extend([grouped, permitted])
        self.forward()
        self.assertEqual(get_user_model().objects.filter(pk__in=[u.pk for u in workers], is_active=True).count(), len(workers))
        self.assertFalse(AuditEvent.objects.filter(action=migration.ACTION).exists())

    def test_used_or_manually_created_accounts_are_preserved_with_their_records(self):
        authored, google, merge, actor = [self.worker() for _ in range(4)]
        draft = Message.objects.create(workspace=self.workspace, created_by=authored, to="recipient@example.test", subject="Kept", body="Kept")
        credential = GoogleCredential.objects.create(user=google, encrypted_data="test-only", connected=False)
        receipt = MergeReceipt.objects.create(user=merge, token="a" * 64)
        AuditEvent.objects.create(workspace=self.workspace, actor=actor, action="message.previewed")
        referenced = []
        for action in ("assistant.created", "assistant.profile_updated", "assistant.password_changed"):
            worker = self.worker()
            referenced.append(worker)
            AuditEvent.objects.create(workspace=self.workspace, actor=self.owner, action=action, detail=f"User {worker.pk}")
        unrelated = self.worker()
        AuditEvent.objects.create(workspace=self.workspace, actor=self.owner, action="assistant.created", detail=f"User {unrelated.pk}0")
        self.forward()
        for worker in [authored, google, merge, actor, *referenced]:
            worker.refresh_from_db()
            self.assertTrue(worker.is_active)
            self.assertFalse(self.marker(worker).exists())
        unrelated.refresh_from_db()
        self.assertFalse(unrelated.is_active)
        self.assertTrue(Message.objects.filter(pk=draft.pk).exists())
        self.assertTrue(GoogleCredential.objects.filter(pk=credential.pk).exists())
        self.assertTrue(MergeReceipt.objects.filter(pk=receipt.pk).exists())

    def test_forward_and_reverse_are_idempotent_and_do_not_restore_preexisting_inactive_users(self):
        worker = self.worker()
        inactive = self.worker(is_active=False)
        self.forward()
        self.forward()
        self.assertEqual(self.marker(worker).count(), 1)
        self.assertFalse(self.marker(inactive).exists())
        self.backward()
        self.backward()
        worker.refresh_from_db()
        inactive.refresh_from_db()
        self.assertTrue(worker.is_active)
        self.assertFalse(inactive.is_active)
        self.assertFalse(self.marker(worker).exists())

    def test_reverse_keeps_used_retired_accounts_inactive_and_retains_the_marker(self):
        configured, used, audited = [self.worker() for _ in range(3)]
        self.forward()
        configured.set_password("New-Assigned-Password!2026")
        configured.save(update_fields=["password"])
        Message.objects.create(workspace=self.workspace, created_by=used, to="recipient@example.test", subject="Kept", body="Kept")
        AuditEvent.objects.create(workspace=self.workspace, actor=self.owner, action="assistant.profile_updated", detail=f"User {audited.pk}")
        self.backward()
        for worker in (configured, used, audited):
            worker.refresh_from_db()
            self.assertFalse(worker.is_active)
            self.assertTrue(self.marker(worker).exists())

    def test_reverse_requires_an_exact_marker_from_this_workspace_with_no_actor(self):
        wrong_actor, wrong_workspace, wrong_detail = [self.worker(is_active=False) for _ in range(3)]
        other_owner = get_user_model().objects.create_user("other-retirement-owner")
        other_workspace = Workspace.objects.create(name="Other", executive=other_owner)
        AuditEvent.objects.create(workspace=self.workspace, actor=self.owner, action=migration.ACTION, detail=f"User {wrong_actor.pk}")
        AuditEvent.objects.create(workspace=other_workspace, action=migration.ACTION, detail=f"User {wrong_workspace.pk}")
        AuditEvent.objects.create(workspace=self.workspace, action=migration.ACTION, detail=f"User {wrong_detail.pk} changed")
        self.backward()
        self.assertEqual(get_user_model().objects.filter(pk__in=[wrong_actor.pk, wrong_workspace.pk, wrong_detail.pk], is_active=False).count(), 3)
        self.assertEqual(AuditEvent.objects.filter(action=migration.ACTION).count(), 3)

    def test_a_reactivated_account_is_not_retired_again_or_changed_by_reverse(self):
        worker = self.worker()
        self.forward()
        get_user_model().objects.filter(pk=worker.pk).update(is_active=True)
        self.forward()
        self.backward()
        worker.refresh_from_db()
        self.assertTrue(worker.is_active)
        self.assertEqual(self.marker(worker).count(), 1)
