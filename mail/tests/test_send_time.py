"""V3 calendar-date workflows, optional planning time and approval integrity."""

from datetime import date, datetime, time, timedelta, timezone as datetime_timezone
from types import SimpleNamespace
from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from mail.models import MergeReceipt, Message
from mail.tests.test_security import WorkspaceTestCase


class SendTimeTests(WorkspaceTestCase):
    def setUp(self):
        super().setUp()
        self.enterContext(timezone.override("America/Chicago"))
        # September 19 at 15:30 CDT; all production comparisons must use local time.
        self.clock = patch("django.utils.timezone.now", return_value=datetime(
            2026, 9, 19, 20, 30, tzinfo=datetime_timezone.utc))
        self.now = self.clock.start()
        self.addCleanup(self.clock.stop)
        self.today = date(2026, 9, 19)
        Message.objects.update(send_date=self.today)
        for item in (self.own, self.peer, self.foreign):
            item.refresh_from_db()

    def make_timed(self, name, *, day=None, at=None):
        return self.make_message(self.assistant, self.workspace, name,
                                 send_date=day or self.today, send_time=at)

    def boundary_drafts(self):
        Message.objects.filter(workspace=self.workspace).delete()
        return {
            "overdue": self.make_timed("Yesterday late", day=self.today - timedelta(days=1), at=time(23, 59)),
            "date_only": self.make_timed("Today without time"),
            "old_date_only": self.make_timed("Yesterday without time", day=self.today - timedelta(days=1)),
            "earlier": self.make_timed("Earlier today", at=time(15, 29)),
            "boundary": self.make_timed("Due at this minute", at=time(15, 30)),
            "later": self.make_timed("Later today", at=time(15, 31)),
            "tomorrow": self.make_timed("Tomorrow midnight", day=self.today + timedelta(days=1), at=time(0)),
        }

    def merge_preview(self, send_time="18:45"):
        return self.client.post(reverse("mail:merge"), {
            "action": "preview",
            "csv_file": SimpleUploadedFile("time.csv", b"email,name\none@example.test,One\ntwo@example.test,Two\n", content_type="text/csv"),
            "subject": "Timed CSV {{name}}", "body": "Hello {{name}}",
            "cc": "", "bcc": "", "send_date": self.today.isoformat(),
            "send_time": send_time,
        })

    def test_compose_and_edit_preserve_selected_time_without_delivery(self):
        self.login(self.assistant)
        with patch("mail.views.send_message") as deliver:
            response = self.client.post(reverse("mail:compose"), self.draft_data(
                subject="Selected send time", send_time="18:45"))
            self.assertEqual(response.status_code, 302)
            draft = Message.objects.get(subject="Selected send time")
            self.assertEqual(draft.send_time, time(18, 45))
            response = self.client.get(reverse("mail:edit", args=[draft.pk]))
            self.assertContains(response, 'type="time"')
            self.assertContains(response, 'value="18:45"')
            response = self.client.post(reverse("mail:edit", args=[draft.pk]),
                                        self.draft_data(draft, send_time="09:05"))
            self.assertEqual(response.status_code, 302)
        deliver.assert_not_called()
        draft.refresh_from_db()
        self.assertEqual(draft.send_time, time(9, 5))
        self.assertEqual(draft.version, 2)
        self.assertEqual(draft.status, "draft")

    def test_blank_or_missing_time_saves_date_only_compose_and_edit(self):
        self.login(self.assistant)
        before = Message.objects.count()
        for omitted in (True, False):
            data = self.draft_data(subject="Date-only draft", send_time="")
            if omitted:
                del data["send_time"]
            with self.subTest(omitted=omitted):
                response = self.client.post(reverse("mail:compose"), data)
                self.assertEqual(response.status_code, 302)
        self.assertEqual(Message.objects.count(), before + 2)
        self.assertEqual(Message.objects.filter(subject="Date-only draft", send_time__isnull=True).count(), 2)
        timed = self.make_timed("Clear optional time", at=time(16))
        response = self.client.post(reverse("mail:edit", args=[timed.pk]), self.draft_data(timed, send_time=""))
        self.assertEqual(response.status_code, 302)
        timed.refresh_from_db()
        self.assertIsNone(timed.send_time)
        self.assertEqual(timed.version, 2)

    def test_invalid_time_does_not_save_or_change_draft(self):
        self.login(self.assistant)
        before = Message.objects.count()
        for value in ("24:01", "09:60", "not-a-time", "09:30:00", "09:30:59"):
            with self.subTest(value=value):
                response = self.client.post(reverse("mail:edit", args=[self.own.pk]),
                                            self.draft_data(send_time=value, subject="Must not change"))
                self.assertEqual(response.status_code, 200)
                self.assertIn("send_time", response.context["form"].errors)
        self.own.refresh_from_db()
        self.assertEqual(self.own.subject, "Own assistant draft")
        self.assertEqual(self.own.version, 1)
        self.assertEqual(self.own.send_time, time(0))
        self.assertEqual(Message.objects.count(), before)

    def test_current_and_future_partition_by_local_date_regardless_of_time(self):
        items = self.boundary_drafts()
        self.login()
        current = self.client.get(reverse("mail:dashboard"), {"period": "current"})
        future = self.client.get(reverse("mail:dashboard"), {"period": "future"})
        self.assertEqual({item.pk for item in current.context["drafts"]},
                         {items[key].pk for key in ("overdue", "old_date_only", "date_only", "earlier", "boundary", "later")})
        self.assertEqual({item.pk for item in future.context["drafts"]},
                         {items[key].pk for key in ("tomorrow",)})
        self.assertEqual(current.context["counts"]["current"], 6)
        self.assertEqual(current.context["counts"]["future"], 1)
        self.assertEqual(current.context["counts"]["needs_time"], 2)

    def test_legacy_missing_times_are_visible_in_current_and_compatibility_filter(self):
        items = self.boundary_drafts()
        self.login()
        needs_time = self.client.get(reverse("mail:dashboard"), {"period": "needs_time"})
        self.assertEqual(needs_time.status_code, 200)
        self.assertEqual({item.pk for item in needs_time.context["drafts"]},
                         {items["date_only"].pk, items["old_date_only"].pk})
        self.assertContains(needs_time, "Date only")
        self.assertNotContains(needs_time, "Any time")
        all_drafts = self.client.get(reverse("mail:dashboard"), {"period": "all"})
        self.assertEqual({item.pk for item in all_drafts.context["drafts"]}, {item.pk for item in items.values()})

    def test_local_date_is_used_when_utc_date_has_advanced(self):
        self.now.return_value = datetime(2026, 9, 20, 0, 30, tzinfo=datetime_timezone.utc)
        later = self.make_timed("Seven thirty local is before eight", at=time(20))
        self.login()
        current = self.client.get(reverse("mail:dashboard"), {"period": "current"})
        future = self.client.get(reverse("mail:dashboard"), {"period": "future"})
        self.assertIn(later, current.context["drafts"])
        self.assertNotIn(later, future.context["drafts"])

    def test_explicit_midnight_is_current_from_local_midnight(self):
        self.now.return_value = datetime(2026, 9, 19, 5, 0, tzinfo=datetime_timezone.utc)
        items = self.boundary_drafts()
        midnight = self.make_timed("Explicit midnight", at=time(0))
        self.login()
        response = self.client.get(reverse("mail:dashboard"), {"period": "current"})
        self.assertEqual({item.pk for item in response.context["drafts"]},
                         {item.pk for key, item in items.items() if key != "tomorrow"} | {midnight.pk})

    def test_midnight_is_valid_optional_form_value(self):
        self.login(self.assistant)
        response = self.client.post(reverse("mail:compose"), self.draft_data(
            subject="Midnight selected intentionally", send_time="00:00"))
        self.assertEqual(response.status_code, 302)
        self.assertEqual(Message.objects.get(subject="Midnight selected intentionally").send_time, time(0))

    def test_new_and_legacy_forms_do_not_invent_a_send_time(self):
        self.login(self.assistant)
        legacy = self.make_timed("Old draft needing a time")
        for url in (reverse("mail:compose"), reverse("mail:edit", args=[legacy.pk]), reverse("mail:merge")):
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertFalse(response.context["form"].fields["send_time"].required)
                self.assertIn(response.context["form"]["send_time"].value(), (None, ""))

    def test_batch_sends_all_confirmed_dates_through_today(self):
        items = self.boundary_drafts()
        self.login()
        response = self.client.get(reverse("mail:send_current"))
        expected = {items[key].pk for key in ("overdue", "old_date_only", "date_only", "earlier", "boundary", "later")}
        self.assertEqual({item.pk for item in response.context["messages_to_act"]}, expected)
        with patch("mail.views.send_message", return_value=SimpleNamespace(status="sent", last_error="")) as deliver:
            response = self.client.post(reverse("mail:send_current"), {"batch_token": response.context["batch_token"]})
        self.assertEqual(response.status_code, 302)
        self.assertEqual({call.args[1] for call in deliver.call_args_list}, expected)

    def test_batch_rechecks_date_before_sending_any_message(self):
        self.login()
        response = self.client.get(reverse("mail:send_current"))
        # Isolate the time guard: a direct administrative update bypasses versioning.
        Message.objects.filter(pk=self.peer.pk).update(send_date=self.today + timedelta(days=1))
        with patch("mail.views.send_message") as deliver:
            response = self.client.post(reverse("mail:send_current"), {"batch_token": response.context["batch_token"]})
        self.assertEqual(response.status_code, 302)
        deliver.assert_not_called()

    def test_becoming_due_after_confirmation_does_not_expand_approved_batch(self):
        later = self.make_timed("Becomes due after preview", day=self.today + timedelta(days=1), at=time(15, 31))
        self.now.return_value = datetime(2026, 9, 20, 4, 59, tzinfo=datetime_timezone.utc)
        self.login()
        response = self.client.get(reverse("mail:send_current"))
        self.now.return_value = datetime(2026, 9, 20, 5, 1, tzinfo=datetime_timezone.utc)
        with patch("mail.views.send_message", return_value=SimpleNamespace(status="sent", last_error="")) as deliver:
            self.client.post(reverse("mail:send_current"), {"batch_token": response.context["batch_token"]})
        sent_ids = {call.args[1] for call in deliver.call_args_list}
        self.assertEqual(sent_ids, {self.own.pk, self.peer.pk})
        self.assertNotIn(later.pk, sent_ids)

    def test_batch_rejects_time_removed_after_confirmation_before_sending_any(self):
        self.login()
        response = self.client.get(reverse("mail:send_current"))
        Message.objects.filter(pk=self.peer.pk).update(send_time=None, version=self.peer.version + 1)
        with patch("mail.views.send_message") as deliver:
            response = self.client.post(reverse("mail:send_current"), {"batch_token": response.context["batch_token"]})
        self.assertEqual(response.status_code, 302)
        deliver.assert_not_called()

    def test_time_edit_invalidates_existing_individual_approval(self):
        self.login()
        response = self.client.get(reverse("mail:send", args=[self.own.pk]))
        token = response.context["batch_token"]
        assistant = Client()
        assistant.force_login(self.assistant)
        changed = assistant.post(reverse("mail:edit", args=[self.own.pk]), self.draft_data(send_time="16:00"))
        self.assertEqual(changed.status_code, 302)
        with patch("mail.services._deliver_demo") as deliver:
            self.client.post(reverse("mail:send", args=[self.own.pk]), {"batch_token": token})
        deliver.assert_not_called()
        self.own.refresh_from_db()
        self.assertEqual(self.own.send_time, time(16))
        self.assertEqual(self.own.status, "draft")

    def test_executive_can_explicitly_send_later_today_immediately(self):
        later = self.make_timed("Explicit send overrides planning time", at=time(22))
        self.login()
        response = self.client.get(reverse("mail:send", args=[later.pk]))
        response = self.client.post(reverse("mail:send", args=[later.pk]), {"batch_token": response.context["batch_token"]})
        self.assertEqual(response.status_code, 302)
        later.refresh_from_db()
        self.assertEqual(later.status, "sent")
        self.assertTrue(later.provider_id.startswith("demo-"))
        self.assertEqual(later.sent_at, self.now.return_value)

    def test_executive_can_explicitly_send_legacy_draft_without_time(self):
        legacy = self.make_timed("Explicit send of legacy draft")
        self.login()
        response = self.client.get(reverse("mail:send", args=[legacy.pk]))
        response = self.client.post(reverse("mail:send", args=[legacy.pk]), {"batch_token": response.context["batch_token"]})
        self.assertEqual(response.status_code, 302)
        legacy.refresh_from_db()
        self.assertEqual(legacy.status, "sent")
        self.assertTrue(legacy.provider_id.startswith("demo-"))
        self.assertIsNone(legacy.send_time)

    def test_review_filters_future_date_and_saves_time_without_sending(self):
        future = self.make_timed("Review future time", day=self.today + timedelta(days=1), at=time(18))
        self.login()
        response = self.client.get(reverse("mail:review", args=["future"]))
        self.assertEqual(response.context["message_obj"].pk, future.pk)
        with patch("mail.views.send_message") as deliver:
            saved = self.client.post(reverse("mail:review", args=["future"]), self.draft_data(
                future, send_time="19:15", review_token=response.context["review_token"]))
        self.assertEqual(saved.status_code, 302)
        deliver.assert_not_called()
        future.refresh_from_db()
        self.assertEqual(future.send_time, time(19, 15))
        self.assertEqual(future.status, "draft")

    def test_merge_preview_commit_preserves_approved_time_for_every_row(self):
        self.login(self.assistant)
        before = Message.objects.count()
        with patch("mail.views.send_message") as deliver:
            preview = self.merge_preview()
            self.assertEqual(preview.status_code, 200)
            self.assertEqual(Message.objects.count(), before)
            response = self.client.post(reverse("mail:merge"), {
                "action": "commit", "merge_token": preview.context["merge_token"], "send_time": "23:59",
            })
        self.assertEqual(response.status_code, 302)
        deliver.assert_not_called()
        rows = list(Message.objects.filter(subject__startswith="Timed CSV"))
        self.assertEqual(len(rows), 2)
        self.assertTrue(all(row.send_time == time(18, 45) and row.send_date == self.today for row in rows))

    def test_merge_invalid_time_does_not_offer_preview_or_create_drafts(self):
        self.login(self.assistant)
        before = Message.objects.count()
        for value in ("24:00", "18:45:00", "18:45:23"):
            with self.subTest(value=value):
                response = self.merge_preview(send_time=value)
                self.assertEqual(response.status_code, 200)
                self.assertIn("send_time", response.context["form"].errors)
                self.assertNotIn("merge_token", response.context)
        self.assertEqual(Message.objects.count(), before)

    def test_date_only_merge_preview_commits_without_inventing_time(self):
        self.login(self.assistant)
        preview = self.merge_preview(send_time="")
        self.assertEqual(preview.status_code, 200)
        response = self.client.post(reverse("mail:merge"), {
            "action": "commit", "merge_token": preview.context["merge_token"],
        })
        self.assertEqual(response.status_code, 302)
        rows = list(Message.objects.filter(subject__startswith="Timed CSV"))
        self.assertEqual(len(rows), 2)
        self.assertTrue(all(row.send_time is None for row in rows))
        self.assertTrue(MergeReceipt.objects.filter(token=preview.context["merge_token"]).exists())

    def test_legacy_merge_preview_zero_seconds_is_accepted_without_rounding(self):
        self.login(self.assistant)
        preview = self.merge_preview()
        session = self.client.session
        saved = session["merge_preview"]
        saved["send_time"] = "18:45:00"
        session["merge_preview"] = saved
        session.save()
        response = self.client.post(reverse("mail:merge"), {
            "action": "commit", "merge_token": preview.context["merge_token"],
        })
        self.assertEqual(response.status_code, 302)
        rows = list(Message.objects.filter(subject__startswith="Timed CSV"))
        self.assertEqual(len(rows), 2)
        self.assertTrue(all(row.send_time == time(18, 45) for row in rows))

    def test_invalid_stored_merge_time_cannot_create_drafts_or_receipt(self):
        self.login(self.assistant)
        before = Message.objects.count()
        for value in (123, {"hour": 18}, "18:45:01", "invalid"):
            with self.subTest(value=value):
                preview = self.merge_preview()
                session = self.client.session
                saved = session["merge_preview"]
                saved["send_time"] = value
                session["merge_preview"] = saved
                session.save()
                response = self.client.post(reverse("mail:merge"), {
                    "action": "commit", "merge_token": preview.context["merge_token"],
                })
                self.assertEqual(response.status_code, 400)
                self.assertEqual(Message.objects.count(), before)
                self.assertFalse(MergeReceipt.objects.filter(token=preview.context["merge_token"]).exists())
