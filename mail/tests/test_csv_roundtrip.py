"""CSV source diagnostics and preview-to-draft workflows with synthetic data."""

import io
from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase
from django.urls import reverse
from django.utils import timezone

from mail.models import Message
from mail.services import bcc_from_csv, merge_preview
from mail.tests.test_security import WorkspaceTestCase


class CSVSourceTests(SimpleTestCase):
    def preview(self, content, subject="CSV audit", body="{{note}}"):
        return merge_preview(io.BytesIO(content.encode("utf-8")), subject, body)

    def test_recipient_errors_retain_source_line_after_blank_and_multiline_rows(self):
        content = 'email,note\n\none@example.test,"first line\nsecond line"\n\ninvalid,broken\n'
        for operation in (self.preview, lambda value: bcc_from_csv(io.BytesIO(value.encode("utf-8")))):
            with self.subTest(operation=operation):
                with self.assertRaisesMessage(ValidationError, "CSV row 6:"):
                    operation(content)

    def test_multiline_record_errors_report_the_record_start(self):
        for content in ('email,note\ninvalid,"first\nsecond"\n', 'email,note\n,"first\nsecond"\n'):
            for operation in (self.preview, lambda value: bcc_from_csv(io.BytesIO(value.encode("utf-8")))):
                with self.subTest(content=content, operation=operation):
                    with self.assertRaisesMessage(ValidationError, "CSV row 2:"):
                        operation(content)

    def test_multiline_column_count_error_uses_the_same_source_line_convention(self):
        content = 'email,note\n\none@example.test,"first\nsecond",extra\n'
        with self.assertRaisesMessage(ValidationError, "CSV row 3 has a different number of columns"):
            self.preview(content)

    def test_utf8_bom_quoted_newlines_and_formula_like_cells_remain_literal(self):
        content = '\ufeffemail,note\r\n\r\none@example.test,"Renée, 你好\r\n=1+1 <script>alert(1)</script> {{unused}}"\r\n'
        self.assertEqual(self.preview(content), [{
            "to": "one@example.test", "subject": "CSV audit", "cc": "", "bcc": "",
            "body": "Renée, 你好\r\n=1+1 <script>alert(1)</script> {{unused}}",
        }])

    def test_csv_rejects_bad_encoding_nulls_and_duplicate_trimmed_headers(self):
        for content in (b"email,note\na@example.test,\xff", b"email,note\na@example.test,\x00", b"email, email \na@example.test,b@example.test"):
            for operation in (lambda value: merge_preview(io.BytesIO(value), "CSV audit", "Body"),
                              lambda value: bcc_from_csv(io.BytesIO(value))):
                with self.subTest(content=content, operation=operation):
                    with self.assertRaises(ValidationError):
                        operation(content)

    def test_exact_recipient_limits_accept_and_next_row_rejects(self):
        merge_csv = "email,note\n" + "".join(f"person{index}@example.test,Hello\n" for index in range(200))
        self.assertEqual(len(self.preview(merge_csv)), 200)
        with self.assertRaisesMessage(ValidationError, "at most 200"):
            self.preview(merge_csv + "overflow@example.test,Hello\n")
        bcc_csv = "email\n" + "".join(f"person{index}@example.test\n" for index in range(450))
        self.assertEqual(len(bcc_from_csv(io.BytesIO(bcc_csv.encode())).split(", ")), 450)
        with self.assertRaisesMessage(ValidationError, "at most 450"):
            bcc_from_csv(io.BytesIO((bcc_csv + "overflow@example.test\n").encode()))


class CSVRoundtripTests(WorkspaceTestCase):
    def preview(self, content, **overrides):
        fields = {
            "action": "preview", "csv_file": SimpleUploadedFile("recipients.csv", content.encode("utf-8"), content_type="text/csv"),
            "subject": "Hello {{name}}", "body": "{{note}}", "cc": "", "bcc": "",
            "send_date": timezone.localdate(),
            "send_time": "00:00",
        }
        fields.update(overrides)
        return self.client.post(reverse("mail:merge"), fields)

    def test_multiline_csv_preview_is_escaped_and_roundtrips_without_sending(self):
        self.login(self.assistant)
        before = Message.objects.count()
        note = "First line\n=1+1 <script>alert(1)</script> {{unexpanded}}"
        with patch("mail.views.send_message") as deliver:
            preview = self.preview('email,name,note\none@example.test,"Renée, PhD","' + note + '"\n')
            self.assertEqual(preview.status_code, 200)
            self.assertContains(preview, "&lt;script&gt;alert(1)&lt;/script&gt;")
            self.assertNotContains(preview, "<script>alert(1)</script>")
            self.assertEqual(Message.objects.count(), before)
            response = self.client.post(reverse("mail:merge"), {"action": "commit", "merge_token": preview.context["merge_token"]})
        self.assertEqual(response.status_code, 302)
        deliver.assert_not_called()
        message = Message.objects.get(subject="Hello Renée, PhD")
        self.assertEqual(message.body, note)
        self.assertEqual(message.to, "one@example.test")
        self.assertEqual(message.status, "draft")

    def test_new_preview_invalidates_old_confirmation_without_losing_new_preview(self):
        self.login(self.assistant)
        before = Message.objects.count()
        old = self.preview("email,name,note\nold@example.test,Old,Old body\n").context["merge_token"]
        current = self.preview("email,name,note\nnew@example.test,New,New body\n").context["merge_token"]
        response = self.client.post(reverse("mail:merge"), {"action": "commit", "merge_token": old})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(Message.objects.count(), before)
        self.assertEqual(self.client.session["merge_preview"]["token"], current)
        response = self.client.post(reverse("mail:merge"), {"action": "commit", "merge_token": current})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(Message.objects.count(), before + 1)
        self.assertTrue(Message.objects.filter(subject="Hello New", to="new@example.test").exists())
        self.assertFalse(Message.objects.filter(subject="Hello Old").exists())

    def test_expired_confirmation_creates_no_drafts(self):
        self.login(self.assistant)
        before = Message.objects.count()
        token = self.preview("email,name,note\na@example.test,Ada,Body\n").context["merge_token"]
        session = self.client.session
        saved = session["merge_preview"]
        saved["at"] = timezone.now().timestamp() - 1801
        session["merge_preview"] = saved
        session.save()
        response = self.client.post(reverse("mail:merge"), {"action": "commit", "merge_token": token})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(Message.objects.count(), before)

    def test_bcc_import_rejects_empty_email_without_saving_or_modifying_draft(self):
        self.login(self.assistant)
        before = Message.objects.count()
        response = self.client.post(reverse("mail:edit", args=[self.own.pk]), self.draft_data(
            subject="Must not save", bcc="existing@example.test",
            bcc_csv=SimpleUploadedFile("bcc.csv", b"email,note\none@example.test,Valid\n\n,Missing address\n", content_type="text/csv"),
        ))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "CSV row 4:")
        self.assertIn("bcc_csv", response.context["form"].errors)
        self.own.refresh_from_db()
        self.assertEqual(self.own.subject, "Own assistant draft")
        self.assertEqual(self.own.bcc, "")
        self.assertEqual(Message.objects.count(), before)
