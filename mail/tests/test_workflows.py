"""Product workflows tested through real Django HTTP handlers, without real mail."""

from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.exceptions import ValidationError
from django.urls import reverse
from django.utils import timezone

from mail.models import Attachment, Message
from mail.tests.test_security import WorkspaceTestCase


class DraftWorkflowTests(WorkspaceTestCase):
    def test_assistant_can_compose_edit_and_delete_own_draft(self):
        self.login(self.assistant)
        response = self.client.post(reverse("mail:compose"), self.draft_data(subject="Prepared for executive"))
        self.assertEqual(response.status_code, 302)
        draft = Message.objects.get(subject="Prepared for executive")
        self.assertEqual(draft.status, "draft")
        response = self.client.post(reverse("mail:edit", args=[draft.pk]), self.draft_data(draft, subject="Revised draft"))
        self.assertEqual(response.status_code, 302)
        draft.refresh_from_db()
        self.assertEqual(draft.subject, "Revised draft")
        self.assertEqual(draft.version, 2)
        response = self.client.post(reverse("mail:delete", args=[draft.pk]), {"version": draft.version})
        self.assertEqual(response.status_code, 302)
        self.assertFalse(Message.objects.filter(pk=draft.pk).exists())

    def test_dashboard_current_includes_overdue_and_today_and_future_is_strict(self):
        today = timezone.localdate()
        overdue = self.make_message(self.assistant, self.workspace, "Overdue unique", send_date=today - timedelta(days=1))
        future = self.make_message(self.assistant, self.workspace, "Future unique", send_date=today + timedelta(days=1))
        self.login()
        current_response = self.client.get(reverse("mail:dashboard"), {"period": "current"})
        self.assertContains(current_response, overdue.subject)
        self.assertContains(current_response, self.own.subject)
        self.assertNotContains(current_response, future.subject)
        future_response = self.client.get(reverse("mail:dashboard"), {"period": "future"})
        self.assertContains(future_response, future.subject)
        self.assertNotContains(future_response, overdue.subject)
        self.assertNotContains(future_response, self.own.subject)

    def test_search_never_expands_tenant_scope(self):
        self.login()
        response = self.client.get(reverse("mail:dashboard"), {"q": "confidential"})
        self.assertContains(response, self.peer.subject)
        self.assertNotContains(response, self.foreign.subject)

    def test_review_saves_and_moves_to_next_without_sending(self):
        self.login()
        response = self.client.get(reverse("mail:review", args=["all"]))
        self.assertEqual(response.status_code, 200)
        first = response.context["message_obj"]
        with patch("mail.views.send_message") as deliver:
            response = self.client.post(reverse("mail:review", args=["all"]),
                                        self.draft_data(first, subject="Executive revision", review_token=response.context["review_token"]))
        self.assertEqual(response.status_code, 302)
        deliver.assert_not_called()
        first.refresh_from_db()
        self.assertEqual(first.subject, "Executive revision")
        self.assertEqual(first.status, "draft")
        next_response = self.client.get(response.url)
        self.assertEqual(next_response.status_code, 200)
        if next_response.context.get("message_obj"):
            self.assertNotEqual(next_response.context["message_obj"].pk, first.pk)

    def test_review_snapshot_does_not_include_later_drafts(self):
        self.login()
        response = self.client.get(reverse("mail:review", args=["current"]))
        count = response.context["review_total"]
        first = response.context["message_obj"]
        self.make_message(self.assistant, self.workspace, "Arrived after review began")
        response = self.client.post(reverse("mail:review", args=["current"]), self.draft_data(first, review_token=response.context["review_token"]))
        next_response = self.client.get(response.url)
        self.assertEqual(next_response.context["review_total"], count)

    def test_review_rejects_stale_version(self):
        self.login()
        response = self.client.get(reverse("mail:review", args=["all"]))
        first = response.context["message_obj"]
        Message.objects.filter(pk=first.pk).update(subject="Assistant changed during review", version=first.version + 1)
        self.client.post(reverse("mail:review", args=["all"]), self.draft_data(first, subject="Stale review", review_token=response.context["review_token"]))
        first.refresh_from_db()
        self.assertEqual(first.subject, "Assistant changed during review")

    def test_review_future_is_empty_when_no_future_drafts(self):
        self.login()
        response = self.client.get(reverse("mail:review", args=["future"]), follow=True)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.context.get("message_obj"))

    def test_invalid_recipient_and_header_injection_are_rejected(self):
        self.login(self.assistant)
        initial_count = Message.objects.count()
        for recipient in ("not-an-address", "recipient@example.test\r\nBcc: victim@example.test"):
            with self.subTest(recipient=recipient):
                response = self.client.post(reverse("mail:compose"), self.draft_data(to=recipient))
                self.assertEqual(response.status_code, 200)
                self.assertTrue(response.context["form"].errors)
                self.assertEqual(Message.objects.count(), initial_count)

    def test_executive_can_create_assistant_in_own_workspace_only(self):
        self.login()
        response = self.client.post(reverse("mail:team"), {
            "username": "new-qa-worker", "email": "new-worker@example.test", "first_name": "New Worker",
            "password": "R2!thorough-test-password", "role": "executive", "workspace": self.other_workspace.pk,
        })
        self.assertEqual(response.status_code, 302)
        from django.contrib.auth import get_user_model
        worker = get_user_model().objects.get(username="new-qa-worker")
        self.assertEqual(worker.membership.workspace_id, self.workspace.pk)
        self.assertEqual(worker.membership.role, "assistant")
        self.assertTrue(worker.check_password("R2!thorough-test-password"))


class SendConfirmationTests(WorkspaceTestCase):
    def test_send_confirmation_shows_body_signature_and_attachment_names(self):
        self.workspace.signature = "Executive approved signature"
        self.workspace.save(update_fields=["signature"])
        Attachment.objects.create(message=self.own, file=SimpleUploadedFile("review-me.txt", b"private"),
                                  original_name="review-me.txt", size=7, content_type="text/plain")
        self.login()
        response = self.client.get(reverse("mail:send", args=[self.own.pk]))
        self.assertContains(response, self.own.body)
        self.assertContains(response, self.workspace.signature)
        self.assertContains(response, "review-me.txt")

    def test_explicit_individual_confirmation_can_send_future_draft_locally(self):
        future = self.make_message(self.assistant, self.workspace, "Future approved now", send_date=timezone.localdate() + timedelta(days=30))
        self.login()
        response = self.client.get(reverse("mail:send", args=[future.pk]))
        response = self.client.post(reverse("mail:send", args=[future.pk]), {
            "version": response.context["version"], "batch_token": response.context["batch_token"],
        })
        self.assertEqual(response.status_code, 302)
        future.refresh_from_db()
        self.assertEqual(future.status, "sent")
        self.assertTrue(future.provider_id.startswith("demo-"))
        self.assertIsNotNone(future.sent_at)

    def test_individual_send_rejects_stale_confirmation(self):
        self.login()
        response = self.client.get(reverse("mail:send", args=[self.own.pk]))
        version = response.context["version"]
        token = response.context["batch_token"]
        Message.objects.filter(pk=self.own.pk).update(subject="Changed since approval", version=self.own.version + 1)
        with patch("mail.services._deliver_demo") as deliver:
            self.client.post(reverse("mail:send", args=[self.own.pk]), {"version": version, "batch_token": token})
        deliver.assert_not_called()

    def test_individual_send_requires_server_confirmation(self):
        self.login()
        with patch("mail.views.send_message") as deliver:
            self.client.post(reverse("mail:send", args=[self.own.pk]))
        deliver.assert_not_called()

    def test_signature_change_invalidates_individual_send_confirmation(self):
        self.login()
        response = self.client.get(reverse("mail:send", args=[self.own.pk]))
        version = response.context["version"]
        token = response.context["batch_token"]
        from django.test import Client
        assistant_client = Client()
        assistant_client.force_login(self.assistant)
        self.assertEqual(assistant_client.post(reverse("mail:signature"), {"signature": "New signature after approval"}).status_code, 302)
        with patch("mail.views.send_message") as deliver:
            self.client.post(reverse("mail:send", args=[self.own.pk]), {"version": version, "batch_token": token})
        deliver.assert_not_called()

    def test_signature_change_invalidates_batch_confirmation(self):
        self.login()
        response = self.client.get(reverse("mail:send_current"))
        token = response.context["batch_token"]
        from django.test import Client
        assistant_client = Client()
        assistant_client.force_login(self.assistant)
        assistant_client.post(reverse("mail:signature"), {"signature": "Changed signature"})
        with patch("mail.views.send_message") as deliver:
            self.client.post(reverse("mail:send_current"), {"batch_token": token})
        deliver.assert_not_called()

    def test_current_batch_requires_valid_server_snapshot(self):
        self.login()
        with patch("mail.views.send_message") as deliver:
            self.client.post(reverse("mail:send_current"), {"batch_token": "forged"})
        deliver.assert_not_called()

    def test_current_batch_excludes_future_new_and_foreign_drafts(self):
        self.login()
        future = self.make_message(self.assistant, self.workspace, "Future explicit send", send_date=timezone.localdate() + timedelta(days=3))
        response = self.client.get(reverse("mail:send_current"))
        token = response.context["batch_token"]
        new = self.make_message(self.assistant, self.workspace, "New after approval")
        with patch("mail.views.send_message", return_value=SimpleNamespace(status="sent", last_error="")) as deliver:
            self.client.post(reverse("mail:send_current"), {"batch_token": token})
        sent_ids = {call.args[1] for call in deliver.call_args_list}
        self.assertEqual(sent_ids, {self.own.pk, self.peer.pk})
        self.assertTrue(sent_ids.isdisjoint({future.pk, new.pk, self.foreign.pk}))

    def test_current_batch_does_not_send_a_changed_draft(self):
        self.login()
        response = self.client.get(reverse("mail:send_current"))
        token = response.context["batch_token"]
        Message.objects.filter(pk=self.own.pk).update(subject="Changed after batch approval", version=self.own.version + 1)
        with patch("mail.views.send_message", return_value=SimpleNamespace(status="sent", last_error="")) as deliver:
            self.client.post(reverse("mail:send_current"), {"batch_token": token})
        sent_ids = {call.args[1] for call in deliver.call_args_list}
        self.assertNotIn(self.own.pk, sent_ids)

    def test_batch_confirmation_is_one_use(self):
        self.login()
        response = self.client.get(reverse("mail:send_current"))
        token = response.context["batch_token"]
        with patch("mail.views.send_message", return_value=SimpleNamespace(status="sent", last_error="")) as deliver:
            self.client.post(reverse("mail:send_current"), {"batch_token": token})
            initial_calls = deliver.call_count
            self.client.post(reverse("mail:send_current"), {"batch_token": token})
        self.assertEqual(deliver.call_count, initial_calls)

    def test_partial_batch_failure_reports_already_delivered_count(self):
        self.login()
        response = self.client.get(reverse("mail:send_current"))
        token = response.context["batch_token"]
        with patch("mail.views.send_message", side_effect=[
            SimpleNamespace(status="sent", last_error=""), ValidationError("Changed during delivery"),
        ]):
            response = self.client.post(reverse("mail:send_current"), {"batch_token": token}, follow=True)
        self.assertContains(response, "1 message(s) were delivered before the batch stopped")
        self.assertNotContains(response, "No messages were sent")

    def test_batch_reports_partial_delivery_when_later_draft_is_deleted(self):
        self.login()
        response = self.client.get(reverse("mail:send_current"))
        token = response.context["batch_token"]
        from mail.services import send_message as real_send

        def deliver_then_delete(user, message_id, **kwargs):
            if message_id == self.own.pk:
                self.peer.delete()
                return SimpleNamespace(status="sent", last_error="")
            return real_send(user, message_id, **kwargs)

        with patch("mail.views.send_message", side_effect=deliver_then_delete):
            response = self.client.post(reverse("mail:send_current"), {"batch_token": token}, follow=True)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "1 message(s) were delivered before the batch stopped")
        self.assertContains(response, "remaining draft was removed")


class AttachmentWorkflowTests(WorkspaceTestCase):
    def test_deleting_draft_removes_private_attachment_file_after_commit(self):
        attached = Attachment.objects.create(message=self.own, file=SimpleUploadedFile("delete-me.txt", b"private"),
                                             original_name="delete-me.txt", size=7, content_type="text/plain")
        saved_path = Path(attached.file.path)
        self.assertTrue(saved_path.exists())
        self.login(self.assistant)
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(reverse("mail:delete", args=[self.own.pk]), {"version": self.own.version})
        self.assertEqual(response.status_code, 302)
        self.assertFalse(saved_path.exists())

    def test_attachment_database_insert_failure_cleans_up_written_file(self):
        self.login(self.assistant)
        before_files = set(Path(self._media.name).rglob("*"))
        with patch("mail.models.Attachment.save", side_effect=ValidationError("Upload could not be recorded")):
            response = self.client.post(reverse("mail:edit", args=[self.own.pk]), self.draft_data(
                subject="Do not partially save", attachment_1=SimpleUploadedFile("rollback.txt", b"private")))
        self.assertEqual(response.status_code, 200)
        self.own.refresh_from_db()
        self.assertEqual(self.own.subject, "Own assistant draft")
        self.assertEqual(self.own.attachments.count(), 0)
        new_files = {path for path in Path(self._media.name).rglob("*") if path.is_file()} - before_files
        self.assertFalse(new_files)

    def test_three_attachments_survive_save_and_download(self):
        self.login(self.assistant)
        data = self.draft_data(subject="Three attachments")
        for index in range(1, 4):
            data[f"attachment_{index}"] = SimpleUploadedFile(f"file{index}.txt", f"file {index}".encode(), content_type="text/plain")
        response = self.client.post(reverse("mail:compose"), data)
        self.assertEqual(response.status_code, 302)
        draft = Message.objects.get(subject="Three attachments")
        self.assertEqual(draft.attachments.count(), 3)
        for attachment in draft.attachments.all():
            result = self.client.get(reverse("mail:attachment", args=[attachment.pk]))
            self.assertEqual(result.status_code, 200)
            self.assertTrue(b"".join(result.streaming_content).startswith(b"file "))
            result.close()

    def test_fourth_attachment_rejected_without_partially_editing_draft(self):
        for index in range(3):
            Attachment.objects.create(message=self.own, file=SimpleUploadedFile(f"saved{index}.txt", b"file"),
                                      original_name=f"saved{index}.txt", size=4, content_type="text/plain")
        self.login(self.assistant)
        response = self.client.post(reverse("mail:edit", args=[self.own.pk]), self.draft_data(
            subject="Should not save", attachment_1=SimpleUploadedFile("extra.txt", b"extra")))
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["form"].errors)
        self.own.refresh_from_db()
        self.assertEqual(self.own.subject, "Own assistant draft")
        self.assertEqual(self.own.attachments.count(), 3)

    def test_remove_then_replace_attachment_in_single_save(self):
        for index in range(3):
            Attachment.objects.create(message=self.own, file=SimpleUploadedFile(f"saved{index}.txt", b"file"),
                                      original_name=f"saved{index}.txt", size=4, content_type="text/plain")
        removed = self.own.attachments.first()
        self.login(self.assistant)
        response = self.client.post(reverse("mail:edit", args=[self.own.pk]), self.draft_data(
            remove_attachments=[removed.pk], attachment_1=SimpleUploadedFile("replacement.txt", b"replacement")))
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.own.attachments.count(), 3)
        self.assertFalse(Attachment.objects.filter(pk=removed.pk).exists())
        self.assertTrue(self.own.attachments.filter(original_name="replacement.txt").exists())

    def test_bcc_csv_appends_validated_recipients(self):
        self.login(self.assistant)
        response = self.client.post(reverse("mail:compose"), self.draft_data(
            subject="BCC import", bcc="original@example.test",
            bcc_csv=SimpleUploadedFile("bcc.csv", b"email\nimported@example.test\n", content_type="text/csv")))
        self.assertEqual(response.status_code, 302)
        draft = Message.objects.get(subject="BCC import")
        self.assertIn("original@example.test", draft.bcc)
        self.assertIn("imported@example.test", draft.bcc)


class MergeWorkflowTests(WorkspaceTestCase):
    def preview(self, content=b"email,first_name\none@example.test,Ada\ntwo@example.test,Grace\n"):
        return self.client.post(reverse("mail:merge"), {
            "action": "preview", "csv_file": SimpleUploadedFile("merge.csv", content, content_type="text/csv"),
            "subject": "Hello {{first_name}}", "body": "Dear {{first_name}}, welcome.",
            "cc": "", "bcc": "", "send_date": timezone.localdate(), "send_time": "00:00",
        })

    def test_preview_then_commit_creates_personalized_drafts_only_once(self):
        self.login(self.assistant)
        before = Message.objects.count()
        with patch("mail.views.send_message") as deliver:
            preview = self.preview()
            self.assertEqual(preview.status_code, 200)
            self.assertEqual(Message.objects.count(), before)
            self.assertEqual(len(preview.context["preview_rows"]), 2)
            token = preview.context["merge_token"]
            response = self.client.post(reverse("mail:merge"), {"action": "commit", "merge_token": token})
            self.assertEqual(response.status_code, 302)
            self.assertEqual(Message.objects.count(), before + 2)
            self.client.post(reverse("mail:merge"), {"action": "commit", "merge_token": token})
        deliver.assert_not_called()
        self.assertEqual(Message.objects.count(), before + 2)
        self.assertTrue(Message.objects.filter(created_by=self.assistant, workspace=self.workspace,
                                               subject="Hello Ada", body="Dear Ada, welcome.", status="draft").exists())

    def test_merge_commit_rejects_forged_token(self):
        self.login(self.assistant)
        before = Message.objects.count()
        self.client.post(reverse("mail:merge"), {"action": "commit", "merge_token": "forged"})
        self.assertEqual(Message.objects.count(), before)

    def test_invalid_late_csv_row_creates_no_partial_drafts(self):
        self.login(self.assistant)
        before = Message.objects.count()
        response = self.preview(b"email,first_name\none@example.test,Ada\ninvalid,Grace\n")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["form"].errors)
        self.assertEqual(Message.objects.count(), before)

    def test_merge_preview_token_cannot_be_used_by_another_user(self):
        self.login(self.assistant)
        response = self.preview()
        token = response.context["merge_token"]
        before = Message.objects.count()
        self.client.logout()
        self.login(self.outsider)
        self.client.post(reverse("mail:merge"), {"action": "commit", "merge_token": token})
        self.assertEqual(Message.objects.count(), before)

    def test_cc_and_bcc_placeholders_are_validated_after_expansion(self):
        self.login(self.assistant)
        response = self.client.post(reverse("mail:merge"), {
            "action": "preview", "csv_file": SimpleUploadedFile("merge.csv", b"email,cc_email,bcc_email\none@example.test,cc@example.test,bcc@example.test\n"),
            "subject": "Hello", "body": "Personalized recipients", "cc": "{{cc_email}}", "bcc": "{{bcc_email}}",
            "send_date": timezone.localdate(),
            "send_time": "00:00",
        })
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["preview_rows"][0]["cc"], "cc@example.test")
        self.assertEqual(response.context["preview_rows"][0]["bcc"], "bcc@example.test")
