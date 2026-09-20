"""Date-only planning, ignored legacy times and V3 manual sending."""

from datetime import date, datetime, time, timedelta, timezone as datetime_timezone
from types import SimpleNamespace
from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from mail.models import MergeReceipt, Message
from mail.tests.test_security import WorkspaceTestCase


class SendDateTests(WorkspaceTestCase):
    def setUp(self):
        super().setUp()
        self.enterContext(timezone.override("America/Chicago"))
        # September 19 at 15:30 CDT; comparisons must use the local calendar date.
        self.now = self.enterContext(patch("django.utils.timezone.now", return_value=datetime(
            2026, 9, 19, 20, 30, tzinfo=datetime_timezone.utc)))
        self.today = date(2026, 9, 19)
        Message.objects.update(send_date=self.today)
        for item in (self.own, self.peer, self.foreign):
            item.refresh_from_db()

    def make_draft(self, name, *, day=None, legacy_time=None):
        return self.make_message(self.assistant, self.workspace, name,
                                 send_date=day or self.today, send_time=legacy_time)

    def boundary_drafts(self):
        Message.objects.filter(workspace=self.workspace).delete()
        return {
            "overdue": self.make_draft("Yesterday late", day=self.today - timedelta(days=1), legacy_time=time(23, 59)),
            "today": self.make_draft("Today draft"),
            "old": self.make_draft("Yesterday draft", day=self.today - timedelta(days=1)),
            "legacy_early": self.make_draft("Legacy earlier", legacy_time=time(15, 29)),
            "legacy_boundary": self.make_draft("Legacy boundary", legacy_time=time(15, 30)),
            "legacy_late": self.make_draft("Legacy later", legacy_time=time(15, 31)),
            "tomorrow": self.make_draft("Tomorrow draft", day=self.today + timedelta(days=1), legacy_time=time(0)),
        }

    def merge_preview(self, **extra):
        data = {
            "action": "preview",
            "csv_file": SimpleUploadedFile("people.csv", b"email,name\none@example.test,One\ntwo@example.test,Two\n", content_type="text/csv"),
            "subject": "Date CSV {{name}}", "body": "Hello {{name}}",
            "cc": "", "bcc": "", "send_date": self.today.isoformat(),
        }
        data.update(extra)
        return self.client.post(reverse("mail:merge"), data)

    def test_new_edit_and_merge_forms_offer_date_without_time(self):
        self.login(self.assistant)
        legacy = self.make_draft("Legacy timed draft", legacy_time=time(18, 45))
        for url in (reverse("mail:compose"), reverse("mail:edit", args=[legacy.pk]), reverse("mail:merge")):
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertTrue(response.context["form"].fields["send_date"].required)
                self.assertNotIn("send_time", response.context["form"].fields)
                self.assertContains(response, 'type="date"')
                self.assertNotContains(response, 'type="time"')
                self.assertNotContains(response, 'name="send_time"')
                self.assertNotContains(response, "Planning time")

    def test_compose_ignores_stale_posted_time_and_never_sends(self):
        self.login(self.assistant)
        for value in (None, "", "18:45", "24:01", "not-a-time", "18:45:59"):
            data = self.draft_data(subject="Date-only draft")
            data.pop("send_time", None)
            if value is not None:
                data["send_time"] = value
            with self.subTest(value=value), patch("mail.views.send_message") as deliver:
                response = self.client.post(reverse("mail:compose"), data)
                self.assertEqual(response.status_code, 302)
                deliver.assert_not_called()
        drafts = list(Message.objects.filter(subject="Date-only draft"))
        self.assertEqual(len(drafts), 6)
        self.assertTrue(all(row.send_time is None and row.send_date == self.today for row in drafts))

    def test_edit_clears_legacy_time_and_ignores_posted_time_without_sending(self):
        self.login(self.assistant)
        legacy = self.make_draft("Legacy draft", legacy_time=time(16))
        with patch("mail.views.send_message") as deliver:
            response = self.client.post(reverse("mail:edit", args=[legacy.pk]), self.draft_data(
                legacy, send_date=self.today + timedelta(days=2), send_time="19:15"))
        self.assertEqual(response.status_code, 302)
        deliver.assert_not_called()
        legacy.refresh_from_db()
        self.assertIsNone(legacy.send_time)
        self.assertEqual(legacy.send_date, self.today + timedelta(days=2))
        self.assertEqual(legacy.version, 2)
        self.assertEqual(legacy.status, "draft")

    def test_date_remains_required_for_compose_and_merge(self):
        self.login(self.assistant)
        before = Message.objects.count()
        response = self.client.post(reverse("mail:compose"), self.draft_data(send_date=""))
        self.assertIn("send_date", response.context["form"].errors)
        response = self.merge_preview(send_date="")
        self.assertIn("send_date", response.context["form"].errors)
        self.assertNotIn("merge_token", response.context)
        self.assertEqual(Message.objects.count(), before)

    def test_current_and_future_partition_by_local_date_ignoring_legacy_times(self):
        items = self.boundary_drafts()
        self.login()
        current = self.client.get(reverse("mail:dashboard"), {"period": "current"})
        future = self.client.get(reverse("mail:dashboard"), {"period": "future"})
        self.assertEqual({item.pk for item in current.context["drafts"]},
                         {item.pk for key, item in items.items() if key != "tomorrow"})
        self.assertEqual({item.pk for item in future.context["drafts"]}, {items["tomorrow"].pk})
        self.assertEqual(current.context["counts"]["current"], 6)
        self.assertEqual(current.context["counts"]["future"], 1)
        self.assertNotIn("needs_time", current.context["counts"])

    def test_removed_time_filter_cannot_exclude_date_only_drafts(self):
        self.login()
        for url in (reverse("mail:dashboard") + "?period=needs_time", reverse("mail:review", args=["needs_time"])):
            self.assertEqual(self.client.get(url).status_code, 404)

    def test_local_date_is_used_when_utc_date_has_advanced(self):
        self.now.return_value = datetime(2026, 9, 20, 0, 30, tzinfo=datetime_timezone.utc)
        draft = self.make_draft("Still September 19 locally", legacy_time=time(20))
        self.login()
        current = self.client.get(reverse("mail:dashboard"), {"period": "current"})
        future = self.client.get(reverse("mail:dashboard"), {"period": "future"})
        self.assertIn(draft, current.context["drafts"])
        self.assertNotIn(draft, future.context["drafts"])

    def test_entire_date_is_current_from_local_midnight(self):
        self.now.return_value = datetime(2026, 9, 19, 5, 0, tzinfo=datetime_timezone.utc)
        items = self.boundary_drafts()
        self.login()
        response = self.client.get(reverse("mail:dashboard"), {"period": "current"})
        self.assertEqual({item.pk for item in response.context["drafts"]},
                         {item.pk for key, item in items.items() if key != "tomorrow"})

    def test_legacy_times_do_not_change_same_date_draft_order(self):
        first = self.make_draft("Created first", legacy_time=time(23, 59))
        second = self.make_draft("Created second", legacy_time=time(0))
        self.assertEqual(list(Message.objects.filter(pk__in=[first.pk, second.pk]).values_list("pk", flat=True)),
                         [first.pk, second.pk])

    def test_batch_sends_all_confirmed_dates_through_today(self):
        items = self.boundary_drafts()
        self.login()
        response = self.client.get(reverse("mail:send_current"))
        expected = {item.pk for key, item in items.items() if key != "tomorrow"}
        self.assertEqual({item.pk for item in response.context["messages_to_act"]}, expected)
        with patch("mail.views.send_message", return_value=SimpleNamespace(status="sent", last_error="")) as deliver:
            response = self.client.post(reverse("mail:send_current"), {"batch_token": response.context["batch_token"]})
        self.assertEqual(response.status_code, 302)
        self.assertEqual({call.args[1] for call in deliver.call_args_list}, expected)

    def test_batch_rechecks_date_before_sending_any_message(self):
        self.login()
        response = self.client.get(reverse("mail:send_current"))
        # An administrative update can bypass normal edit versioning.
        Message.objects.filter(pk=self.peer.pk).update(send_date=self.today + timedelta(days=1))
        with patch("mail.views.send_message") as deliver:
            response = self.client.post(reverse("mail:send_current"), {"batch_token": response.context["batch_token"]})
        self.assertEqual(response.status_code, 302)
        deliver.assert_not_called()

    def test_becoming_due_after_confirmation_does_not_expand_approved_batch(self):
        later = self.make_draft("Becomes due after preview", day=self.today + timedelta(days=1))
        self.now.return_value = datetime(2026, 9, 20, 4, 59, tzinfo=datetime_timezone.utc)
        self.login()
        response = self.client.get(reverse("mail:send_current"))
        self.now.return_value = datetime(2026, 9, 20, 5, 1, tzinfo=datetime_timezone.utc)
        with patch("mail.views.send_message", return_value=SimpleNamespace(status="sent", last_error="")) as deliver:
            self.client.post(reverse("mail:send_current"), {"batch_token": response.context["batch_token"]})
        sent_ids = {call.args[1] for call in deliver.call_args_list}
        self.assertEqual(sent_ids, {self.own.pk, self.peer.pk})
        self.assertNotIn(later.pk, sent_ids)

    def test_date_edit_invalidates_existing_individual_approval(self):
        self.login()
        response = self.client.get(reverse("mail:send", args=[self.own.pk]))
        token = response.context["batch_token"]
        assistant = Client()
        assistant.force_login(self.assistant)
        changed = assistant.post(reverse("mail:edit", args=[self.own.pk]),
                                 self.draft_data(send_date=self.today + timedelta(days=1)))
        self.assertEqual(changed.status_code, 302)
        with patch("mail.services._deliver_demo") as deliver:
            self.client.post(reverse("mail:send", args=[self.own.pk]), {"batch_token": token})
        deliver.assert_not_called()
        self.own.refresh_from_db()
        self.assertEqual(self.own.status, "draft")

    def test_executive_can_explicitly_send_a_future_dated_draft_now(self):
        future = self.make_draft("Send future explicitly", day=self.today + timedelta(days=30), legacy_time=time(22))
        self.login()
        response = self.client.get(reverse("mail:send", args=[future.pk]))
        response = self.client.post(reverse("mail:send", args=[future.pk]), {"batch_token": response.context["batch_token"]})
        self.assertEqual(response.status_code, 302)
        future.refresh_from_db()
        self.assertEqual(future.status, "sent")
        self.assertTrue(future.provider_id.startswith("demo-"))
        self.assertEqual(future.sent_at, self.now.return_value)

    def test_review_saves_date_without_sending_or_accepting_time(self):
        future = self.make_draft("Review future date", day=self.today + timedelta(days=1), legacy_time=time(18))
        self.login()
        response = self.client.get(reverse("mail:review", args=["future"]))
        self.assertEqual(response.context["message_obj"].pk, future.pk)
        self.assertNotContains(response, 'name="send_time"')
        with patch("mail.views.send_message") as deliver:
            saved = self.client.post(reverse("mail:review", args=["future"]), self.draft_data(
                future, send_date=self.today + timedelta(days=2), send_time="19:15", review_token=response.context["review_token"]))
        self.assertEqual(saved.status_code, 302)
        deliver.assert_not_called()
        future.refresh_from_db()
        self.assertIsNone(future.send_time)
        self.assertEqual(future.send_date, self.today + timedelta(days=2))
        self.assertEqual(future.status, "draft")

    def test_merge_preview_and_commit_ignore_posted_time(self):
        self.login(self.assistant)
        before = Message.objects.count()
        with patch("mail.views.send_message") as deliver:
            preview = self.merge_preview(send_time="18:45")
            self.assertEqual(preview.status_code, 200)
            self.assertNotIn("send_time", self.client.session["merge_preview"])
            self.assertNotContains(preview, "18:45")
            self.assertEqual(Message.objects.count(), before)
            response = self.client.post(reverse("mail:merge"), {
                "action": "commit", "merge_token": preview.context["merge_token"], "send_time": "23:59",
            })
        self.assertEqual(response.status_code, 302)
        deliver.assert_not_called()
        rows = list(Message.objects.filter(subject__startswith="Date CSV"))
        self.assertEqual(len(rows), 2)
        self.assertTrue(all(row.send_time is None and row.send_date == self.today for row in rows))
        self.assertTrue(MergeReceipt.objects.filter(token=preview.context["merge_token"]).exists())

    def test_legacy_merge_preview_time_is_ignored_regardless_of_value(self):
        self.login(self.assistant)
        for value in ("18:45", "18:45:00", "invalid", 123, {"hour": 18}):
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
                self.assertEqual(response.status_code, 302)
        rows = list(Message.objects.filter(subject__startswith="Date CSV"))
        self.assertEqual(len(rows), 10)
        self.assertTrue(all(row.send_time is None for row in rows))

    def test_legacy_planning_time_is_hidden_but_actual_sent_time_remains_visible(self):
        legacy = self.make_draft("Legacy draft", legacy_time=time(18, 45))
        self.login()
        for url in (reverse("mail:dashboard"), reverse("mail:detail", args=[legacy.pk]), reverse("mail:send", args=[legacy.pk])):
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertNotContains(response, "Planning time")
                self.assertNotContains(response, "6:45")
                self.assertNotContains(response, "18:45")
        Message.objects.filter(pk=legacy.pk).update(status="sent", sent_at=self.now.return_value)
        for url in (reverse("mail:detail", args=[legacy.pk]), reverse("mail:sent")):
            self.assertContains(self.client.get(url), "3:30 PM")
