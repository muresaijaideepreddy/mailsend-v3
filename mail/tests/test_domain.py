import io
from types import SimpleNamespace

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.test import TestCase
from django.utils import timezone

from mail.models import Membership, Message, Workspace
from mail.services import (
    MAX_ATTACHMENT_BYTES, MAX_CSV_BYTES, bcc_from_csv, merge_preview,
    parse_addresses, require_executive, validate_attachments, visible_messages,
)


class DomainTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        User = get_user_model()
        cls.executive = User.objects.create_user("domain-exec", email="exec@example.com")
        cls.assistant = User.objects.create_user("domain-assistant", email="assistant@example.com")
        cls.other_assistant = User.objects.create_user("domain-assistant-2", email="assistant2@example.com")
        cls.outsider = User.objects.create_user("domain-outsider", email="other@example.com")
        cls.workspace = Workspace.objects.create(name="Research", executive=cls.executive)
        Membership.objects.create(workspace=cls.workspace, user=cls.executive, role="executive")
        Membership.objects.create(workspace=cls.workspace, user=cls.assistant, role="assistant")
        Membership.objects.create(workspace=cls.workspace, user=cls.other_assistant, role="assistant")

    def draft(self, **overrides):
        values = dict(workspace=self.workspace, created_by=self.assistant, to="recipient@example.com", subject="Research update", body="Here is the update.", send_date=timezone.localdate())
        values.update(overrides)
        return Message.objects.create(**values)

    def test_executive_sees_workspace_assistant_sees_only_own_messages(self):
        own = self.draft()
        other = self.draft(created_by=self.other_assistant)
        self.assertSetEqual(set(visible_messages(self.executive)), {own, other})
        self.assertListEqual(list(visible_messages(self.assistant)), [own])
        with self.assertRaises(PermissionDenied):
            visible_messages(self.outsider)
        with self.assertRaises(PermissionDenied):
            require_executive(self.assistant)

    def test_invalid_executive_membership_cannot_gain_send_authority(self):
        Membership.objects.filter(user=self.executive).delete()
        Membership.objects.filter(user=self.assistant).update(role="executive")
        with self.assertRaises(PermissionDenied):
            require_executive(self.assistant)
        with self.assertRaises(PermissionDenied):
            visible_messages(self.assistant)

    def test_assistant_can_see_workspace_sent_history_from_other_authors(self):
        sent = self.draft(created_by=self.other_assistant, status="sent")
        self.assertIn(sent, visible_messages(self.assistant))

    def test_disabling_account_revokes_access_even_for_cached_user_instance(self):
        get_user_model().objects.filter(pk=self.executive.pk).update(is_active=False)
        self.assertTrue(self.executive.is_active)
        with self.assertRaises(PermissionDenied):
            require_executive(self.executive)
        with self.assertRaises(PermissionDenied):
            visible_messages(self.executive)

    def test_membership_clean_rejects_role_owner_mismatch(self):
        with self.assertRaises(ValidationError):
            Membership(workspace=self.workspace, user=self.outsider, role="executive").clean()
        with self.assertRaises(ValidationError):
            Membership(workspace=self.workspace, user=self.executive, role="assistant").clean()

    def test_message_clean_rejects_cross_workspace_author(self):
        message = self.draft(created_by=self.outsider)
        with self.assertRaises(ValidationError) as raised:
            message.full_clean()
        self.assertIn("created_by", raised.exception.message_dict)

    def test_recipient_cap_applies_across_all_fields(self):
        message = self.draft(to=", ".join(f"r{i}@example.com" for i in range(225)), bcc=", ".join(f"b{i}@example.com" for i in range(226)))
        with self.assertRaises(ValidationError):
            message.full_clean()

    def test_subject_header_injection_is_rejected(self):
        for subject in ("Hi\r\nBcc: victim@example.com", "\n", "Hi\x00there"):
            with self.subTest(subject=subject):
                message = self.draft(subject=subject)
                with self.assertRaises(ValidationError):
                    message.full_clean()


class AddressValidationTests(TestCase):
    def test_named_and_multiple_addresses_are_preserved_and_deduplicated(self):
        self.assertEqual(parse_addresses('"Doe, Jane" <jane@example.com>, jane@example.com, other@example.com'), '"Doe, Jane" <jane@example.com>, other@example.com')

    def test_invalid_and_injected_addresses_are_rejected(self):
        for address in ("bad", "a@example.com b@example.com", "good@example.com\r\nBcc: bad@example.com", "a@example.com\n", "\na@example.com", "a@example.com\x00", '"unfinished <a@example.com>', "a@", "@example.com"):
            with self.subTest(address=address):
                with self.assertRaises(ValidationError):
                    parse_addresses(address)

    def test_optional_and_required_fields(self):
        self.assertEqual(parse_addresses(""), "")
        with self.assertRaises(ValidationError):
            parse_addresses("", required=True)


class AttachmentValidationTests(TestCase):
    def file(self, size, name="document.pdf"):
        return SimpleNamespace(size=size, name=name)

    def test_boundary_total_and_count_include_existing_files(self):
        validate_attachments([self.file(MAX_ATTACHMENT_BYTES - 2)], existing=[self.file(1), self.file(1)])
        with self.assertRaises(ValidationError):
            validate_attachments([self.file(MAX_ATTACHMENT_BYTES)], existing=[self.file(1)])
        with self.assertRaises(ValidationError):
            validate_attachments([self.file(1)], existing=[self.file(1)] * 3)

    def test_unknown_size_and_header_injection_filename(self):
        for file in (SimpleNamespace(name="file"), self.file(-1), self.file(1, "bad\r\nname.txt")):
            with self.subTest(file=file):
                with self.assertRaises(ValidationError):
                    validate_attachments([file])


class CSVTests(TestCase):
    def preview(self, content, subject="Hello {{first_name}}", body="A message for {{first_name}}.", **kwargs):
        if isinstance(content, str):
            content = content.encode("utf-8")
        return merge_preview(io.BytesIO(content), subject, body, **kwargs)

    def test_bom_unicode_and_quoted_fields(self):
        rows = self.preview('\ufeffemail,first_name\r\na@example.com,"Jane, PhD"\r\nb@example.com,Renée\r\n', cc="copy@example.com")
        self.assertEqual(rows[0], dict(to="a@example.com", subject="Hello Jane, PhD", body="A message for Jane, PhD.", cc="copy@example.com", bcc=""))
        self.assertEqual(rows[1]["subject"], "Hello Renée")

    def test_rejects_missing_duplicate_invalid_and_malformed_headers(self):
        for content in ("", "name\nJane\n", "email,email\na@example.com,b@example.com", "email,first name\na@example.com,Jane", 'email,first_name\na@example.com,"Jane'):
            with self.subTest(content=content):
                with self.assertRaises(ValidationError):
                    self.preview(content)

    def test_bad_row_rejects_whole_preview_instead_of_partial_results(self):
        for content in ("email,first_name\na@example.com,Jane\nbad,Alex", "email,first_name\na@example.com,Jane,Extra", 'email,first_name\n"a@example.com,b@example.com",Jane'):
            with self.subTest(content=content):
                with self.assertRaises(ValidationError):
                    self.preview(content)

    def test_unknown_and_invalid_placeholders_are_rejected(self):
        for subject in ("Hello {{missing}}", "Hello {{name", "Hello {{ first-name }}"):
            with self.subTest(subject=subject):
                with self.assertRaises(ValidationError):
                    self.preview("email,first_name\na@example.com,Jane", subject=subject)

    def test_csv_cannot_inject_mail_headers(self):
        with self.assertRaises(ValidationError):
            self.preview('email,first_name\na@example.com,"Jane\r\nBcc: injected@example.com"')

    def test_row_and_byte_limits(self):
        with self.assertRaises(ValidationError):
            self.preview("email,first_name\n" + "a@example.com,Jane\n" * 201)
        with self.assertRaises(ValidationError):
            self.preview(b"a" * (MAX_CSV_BYTES + 1))

    def test_bcc_import_uses_email_column_and_deduplicates(self):
        content = io.BytesIO(b"first_name,email\nJane,a@example.com\nAlex,b@example.com\nJane,a@example.com\n")
        self.assertEqual(bcc_from_csv(content), "a@example.com, b@example.com")

    def test_untrusted_merge_cells_are_inserted_as_literal_text(self):
        rows = self.preview('email,first_name\na@example.com,{{danger}}')
        self.assertEqual(rows[0]["subject"], "Hello {{danger}}")

    def test_oversized_template_and_placeholder_expansion_are_rejected(self):
        with self.assertRaises(ValidationError):
            self.preview("email,first_name\na@example.com,Jane", body="x" * 100_001)
        with self.assertRaises(ValidationError):
            self.preview("email,first_name\na@example.com," + "x" * 60_000, subject="Hello", body="{{first_name}}{{first_name}}")

    def test_aggregate_preview_budget_prevents_session_memory_explosion(self):
        csv_content = "email,first_name\n" + "a@example.com,Jane\n" * 200
        with self.assertRaises(ValidationError) as raised:
            self.preview(csv_content, body="x" * 22_000)
        self.assertIn("4 MiB", str(raised.exception))
