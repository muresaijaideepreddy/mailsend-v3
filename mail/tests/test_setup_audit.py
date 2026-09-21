"""Regression checks for local demo seeding and real workspace bootstrapping."""

from io import StringIO
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings

from mail.models import Membership, Message, Workspace


@override_settings(DEBUG=True, MAILSEND_DELIVERY_MODE="demo")
class DemoSetupAuditTests(TestCase):
    def seed(self, **options):
        call_command("seed_demo", stdout=StringIO(), **options)

    def test_seed_creates_consistent_accounts_and_is_idempotent(self):
        self.seed()
        executive = get_user_model().objects.get(username="executive")
        assistant = get_user_model().objects.get(username="assistant")
        assistant.set_password("Changed-Local-Password!2026")
        assistant.save()
        original_ids = list(Message.objects.values_list("pk", flat=True))
        self.seed(password="Replacement-Password!2026")
        assistant.refresh_from_db()
        self.assertTrue(assistant.check_password("Changed-Local-Password!2026"))
        self.assertEqual(Workspace.objects.count(), 1)
        self.assertEqual(Membership.objects.count(), 2)
        self.assertEqual(list(Message.objects.values_list("pk", flat=True)), original_ids)
        self.assertEqual(len(original_ids), 5)
        self.assertEqual(executive.membership.workspace, assistant.membership.workspace)
        for message in Message.objects.all():
            message.full_clean()

    def test_seed_refuses_existing_assistant_from_another_workspace(self):
        User = get_user_model()
        owner = User.objects.create_user("existing-owner", "owner@example.test")
        assistant = User.objects.create_user("assistant", "worker@example.test")
        workspace = Workspace.objects.create(executive=owner, name="Existing organization")
        Membership.objects.create(user=owner, workspace=workspace, role="executive")
        Membership.objects.create(user=assistant, workspace=workspace, role="assistant")
        with self.assertRaises(CommandError):
            self.seed()
        self.assertEqual(User.objects.count(), 2)
        self.assertEqual(Workspace.objects.count(), 1)
        self.assertEqual(Message.objects.count(), 0)
        assistant.refresh_from_db()
        self.assertEqual(assistant.membership.workspace_id, workspace.pk)

    def test_seed_does_not_adopt_preexisting_unassigned_accounts(self):
        for username, email in (("executive", "daniel@example.com"), ("assistant", "alex@example.com")):
            with self.subTest(username=username):
                account = get_user_model().objects.create_user(username, email)
                with self.assertRaises(CommandError):
                    self.seed()
                self.assertEqual(get_user_model().objects.count(), 1)
                self.assertFalse(Workspace.objects.exists())
                self.assertFalse(Membership.objects.exists())
                account.delete()

    def test_seed_refuses_case_insensitive_username_collisions(self):
        account = get_user_model().objects.create_user("EXECUTIVE", "existing@example.test")
        with self.assertRaises(CommandError):
            self.seed()
        self.assertEqual(list(get_user_model().objects.values_list("pk", flat=True)), [account.pk])
        self.assertFalse(Workspace.objects.exists())

    def test_seed_refuses_demo_email_owned_by_a_different_account(self):
        account = get_user_model().objects.create_user("existing-user", "DANIEL@example.com")
        with self.assertRaises(CommandError):
            self.seed()
        self.assertEqual(list(get_user_model().objects.values_list("pk", flat=True)), [account.pk])
        self.assertFalse(Workspace.objects.exists())

    def test_seed_refuses_inconsistent_demo_memberships_on_repeat(self):
        self.seed()
        assistant = get_user_model().objects.get(username="assistant")
        assistant.membership.delete()
        original_count = Message.objects.count()
        with self.assertRaises(CommandError):
            self.seed()
        self.assertFalse(Membership.objects.filter(user=assistant).exists())
        self.assertEqual(Message.objects.count(), original_count)

    def test_seed_refuses_production_and_gmail(self):
        for configuration in ({"DEBUG": False}, {"MAILSEND_DELIVERY_MODE": "gmail"}):
            with self.subTest(configuration=configuration), override_settings(**configuration):
                with self.assertRaises(CommandError):
                    self.seed()
        self.assertFalse(get_user_model().objects.exists())

    def test_seed_rejects_empty_or_weak_initial_password_without_creating_accounts(self):
        for password in ("", "123"):
            with self.subTest(password=password):
                with self.assertRaises(CommandError):
                    self.seed(password=password)
                self.assertFalse(get_user_model().objects.exists())
                self.assertFalse(Workspace.objects.exists())


class WorkspaceSetupAuditTests(TestCase):
    def create_workspace(self, **options):
        args = {"username": "real-executive", "email": "person@example.test", "name": "Research Lab"}
        args.update(options)
        call_command("create_workspace", stdout=StringIO(), **args)

    @patch("mail.management.commands.create_workspace.getpass.getpass", side_effect=["Useful-Strong-Pass!2026"] * 2)
    def test_creates_valid_workspace_with_matching_executive(self, password_prompt):
        self.create_workspace(email="PERSON@EXAMPLE.TEST")
        user = get_user_model().objects.get(username="real-executive")
        self.assertEqual(user.email, "person@example.test")
        self.assertTrue(user.check_password("Useful-Strong-Pass!2026"))
        self.assertEqual(user.membership.role, "executive")
        self.assertEqual(user.membership.workspace.executive_id, user.pk)
        user.membership.full_clean()
        self.assertEqual(get_user_model().objects.count(), 1)
        self.assertEqual(Workspace.objects.count(), 1)
        self.assertEqual(list(Membership.objects.values_list('user_id', 'role')), [(user.pk, Membership.Role.EXECUTIVE)])

    @patch("mail.management.commands.create_workspace.getpass.getpass", side_effect=["Useful-Strong-Pass!2026"] * 2)
    def test_new_workspace_does_not_change_existing_workers(self, password_prompt):
        User = get_user_model()
        owner = User.objects.create_user('existing-owner', 'owner@example.test')
        worker = User.objects.create_user('existing-worker', password='Existing-Worker-Password!2026')
        workspace = Workspace.objects.create(name='Existing workspace', executive=owner)
        Membership.objects.create(user=owner, workspace=workspace, role=Membership.Role.EXECUTIVE)
        membership = Membership.objects.create(user=worker, workspace=workspace, role=Membership.Role.ASSISTANT)
        original_password = worker.password

        self.create_workspace()

        new_owner = User.objects.get(username='real-executive')
        self.assertEqual(list(new_owner.owned_workspace.memberships.values_list('user_id', 'role')), [(new_owner.pk, Membership.Role.EXECUTIVE)])
        self.assertEqual(User.objects.count(), 3)
        self.assertEqual(Workspace.objects.count(), 2)
        self.assertEqual(Membership.objects.get(role=Membership.Role.ASSISTANT).pk, membership.pk)
        worker.refresh_from_db()
        self.assertEqual(worker.password, original_password)

    @patch("mail.management.commands.create_workspace.getpass.getpass", side_effect=["Useful-Strong-Pass!2026", "Does-not-match!2026"])
    def test_password_mismatch_leaves_no_partial_workspace(self, password_prompt):
        with self.assertRaises(CommandError):
            self.create_workspace()
        self.assertFalse(get_user_model().objects.exists())
        self.assertFalse(Workspace.objects.exists())

    @patch("mail.management.commands.create_workspace.getpass.getpass", side_effect=["123", "123"])
    def test_weak_password_leaves_no_partial_workspace(self, password_prompt):
        with self.assertRaises(CommandError):
            self.create_workspace()
        self.assertFalse(get_user_model().objects.exists())
        self.assertFalse(Workspace.objects.exists())

    @patch("mail.management.commands.create_workspace.getpass.getpass")
    def test_duplicate_identity_is_rejected_before_password_prompt(self, password_prompt):
        get_user_model().objects.create_user("existing", "PERSON@example.test")
        with self.assertRaises(CommandError):
            self.create_workspace()
        password_prompt.assert_not_called()
        self.assertEqual(get_user_model().objects.count(), 1)
        self.assertFalse(Workspace.objects.exists())
