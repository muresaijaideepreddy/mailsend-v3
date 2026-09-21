"""Adversarial HTTP tests for authorization, request integrity and tenant isolation."""

import tempfile
from datetime import time, timedelta
from pathlib import Path

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from mail.models import Attachment, GoogleCredential, Membership, Message, Workspace


class WorkspaceTestCase(TestCase):
    """Two isolated organizations, with two assistants in the first organization."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._media = tempfile.TemporaryDirectory(prefix="mailsend-qa-")
        cls._settings = override_settings(MEDIA_ROOT=cls._media.name, MAILSEND_DELIVERY_MODE="demo", MAILSEND_DEMO_OUTBOX=cls._media.name)
        cls._settings.enable()

    @classmethod
    def tearDownClass(cls):
        cls._settings.disable()
        cls._media.cleanup()
        super().tearDownClass()

    @classmethod
    def setUpTestData(cls):
        User = get_user_model()
        cls.executive = User.objects.create_user("qa-executive", email="executive@example.test")
        cls.assistant = User.objects.create_user("qa-assistant", email="assistant@example.test")
        cls.colleague = User.objects.create_user("qa-colleague", email="colleague@example.test")
        cls.outsider = User.objects.create_user("qa-outsider", email="outsider@example.test")
        cls.workspace = Workspace.objects.create(name="QA Organization", executive=cls.executive)
        cls.other_workspace = Workspace.objects.create(name="Other Organization", executive=cls.outsider)
        Membership.objects.create(user=cls.executive, workspace=cls.workspace, role="executive")
        Membership.objects.create(user=cls.assistant, workspace=cls.workspace, role="assistant")
        Membership.objects.create(user=cls.colleague, workspace=cls.workspace, role="assistant")
        Membership.objects.create(user=cls.outsider, workspace=cls.other_workspace, role="executive")
        cls.own = cls.make_message(cls.assistant, cls.workspace, "Own assistant draft")
        cls.peer = cls.make_message(cls.colleague, cls.workspace, "Peer confidential draft")
        cls.foreign = cls.make_message(cls.outsider, cls.other_workspace, "Foreign confidential draft")

    @classmethod
    def make_message(cls, user, workspace, subject, **kwargs):
        fields = dict(workspace=workspace, created_by=user, to="recipient@example.test", subject=subject,
                      body="Confidential message body", send_date=timezone.localdate(), send_time=time(0))
        fields.update(kwargs)
        return Message.objects.create(**fields)

    def draft_data(self, message=None, **overrides):
        message = message or self.own
        values = {field: getattr(message, field) for field in ("to", "cc", "bcc", "subject", "body", "send_date", "version")}
        values["send_time"] = message.send_time.strftime("%H:%M") if message.send_time is not None else ""
        values.update(overrides)
        return values

    def login(self, user=None):
        self.client.force_login(user or self.executive)

    def assert_denied(self, response):
        self.assertIn(response.status_code, (403, 404, 405), response.content[:1000])


class AuthorizationTests(WorkspaceTestCase):
    def test_anonymous_cannot_read_mail(self):
        for name, kwargs in [("dashboard", {}), ("detail", {"pk": self.own.pk}),
                             ("sent", {}), ("signature", {}), ("team", {})]:
            with self.subTest(name=name):
                response = self.client.get(reverse("mail:" + name, kwargs=kwargs))
                self.assertEqual(response.status_code, 302)
                self.assertIn("login", response.url)

    def test_assistant_dashboard_keeps_other_workers_drafts_private(self):
        self.login(self.assistant)
        response = self.client.get(reverse("mail:dashboard"))
        self.assertContains(response, self.own.subject)
        self.assertNotContains(response, self.peer.subject)
        self.assertNotContains(response, self.foreign.subject)

    def test_executive_dashboard_includes_team_but_not_other_tenants(self):
        self.login()
        response = self.client.get(reverse("mail:dashboard"))
        self.assertContains(response, self.own.subject)
        self.assertContains(response, self.peer.subject)
        self.assertNotContains(response, self.foreign.subject)

    def test_executive_created_unsent_messages_allow_worker_edits_but_never_delete_or_send(self):
        shared = []
        for status in ("draft", "failed", "sending", "uncertain"):
            message = self.make_message(self.executive, self.workspace, f"Executive shared {status}", status=status)
            attachment = Attachment.objects.create(
                message=message, file=SimpleUploadedFile("shared.txt", b"executive-shared"),
                original_name="shared.txt", size=16, content_type="text/plain",
            )
            shared.append((message, attachment))
        for worker in (self.assistant, self.colleague):
            self.login(worker)
            for message, attachment in shared:
                with self.subTest(worker=worker.username, status=message.status):
                    response = self.client.get(reverse("mail:dashboard"))
                    self.assertContains(response, message.subject)
                    self.assertEqual(response.context["counts"]["all"], 5)
                    if message.status in ("draft", "failed"):
                        self.assertContains(response, reverse("mail:edit", args=[message.pk]))
                    else:
                        self.assertNotContains(response, reverse("mail:edit", args=[message.pk]))
                    self.assertNotContains(response, reverse("mail:delete", args=[message.pk]))
                    self.assertNotContains(response, reverse("mail:send", args=[message.pk]))
                    detail = self.client.get(reverse("mail:detail", args=[message.pk]))
                    self.assertContains(detail, message.body)
                    self.assertContains(detail, reverse("mail:attachment", args=[attachment.pk]))
                    if message.status in ("draft", "failed"):
                        self.assertContains(detail, reverse("mail:edit", args=[message.pk]))
                    else:
                        self.assertNotContains(detail, reverse("mail:edit", args=[message.pk]))
                    self.assertNotContains(detail, reverse("mail:delete", args=[message.pk]))
                    self.assertNotContains(detail, reverse("mail:send", args=[message.pk]))
                    download = self.client.get(reverse("mail:attachment", args=[attachment.pk]))
                    self.assertEqual(download.status_code, 200)
                    self.assertEqual(b"".join(download.streaming_content), b"executive-shared")
                    download.close()
                    for name in ("delete", "send"):
                        self.assert_denied(self.client.get(reverse("mail:" + name, args=[message.pk])))
                    if message.status in ("draft", "failed"):
                        self.assertEqual(self.client.get(reverse("mail:edit", args=[message.pk])).status_code, 200)
                    else:
                        self.assert_denied(self.client.get(reverse("mail:edit", args=[message.pk])))
                        self.assert_denied(self.client.post(reverse("mail:edit", args=[message.pk]),
                                                           self.draft_data(message, subject="Unauthorized locked edit")))
                    self.assert_denied(self.client.post(reverse("mail:delete", args=[message.pk]), {"version": message.version}))
                    self.assert_denied(self.client.post(reverse("mail:send", args=[message.pk]), {"version": message.version}))
                    original_status = message.status
                    message.refresh_from_db()
                    self.assertEqual(message.created_by_id, self.executive.pk)
                    self.assertEqual(message.status, original_status)
                    self.assertEqual(message.subject, f"Executive shared {original_status}")
                    self.assertTrue(Attachment.objects.filter(pk=attachment.pk).exists())

    def test_worker_filters_search_and_counts_include_shared_executive_drafts(self):
        today = timezone.localdate()
        overdue = self.make_message(self.executive, self.workspace, "Shared overdue", send_date=today - timedelta(days=1))
        current = self.make_message(self.executive, self.workspace, "Shared current", send_date=today)
        future = self.make_message(self.executive, self.workspace, "Shared future", send_date=today + timedelta(days=1))
        self.make_message(self.colleague, self.workspace, "Shared peer hidden", send_date=today + timedelta(days=1))
        self.make_message(self.outsider, self.other_workspace, "Shared foreign hidden", send_date=today)
        self.login(self.assistant)
        dashboard = self.client.get(reverse("mail:dashboard"))
        self.assertEqual(dashboard.context["counts"], {"all": 4, "current": 3, "future": 1, "sent": 0})
        self.assertEqual({item.pk for item in dashboard.context["drafts"]}, {self.own.pk, overdue.pk, current.pk, future.pk})
        for period, expected in (("all", {overdue.pk, current.pk, future.pk}),
                                 ("current", {overdue.pk, current.pk}), ("future", {future.pk})):
            with self.subTest(period=period):
                response = self.client.get(reverse("mail:dashboard"), {"period": period, "q": "Shared"})
                self.assertEqual({item.pk for item in response.context["drafts"]}, expected)
                self.assertEqual(response.context["counts"], dashboard.context["counts"])
                for pk in expected:
                    self.assertContains(response, reverse("mail:detail", args=[pk]))
        hidden = self.client.get(reverse("mail:dashboard"), {"q": "hidden"})
        self.assertEqual(hidden.context["drafts"], [])

    def test_executive_created_message_moves_from_shared_outbox_to_sent(self):
        message = self.make_message(self.executive, self.workspace, "Executive sent message")
        self.login(self.assistant)
        self.assertContains(self.client.get(reverse("mail:dashboard")), message.subject)
        self.assertContains(self.client.get(reverse("mail:detail", args=[message.pk])), message.subject)
        Message.objects.filter(pk=message.pk).update(status="sent", sent_at=timezone.now())
        self.assertContains(self.client.get(reverse("mail:sent")), message.subject)
        self.assertContains(self.client.get(reverse("mail:detail", args=[message.pk])), message.subject)
        self.assertNotContains(self.client.get(reverse("mail:dashboard")), message.subject)
        self.login(self.outsider)
        self.assert_denied(self.client.get(reverse("mail:detail", args=[message.pk])))

    def test_executive_edit_keeps_draft_visible_to_its_worker_author(self):
        self.login()
        response = self.client.post(reverse("mail:edit", args=[self.own.pk]),
                                    self.draft_data(subject="Executive revised my draft"))
        self.assertEqual(response.status_code, 302)
        self.own.refresh_from_db()
        self.assertEqual(self.own.created_by_id, self.assistant.pk)
        self.login(self.assistant)
        self.assertContains(self.client.get(reverse("mail:dashboard")), self.own.subject)

    def test_assistant_cannot_address_peer_or_foreign_messages(self):
        self.login(self.assistant)
        for message in (self.peer, self.foreign):
            for name in ("detail", "edit", "delete"):
                with self.subTest(message=message.pk, name=name):
                    self.assert_denied(self.client.get(reverse("mail:" + name, args=[message.pk])))
            self.assert_denied(self.client.post(reverse("mail:edit", args=[message.pk]),
                                                self.draft_data(message, subject="Hijacked")))
            self.assert_denied(self.client.post(reverse("mail:delete", args=[message.pk]),
                                                {"version": message.version}))
            message.refresh_from_db()
            self.assertNotEqual(message.subject, "Hijacked")

    def test_executive_cannot_address_foreign_messages(self):
        self.login()
        for name in ("detail", "edit", "delete", "send"):
            with self.subTest(name=name):
                self.assert_denied(self.client.get(reverse("mail:" + name, args=[self.foreign.pk])))
                self.assert_denied(self.client.post(reverse("mail:" + name, args=[self.foreign.pk]),
                                                    self.draft_data(self.foreign, subject="Hijacked")))
        self.foreign.refresh_from_db()
        self.assertEqual(self.foreign.status, "draft")

    def test_assistant_cannot_send_even_own_draft(self):
        self.login(self.assistant)
        for method in (self.client.get, self.client.post):
            self.assert_denied(method(reverse("mail:send", args=[self.own.pk]), {"version": self.own.version}))
            self.assert_denied(method(reverse("mail:send_current")))
        self.own.refresh_from_db()
        self.assertEqual(self.own.status, "draft")

    def test_assistant_cannot_enter_executive_review_or_team(self):
        self.login(self.assistant)
        for period in ("all", "current", "future"):
            self.assert_denied(self.client.get(reverse("mail:review", args=[period])))
            self.assert_denied(self.client.post(reverse("mail:review", args=[period]), self.draft_data()))
        self.assert_denied(self.client.get(reverse("mail:team")))
        count = get_user_model().objects.count()
        self.assert_denied(self.client.post(reverse("mail:team"), {
            "username": "unauthorized-user", "email": "bad@example.test", "password": "Long-test-password-29",
        }))
        self.assertEqual(get_user_model().objects.count(), count)

    def test_client_supplied_owner_workspace_or_status_cannot_escalate(self):
        self.login(self.assistant)
        response = self.client.post(reverse("mail:compose"), self.draft_data(
            subject="Ownership test", workspace=self.other_workspace.pk, created_by=self.outsider.pk,
            status="sent", sent_at=timezone.now().isoformat(), role="executive",
        ))
        self.assertEqual(response.status_code, 302)
        created = Message.objects.get(subject="Ownership test")
        self.assertEqual(created.workspace, self.workspace)
        self.assertEqual(created.created_by, self.assistant)
        self.assertEqual(created.status, "draft")
        self.assistant.membership.refresh_from_db()
        self.assertEqual(self.assistant.membership.role, "assistant")

    def test_sent_history_is_shared_within_workspace_only(self):
        Message.objects.filter(pk__in=[self.peer.pk, self.foreign.pk]).update(status="sent", sent_at=timezone.now())
        self.login(self.assistant)
        response = self.client.get(reverse("mail:sent"))
        self.assertContains(response, self.peer.subject)
        self.assertNotContains(response, self.foreign.subject)

    def test_shared_sent_message_details_and_attachments_are_accessible(self):
        Message.objects.filter(pk=self.peer.pk).update(status="sent", sent_at=timezone.now())
        attached = Attachment.objects.create(message=self.peer, file=SimpleUploadedFile("sent.txt", b"sent-content"),
                                             original_name="sent.txt", size=12, content_type="text/plain")
        self.login(self.assistant)
        self.assertEqual(self.client.get(reverse("mail:detail", args=[self.peer.pk])).status_code, 200)
        response = self.client.get(reverse("mail:attachment", args=[attached.pk]))
        self.assertEqual(response.status_code, 200)
        response.close()

    def test_authenticated_account_without_membership_is_denied_cleanly(self):
        account = get_user_model().objects.create_user("unassigned-account")
        self.login(account)
        for name in ("dashboard", "compose", "sent", "signature", "team", "merge"):
            with self.subTest(name=name):
                self.assert_denied(self.client.get(reverse("mail:" + name)))

    def test_disconnected_google_identity_is_not_shown_as_connected(self):
        credential = GoogleCredential.objects.create(user=self.executive, encrypted_data="placeholder", connected=True)
        self.login()
        self.assertTrue(self.client.get(reverse("mail:dashboard")).context["google_connected"])
        credential.connected = False
        credential.save(update_fields=["connected"])
        self.assertFalse(self.client.get(reverse("mail:dashboard")).context["google_connected"])

    @override_settings(GOOGLE_CLIENT_ID="configured-client", GOOGLE_CLIENT_SECRET="configured-secret", MAILSEND_TOKEN_ENCRYPTION_KEY="")
    def test_google_sign_in_hidden_until_encryption_key_is_configured(self):
        self.login()
        self.assertFalse(self.client.get(reverse("mail:dashboard")).context["google_enabled"])

    def test_shared_signature_update_does_not_modify_other_workspace(self):
        self.login(self.assistant)
        response = self.client.post(reverse("mail:signature"), {
            "signature": "QA organization only", "workspace": self.other_workspace.pk,
            "executive": self.outsider.pk,
        })
        self.assertEqual(response.status_code, 302)
        self.workspace.refresh_from_db()
        self.other_workspace.refresh_from_db()
        self.assertEqual(self.workspace.signature, "QA organization only")
        self.assertEqual(self.other_workspace.signature, "")

    def test_attachments_follow_message_visibility(self):
        own_file = Attachment.objects.create(message=self.own, file=SimpleUploadedFile("own.txt", b"own-secret"),
                                             original_name="own.txt", size=10, content_type="text/plain")
        peer_file = Attachment.objects.create(message=self.peer, file=SimpleUploadedFile("peer.txt", b"peer-secret"),
                                              original_name="peer.txt", size=11, content_type="text/plain")
        foreign_file = Attachment.objects.create(message=self.foreign, file=SimpleUploadedFile("foreign.txt", b"foreign-secret"),
                                                 original_name="foreign.txt", size=14, content_type="text/plain")
        self.login(self.assistant)
        own_response = self.client.get(reverse("mail:attachment", args=[own_file.pk]))
        self.assertEqual(own_response.status_code, 200)
        self.assertIn("attachment", own_response.headers.get("Content-Disposition", ""))
        own_response.close()
        self.assert_denied(self.client.get(reverse("mail:attachment", args=[peer_file.pk])))
        self.assert_denied(self.client.get(reverse("mail:attachment", args=[foreign_file.pk])))
        self.login()
        peer_response = self.client.get(reverse("mail:attachment", args=[peer_file.pk]))
        self.assertEqual(peer_response.status_code, 200)
        peer_response.close()
        self.assert_denied(self.client.get(reverse("mail:attachment", args=[foreign_file.pk])))

    def test_uploaded_file_has_no_public_media_route(self):
        attached = Attachment.objects.create(message=self.own, file=SimpleUploadedFile("private.txt", b"private"),
                                             original_name="private.txt", size=7, content_type="text/plain")
        self.client.logout()
        response = self.client.get(attached.file.url)
        self.assertNotEqual(response.status_code, 200)

    def test_assistant_cannot_remove_another_drafts_attachment(self):
        attached = Attachment.objects.create(message=self.peer, file=SimpleUploadedFile("private.txt", b"private"),
                                             original_name="private.txt", size=7, content_type="text/plain")
        self.login(self.assistant)
        self.client.post(reverse("mail:edit", args=[self.own.pk]),
                         self.draft_data(remove_attachments=[attached.pk]))
        self.assertTrue(Attachment.objects.filter(pk=attached.pk).exists())
        self.assertTrue(Path(attached.file.path).exists())


class RequestIntegrityTests(WorkspaceTestCase):
    def test_csrf_required_for_each_mutating_endpoint(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.executive)
        targets = [("compose", []), ("edit", [self.own.pk]), ("delete", [self.own.pk]),
                   ("send", [self.own.pk]), ("send_current", []), ("review", ["all"]),
                   ("signature", []), ("team", []), ("merge", []), ("google_disconnect", [])]
        for name, args in targets:
            with self.subTest(name=name):
                response = client.post(reverse("mail:" + name, args=args), self.draft_data())
                self.assertEqual(response.status_code, 403)
        self.own.refresh_from_db()
        self.assertEqual(self.own.status, "draft")

    def test_get_confirmations_do_not_delete_or_send(self):
        self.login()
        count = Message.objects.count()
        for name, args in [("delete", [self.own.pk]), ("send", [self.own.pk]), ("send_current", [])]:
            with self.subTest(name=name):
                self.assertEqual(self.client.get(reverse("mail:" + name, args=args)).status_code, 200)
                self.assertEqual(Message.objects.count(), count)
                self.own.refresh_from_db()
                self.assertEqual(self.own.status, "draft")
        self.assertEqual(self.client.get(reverse("mail:google_disconnect")).status_code, 405)

    def test_message_body_and_subject_escape_active_html(self):
        self.own.body = '<script>alert("body")</script>'
        self.own.subject = '<script>alert("subject")</script>'
        self.own.save()
        self.login()
        response = self.client.get(reverse("mail:detail", args=[self.own.pk]))
        self.assertNotContains(response, self.own.body)
        self.assertNotContains(response, self.own.subject)
        self.assertContains(response, "&lt;script&gt;")

    def test_sent_messages_cannot_be_edited_or_deleted(self):
        Message.objects.filter(pk=self.own.pk).update(status="sent", sent_at=timezone.now())
        self.login()
        self.client.post(reverse("mail:edit", args=[self.own.pk]), self.draft_data(subject="Rewritten history"))
        self.client.post(reverse("mail:delete", args=[self.own.pk]), {"version": self.own.version})
        self.own.refresh_from_db()
        self.assertEqual(self.own.subject, "Own assistant draft")
        self.assertEqual(self.own.status, "sent")

    def test_stale_edit_does_not_overwrite_newer_draft(self):
        self.login()
        first = self.draft_data(subject="Saved first")
        stale = self.draft_data(subject="Stale overwrite")
        self.assertEqual(self.client.post(reverse("mail:edit", args=[self.own.pk]), first).status_code, 302)
        response = self.client.post(reverse("mail:edit", args=[self.own.pk]), stale)
        self.assertIn(response.status_code, (200, 400, 409))
        self.own.refresh_from_db()
        self.assertEqual(self.own.subject, "Saved first")
        self.assertEqual(self.own.version, 2)

    def test_stale_delete_does_not_delete_newer_draft(self):
        self.login()
        old_version = self.own.version
        Message.objects.filter(pk=self.own.pk).update(subject="Changed after confirmation", version=old_version + 1)
        self.client.post(reverse("mail:delete", args=[self.own.pk]), {"version": old_version})
        self.assertTrue(Message.objects.filter(pk=self.own.pk).exists())
