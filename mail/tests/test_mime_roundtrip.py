"""Exercise saved attachment bytes through MIME serialization and delivery."""

import base64
import tempfile
from email import policy
from email.parser import BytesParser
from pathlib import Path
from unittest.mock import Mock, patch

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings

from mail.google_api import SEND_URL, send_gmail
from mail.models import Attachment, Membership, Message, Workspace
from mail.services import build_email, send_message


class MIMERoundTripTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.executive = get_user_model().objects.create_user("mime-executive", email="executive@example.test")
        cls.workspace = Workspace.objects.create(
            name="MIME audit", executive=cls.executive, signature="Renée\n研究室 — MailSend"
        )
        Membership.objects.create(user=cls.executive, workspace=cls.workspace, role="executive")

    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.outbox = Path(directory.name) / "outbox"
        settings = override_settings(
            MEDIA_ROOT=Path(directory.name) / "media",
            MAILSEND_DEMO_OUTBOX=self.outbox,
            MAILSEND_DELIVERY_MODE="demo",
        )
        settings.enable()
        self.addCleanup(settings.disable)
        self.message = Message.objects.create(
            workspace=self.workspace, created_by=self.executive,
            to='"Renée, Research" <recipient@example.test>', cc="copy@example.test",
            bcc="private@example.test", subject="研究 update — café",
            body="Hello Renée!\nLine two: 研究 <literal text>.",
        )

    def attach(self, name, data, content_type="application/octet-stream", **values):
        return Attachment.objects.create(
            message=self.message, file=SimpleUploadedFile(name, data),
            original_name=name, content_type=content_type, size=values.get("size", len(data)),
        )

    def parsed(self, outgoing):
        result = BytesParser(policy=policy.default).parsebytes(outgoing.as_bytes())
        self.assertFalse([defect for part in result.walk() for defect in part.defects])
        return result

    def test_demo_roundtrip_preserves_unicode_headers_signature_and_three_attachment_bytes(self):
        files = [
            ("résumé.txt", "Résumé\r\n研究\n".encode(), "text/plain"),
            ("binary.bin", bytes(range(256)) * 4, "application/octet-stream"),
            ("report.pdf", b"%PDF-1.4\r\n\x00\xff\r\n%%EOF", "application/pdf"),
        ]
        for name, data, content_type in files:
            self.attach(name, data, content_type)
        with patch("mail.google_api.requests.post") as network:
            result = send_message(self.executive, self.message.pk, expected_version=1)
        network.assert_not_called()
        self.assertEqual(result.status, "sent")
        saved = list(self.outbox.glob("*.eml"))
        self.assertEqual(len(saved), 1)
        parsed = BytesParser(policy=policy.default).parsebytes(saved[0].read_bytes())
        self.assertEqual(str(parsed["Subject"]), self.message.subject)
        self.assertEqual(parsed["To"].addresses[0].display_name, "Renée, Research")
        self.assertEqual(parsed["Bcc"].addresses[0].addr_spec, "private@example.test")
        expected_body = self.message.body + "\n\n-- \n" + self.workspace.signature + "\n"
        self.assertEqual(parsed.get_body().get_content().replace("\r\n", "\n"), expected_body)
        self.assertEqual(
            [(part.get_filename(), part.get_payload(decode=True), part.get_content_type())
             for part in parsed.iter_attachments()], files,
        )
        self.assertFalse([defect for part in parsed.walk() for defect in part.defects])

    def test_gmail_payload_keeps_bcc_and_attachment_bytes_in_one_request(self):
        content = b"email,name\r\nrecipient@example.test,Sample\r\n"
        self.attach("recipients.csv", content, "text/csv")
        response = Mock(status_code=200)
        response.json.return_value = {"id": "synthetic-gmail-receipt"}
        with patch("mail.google_api._access_token", return_value="synthetic-test-token"), \
                patch("mail.google_api.requests.post", return_value=response) as post:
            receipt = send_gmail(self.executive, build_email(self.message))
        self.assertEqual(receipt, "synthetic-gmail-receipt")
        post.assert_called_once()
        self.assertEqual(post.call_args.args[0], SEND_URL)
        raw = base64.urlsafe_b64decode(post.call_args.kwargs["json"]["raw"])
        parsed = BytesParser(policy=policy.default).parsebytes(raw)
        self.assertEqual(parsed["Bcc"].addresses[0].addr_spec, "private@example.test")
        self.assertEqual(list(parsed.iter_attachments())[0].get_payload(decode=True), content)

    def test_structured_or_invalid_upload_types_are_safe_opaque_attachments(self):
        content = b"From: original@example.test\r\nSubject: saved message\r\n\r\nOriginal body\r\n"
        for content_type in ("message/rfc822", "MESSAGE/RFC822", "multipart/mixed", "text/plain\r\nBcc: injected@example.test"):
            with self.subTest(content_type=content_type):
                item = self.attach("saved.eml", content, content_type)
                try:
                    parsed = self.parsed(build_email(self.message))
                    attachment = list(parsed.iter_attachments())[0]
                    self.assertEqual(attachment.get_content_type(), "application/octet-stream")
                    self.assertEqual(attachment.get_payload(decode=True), content)
                    self.assertEqual(attachment.get_filename(), "saved.eml")
                finally:
                    item.delete()

    def test_actual_file_bytes_cannot_bypass_aggregate_limit_with_stale_size_metadata(self):
        self.attach("first.bin", b"12345", size=1)
        self.attach("second.bin", b"6789", size=1)
        with patch("mail.services.MAX_ATTACHMENT_BYTES", 8), patch("mail.services._deliver_demo") as deliver:
            with self.assertRaises(ValidationError):
                send_message(self.executive, self.message.pk, expected_version=1)
        deliver.assert_not_called()
        self.message.refresh_from_db()
        self.assertEqual(self.message.status, "draft")
        self.assertEqual(self.message.version, 1)

    def test_actual_file_bytes_at_aggregate_boundary_are_preserved(self):
        self.attach("first.bin", b"1234", size=1)
        self.attach("second.bin", b"5678", size=1)
        with patch("mail.services.MAX_ATTACHMENT_BYTES", 8):
            parsed = self.parsed(build_email(self.message))
        self.assertEqual([part.get_payload(decode=True) for part in parsed.iter_attachments()], [b"1234", b"5678"])
