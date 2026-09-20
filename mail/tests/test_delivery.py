import tempfile
from email import policy
from email.parser import BytesParser
from pathlib import Path
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db.models import F
from django.http import Http404
from django.test import TestCase, override_settings
from django.utils import timezone

from mail.models import Attachment, AuditEvent, Membership, Message, Workspace
from mail.services import DeliveryRejected, build_email, send_message


class DeliveryTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        User = get_user_model()
        cls.executive = User.objects.create_user("delivery-exec", email="exec@example.com")
        cls.assistant = User.objects.create_user("delivery-assistant", email="assistant@example.com")
        cls.other = User.objects.create_user("delivery-other", email="other@example.com")
        cls.workspace = Workspace.objects.create(name="Research", executive=cls.executive, signature="Daniel\nResearch Lab")
        cls.other_workspace = Workspace.objects.create(name="Other", executive=cls.other)
        Membership.objects.create(user=cls.executive, workspace=cls.workspace, role="executive")
        Membership.objects.create(user=cls.assistant, workspace=cls.workspace, role="assistant")
        Membership.objects.create(user=cls.other, workspace=cls.other_workspace, role="executive")

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.settings_override = override_settings(MAILSEND_DELIVERY_MODE="demo", MAILSEND_DEMO_OUTBOX=Path(self.temp.name) / "outbox", MEDIA_ROOT=Path(self.temp.name) / "media")
        self.settings_override.enable()
        self.addCleanup(self.settings_override.disable)
        self.message = Message.objects.create(workspace=self.workspace, created_by=self.assistant, to="recipient@example.com", cc="copy@example.com", bcc="private@example.com", subject="Update", body="Project body.", send_date=timezone.localdate())

    def test_demo_sends_complete_mime_and_does_not_call_gmail(self):
        Attachment.objects.create(message=self.message, file=SimpleUploadedFile("report.txt", b"attachment content", content_type="text/plain"), original_name="report.txt", size=18, content_type="text/plain")
        with patch("mail.google_api.send_gmail") as gmail:
            result = send_message(self.executive, self.message.pk, expected_version=1)
        gmail.assert_not_called()
        self.assertEqual(result.status, "sent")
        self.assertEqual(result.sent_signature, "Daniel\nResearch Lab")
        self.assertIsNotNone(result.sent_at)
        self.assertTrue(result.provider_id.startswith("demo-"))
        files = list((Path(self.temp.name) / "outbox").glob("*.eml"))
        self.assertEqual(len(files), 1)
        outgoing = BytesParser(policy=policy.default).parsebytes(files[0].read_bytes())
        self.assertEqual(outgoing["From"], "exec@example.com")
        self.assertEqual(outgoing["To"], "recipient@example.com")
        self.assertEqual(outgoing["Cc"], "copy@example.com")
        self.assertEqual(outgoing["Bcc"], "private@example.com")
        self.assertIn("Project body.", outgoing.get_body().get_content())
        self.assertIn("Daniel\r\nResearch Lab", outgoing.get_body().get_content())
        attachment = list(outgoing.iter_attachments())[0]
        self.assertEqual(attachment.get_filename(), "report.txt")
        self.assertEqual(attachment.get_content(), "attachment content")
        self.assertSetEqual(set(AuditEvent.objects.filter(message=self.message).values_list("action", flat=True)), {"send_started", "delivery_sent"})

    def test_sent_message_is_idempotent(self):
        result = send_message(self.executive, self.message.pk)
        again = send_message(self.executive, self.message.pk)
        self.assertEqual(result.provider_id, again.provider_id)
        self.assertEqual(len(list((Path(self.temp.name) / "outbox").glob("*.eml"))), 1)

    def test_assistant_and_other_tenant_cannot_send(self):
        with patch("mail.services._deliver_demo") as deliver:
            with self.assertRaises(PermissionDenied):
                send_message(self.assistant, self.message.pk)
            with self.assertRaises(Http404):
                send_message(self.other, self.message.pk)
        deliver.assert_not_called()
        self.message.refresh_from_db()
        self.assertEqual(self.message.status, "draft")

    def test_stale_confirmation_cannot_send_edited_message(self):
        self.message.version = 2
        self.message.save()
        with patch("mail.services._deliver_demo") as deliver:
            with self.assertRaises(ValidationError):
                send_message(self.executive, self.message.pk, expected_version=1)
        deliver.assert_not_called()

    def test_edit_race_before_claim_prevents_send(self):
        original = build_email

        def raced_build(message):
            outgoing = original(message)
            Message.objects.filter(pk=message.pk).update(version=F("version") + 1, subject="Changed by another user")
            return outgoing

        with patch("mail.services.build_email", side_effect=raced_build), patch("mail.services._deliver_demo") as deliver:
            with self.assertRaises(ValidationError):
                send_message(self.executive, self.message.pk)
        deliver.assert_not_called()
        self.message.refresh_from_db()
        self.assertEqual(self.message.status, "draft")

    def test_duplicate_during_provider_call_is_blocked(self):
        def provider(_):
            with self.assertRaises(ValidationError):
                send_message(self.executive, self.message.pk)
            return "demo-one"

        with patch("mail.services._deliver_demo", side_effect=provider) as deliver:
            result = send_message(self.executive, self.message.pk)
        self.assertEqual(result.status, "sent")
        self.assertEqual(deliver.call_count, 1)

    @override_settings(MAILSEND_DELIVERY_MODE="gmail")
    def test_ambiguous_provider_failure_is_never_retried(self):
        with patch("mail.google_api.send_gmail", side_effect=TimeoutError("private-token-must-not-leak")) as deliver:
            result = send_message(self.executive, self.message.pk)
            self.assertEqual(result.status, "uncertain")
            self.assertNotIn("private-token", result.last_error)
            with self.assertRaises(ValidationError):
                send_message(self.executive, self.message.pk)
            self.assertEqual(deliver.call_count, 1)

    @override_settings(MAILSEND_DELIVERY_MODE="gmail")
    def test_definitive_rejection_can_be_explicitly_retried(self):
        with patch("mail.google_api.send_gmail", side_effect=DeliveryRejected("Not accepted")):
            result = send_message(self.executive, self.message.pk)
        self.assertEqual(result.status, "failed")
        with patch("mail.google_api.send_gmail", return_value="gmail-confirmed") as deliver:
            result = send_message(self.executive, self.message.pk, expected_version=result.version)
        self.assertEqual(result.status, "sent")
        self.assertEqual(result.provider_id, "gmail-confirmed")
        self.assertEqual(deliver.call_count, 1)

    @override_settings(MAILSEND_DELIVERY_MODE="gmail")
    def test_invalid_provider_receipt_is_uncertain(self):
        with patch("mail.google_api.send_gmail", return_value=None):
            result = send_message(self.executive, self.message.pk)
        self.assertEqual(result.status, "uncertain")

    def test_existing_sending_state_cannot_be_resent(self):
        Message.objects.filter(pk=self.message.pk).update(status="sending")
        with self.assertRaises(ValidationError):
            send_message(self.executive, self.message.pk)

    def test_missing_attachment_keeps_message_unsent(self):
        attachment = Attachment.objects.create(message=self.message, file=SimpleUploadedFile("missing.txt", b"hi"), original_name="missing.txt", size=2)
        attachment.file.storage.delete(attachment.file.name)
        with self.assertRaises(ValidationError):
            send_message(self.executive, self.message.pk)
        self.message.refresh_from_db()
        self.assertEqual(self.message.status, "draft")

    def test_sent_message_body_contains_no_html_interpretation(self):
        self.message.body = '<script>alert("bad")</script>'
        self.message.save()
        outgoing = build_email(self.message)
        self.assertEqual(outgoing.get_content_type(), "text/plain")
        self.assertIn("<script>", outgoing.get_content())
