"""Independent V3 document acceptance and dashboard-send abuse cases.

These tests use synthetic isolated data and the local demo transport only.
"""

from datetime import date, datetime, time, timedelta, timezone as datetime_timezone
from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from mail.models import Attachment, Message
from mail.services import DeliveryRejected
from mail.tests.test_security import WorkspaceTestCase


class V3AcceptanceTests(WorkspaceTestCase):
    def setUp(self):
        self.enterContext(timezone.override('America/Chicago'))
        self.clock = self.enterContext(patch('django.utils.timezone.now', return_value=datetime(
            2025, 12, 2, 18, 0, tzinfo=datetime_timezone.utc)))
        Message.objects.filter(workspace=self.workspace).delete()
        self.login()

    def draft(self, subject, day=date(2025, 12, 2), at=None):
        return self.make_message(self.assistant, self.workspace, subject, send_date=day, send_time=at)

    def dashboard(self, client=None, **filters):
        response = (client or self.client).get(reverse('mail:dashboard'), filters)
        self.assertEqual(response.status_code, 200)
        return response

    def token(self, draft, client=None):
        response = self.dashboard(client)
        return next(item.dashboard_token for item in response.context['drafts'] if item.pk == draft.pk)

    def post_send(self, draft, token, client=None):
        return (client or self.client).post(reverse('mail:send', args=[draft.pk]), {'dashboard_token': token})

    def test_december_first_second_third_document_example(self):
        first = self.draft('December first', date(2025, 12, 1))
        second = self.draft('December second', at=time(23, 59))
        third = self.draft('December third', date(2025, 12, 3))
        current = self.client.get(reverse('mail:review', args=['current']))
        self.assertEqual(current.context['review_total'], 2)
        self.assertEqual(current.context['message_obj'].pk, first.pk)
        second_review = self.client.get(reverse('mail:review', args=['current']) + '?index=1')
        self.assertEqual(second_review.context['message_obj'].pk, second.pk)
        with patch('mail.services._deliver_demo', side_effect=['demo-first', 'demo-second']) as delivery:
            page = self.dashboard()
            self.client.post(reverse('mail:send_current'), {'dashboard_token': page.context['dashboard_batch_token']})
        self.assertEqual(delivery.call_count, 2)
        self.assertEqual(set(Message.objects.filter(workspace=self.workspace, status='sent').values_list('pk', flat=True)),
                         {first.pk, second.pk})
        self.assertEqual([item.pk for item in self.dashboard().context['drafts']], [third.pk])
        self.clock.return_value = datetime(2025, 12, 3, 6, 0, tzinfo=datetime_timezone.utc)
        self.login()  # The executive returns the next day after session expiry.
        future = self.client.get(reverse('mail:review', args=['future']))
        self.assertEqual(future.status_code, 200)
        self.assertFalse(future.context.get('message_obj'))
        all_review = self.client.get(reverse('mail:review', args=['all']))
        self.assertEqual(all_review.context['review_total'], 1)
        self.assertEqual(all_review.context['message_obj'].pk, third.pk)
        page = self.dashboard()
        with patch('mail.services._deliver_demo', return_value='demo-third') as delivery:
            self.client.post(reverse('mail:send_current'), {'dashboard_token': page.context['dashboard_batch_token']})
        delivery.assert_called_once()
        self.assertEqual(self.dashboard().context['drafts'], [])

    def test_entire_local_date_in_current_regardless_of_optional_time(self):
        drafts = [self.draft('Earlier date', date(2025, 12, 1)), self.draft('Today no time'),
                  self.draft('Today later time', at=time(23, 59)), self.draft('Next date', date(2025, 12, 3))]
        # UTC has already advanced to December 3; Chicago is still December 2.
        self.clock.return_value = datetime(2025, 12, 3, 1, 0, tzinfo=datetime_timezone.utc)
        current = {item.pk for item in self.dashboard(period='current').context['drafts']}
        future = {item.pk for item in self.dashboard(period='future').context['drafts']}
        self.assertEqual(current, {item.pk for item in drafts[:3]})
        self.assertEqual(future, {drafts[3].pk})
        self.assertEqual(current | future, {item.pk for item in drafts})

    def test_assistant_can_save_date_only_draft_with_every_pdf_attribute(self):
        self.login(self.assistant)
        with patch('mail.views.send_message') as send, patch('mail.services._deliver_demo') as delivery:
            response = self.client.post(reverse('mail:compose'), {
                'version': 1, 'to': 'to@example.test', 'cc': 'cc@example.test', 'bcc': 'bcc@example.test',
                'subject': 'Date-only draft', 'body': 'Prepared by assistant', 'send_date': '2028-12-01',
                'attachment_1': SimpleUploadedFile('prepared.txt', b'prepared document'),
            })
        self.assertEqual(response.status_code, 302)
        send.assert_not_called()
        delivery.assert_not_called()
        draft = Message.objects.get(subject='Date-only draft')
        self.assertIsNone(draft.send_time)
        self.assertEqual(draft.send_date, date(2028, 12, 1))
        self.assertEqual(draft.status, 'draft')
        self.assertEqual(draft.attachments.count(), 1)
        self.assertEqual(draft.created_by_id, self.assistant.pk)

    def test_review_updates_all_fields_and_replaces_attachment_without_sending(self):
        draft = self.draft('Assistant original')
        old = Attachment.objects.create(message=draft, file=SimpleUploadedFile('old.txt', b'old'),
                                        original_name='old.txt', size=3)
        page = self.client.get(reverse('mail:review', args=['all']))
        with patch('mail.views.send_message') as send, patch('mail.services._deliver_demo') as delivery:
            response = self.client.post(reverse('mail:review', args=['all']), self.draft_data(
                draft, to='new-to@example.test', cc='new-cc@example.test', bcc='new-bcc@example.test',
                subject='Executive voice', body='Executive revised the complete text.',
                send_date='2029-01-01', send_time='', remove_attachments=[old.pk],
                attachment_1=SimpleUploadedFile('new.txt', b'new content'),
                review_token=page.context['review_token']))
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse('mail:dashboard'))
        send.assert_not_called()
        delivery.assert_not_called()
        draft.refresh_from_db()
        self.assertEqual((draft.to, draft.cc, draft.bcc), ('new-to@example.test', 'new-cc@example.test', 'new-bcc@example.test'))
        self.assertEqual((draft.subject, draft.body), ('Executive voice', 'Executive revised the complete text.'))
        self.assertEqual(draft.send_date, date(2029, 1, 1))
        self.assertIsNone(draft.send_time)
        self.assertEqual(draft.status, 'draft')
        self.assertEqual(list(draft.attachments.values_list('original_name', flat=True)), ['new.txt'])
        assistant = Client()
        assistant.force_login(self.assistant)
        self.assertContains(self.dashboard(assistant), 'Executive voice')
        self.client.post(reverse('mail:delete', args=[draft.pk]), {'version': draft.version})
        self.assertNotContains(self.dashboard(), 'Executive voice')
        self.assertNotContains(self.dashboard(assistant), 'Executive voice')
        self.assertFalse(Message.objects.filter(pk=draft.pk).exists())

    def test_loading_or_reviewing_due_messages_never_delivers_automatically(self):
        draft = self.draft('Due long ago', date(2020, 1, 1))
        with patch('mail.views.send_message') as send, patch('mail.services._deliver_demo') as delivery:
            self.dashboard()
            page = self.client.get(reverse('mail:review', args=['current']))
            self.client.post(reverse('mail:review', args=['current']), self.draft_data(
                draft, body='Reviewed but not sent', review_token=page.context['review_token']))
            self.clock.return_value += timedelta(days=10)
            self.login()
            self.dashboard()
        send.assert_not_called()
        delivery.assert_not_called()
        draft.refresh_from_db()
        self.assertEqual(draft.status, 'draft')

    def test_dashboard_single_post_sends_future_message_and_replay_never_redelivers(self):
        draft = self.draft('Future override', date(2030, 1, 1))
        token = self.token(draft)
        with patch('mail.services._deliver_demo', return_value='demo-once') as delivery:
            self.assertEqual(self.post_send(draft, token).status_code, 302)
            self.post_send(draft, token)
        delivery.assert_called_once()
        outgoing = delivery.call_args.args[0]
        self.assertEqual(str(outgoing['From']), self.executive.email)
        self.assertEqual(str(outgoing['Subject']), draft.subject)
        draft.refresh_from_db()
        self.assertEqual(draft.status, 'sent')

    def test_assistant_cannot_use_copied_executive_dashboard_tokens(self):
        draft = self.draft('Own assistant draft')
        page = self.dashboard()
        token = next(item.dashboard_token for item in page.context['drafts'] if item.pk == draft.pk)
        assistant = Client()
        assistant.force_login(self.assistant)
        with patch('mail.views.send_message') as send:
            self.assert_denied(self.post_send(draft, token, assistant))
            self.assert_denied(assistant.post(reverse('mail:send_current'), {
                'dashboard_token': page.context['dashboard_batch_token']}))
        send.assert_not_called()
        response = self.dashboard(assistant)
        self.assertNotContains(response, 'name="dashboard_token"')
        self.assertNotContains(response, 'Send Current Messages')

    def test_dashboard_token_rejects_tampering_cross_message_and_cross_action(self):
        first, second = self.draft('First'), self.draft('Second')
        page = self.dashboard()
        token = next(item.dashboard_token for item in page.context['drafts'] if item.pk == first.pk)
        with patch('mail.views.send_message') as send:
            self.post_send(first, token + 'tampered')
            self.post_send(second, token)
            self.post_send(first, page.context['dashboard_batch_token'])
            self.client.post(reverse('mail:send_current'), {'dashboard_token': token})
        send.assert_not_called()

    def test_foreign_executive_cannot_use_another_workspaces_batch_approval(self):
        self.draft('Private workspace message')
        token = self.dashboard().context['dashboard_batch_token']
        other = Client()
        other.force_login(self.outsider)
        with patch('mail.views.send_message') as send:
            other.post(reverse('mail:send_current'), {'dashboard_token': token})
        send.assert_not_called()

    def test_dashboard_approval_expires_and_rejects_clock_rollback(self):
        draft = self.draft('Expires')
        for delta in (timedelta(seconds=1801), timedelta(seconds=-1)):
            with self.subTest(delta=delta):
                issued_at = self.clock.return_value
                token = self.token(draft)
                self.clock.return_value = issued_at + delta
                with patch('mail.views.send_message') as send:
                    self.post_send(draft, token)
                send.assert_not_called()
                self.clock.return_value = issued_at

    def test_changed_content_invalidates_dashboard_approval_before_transport(self):
        draft = self.draft('Before edit')
        token = self.token(draft)
        assistant = Client()
        assistant.force_login(self.assistant)
        response = assistant.post(reverse('mail:edit', args=[draft.pk]), self.draft_data(draft, body='Changed after display'))
        self.assertEqual(response.status_code, 302)
        with patch('mail.services._deliver_demo') as delivery:
            self.post_send(draft, token)
        delivery.assert_not_called()
        draft.refresh_from_db()
        self.assertEqual(draft.status, 'draft')

    def test_changed_signature_invalidates_dashboard_individual_and_batch(self):
        draft = self.draft('Signature matters')
        page = self.dashboard()
        token = next(item.dashboard_token for item in page.context['drafts'] if item.pk == draft.pk)
        assistant = Client()
        assistant.force_login(self.assistant)
        assistant.post(reverse('mail:signature'), {'signature': 'Updated signature'})
        with patch('mail.views.send_message') as send:
            self.post_send(draft, token)
            self.client.post(reverse('mail:send_current'), {'dashboard_token': page.context['dashboard_batch_token']})
        send.assert_not_called()

    def test_failed_delivery_requires_new_dashboard_approval_before_retry(self):
        draft = self.draft('Retry after provider rejection')
        token = self.token(draft)
        with patch('mail.services._deliver_demo', side_effect=DeliveryRejected('synthetic rejection')) as delivery:
            self.post_send(draft, token)
            self.post_send(draft, token)
        delivery.assert_called_once()
        draft.refresh_from_db()
        self.assertEqual(draft.status, 'failed')
        new_token = self.token(draft)
        with patch('mail.services._deliver_demo', return_value='demo-retry') as delivery:
            self.post_send(draft, new_token)
        delivery.assert_called_once()
        draft.refresh_from_db()
        self.assertEqual(draft.status, 'sent')

    def test_batch_approval_does_not_expand_for_new_or_newly_current_drafts(self):
        original = self.draft('In approved batch')
        future = self.draft('Becomes current', date(2025, 12, 3))
        self.clock.return_value = datetime(2025, 12, 3, 5, 59, tzinfo=datetime_timezone.utc)
        self.login()
        token = self.dashboard().context['dashboard_batch_token']
        added = self.draft('Added after dashboard display')
        self.clock.return_value += timedelta(minutes=2)
        with patch('mail.services._deliver_demo', return_value='demo-snapshot') as delivery:
            self.client.post(reverse('mail:send_current'), {'dashboard_token': token})
            self.client.post(reverse('mail:send_current'), {'dashboard_token': token})
        delivery.assert_called_once()
        self.assertEqual(set(Message.objects.filter(workspace=self.workspace, status='sent').values_list('pk', flat=True)), {original.pk})
        self.assertEqual(set(Message.objects.filter(workspace=self.workspace, status='draft').values_list('pk', flat=True)), {added.pk, future.pk})

    def test_changed_batch_member_prevents_all_delivery(self):
        first, second = self.draft('First'), self.draft('Second')
        token = self.dashboard().context['dashboard_batch_token']
        assistant = Client()
        assistant.force_login(self.assistant)
        assistant.post(reverse('mail:edit', args=[second.pk]), self.draft_data(second, subject='Changed second'))
        with patch('mail.views.send_message') as send:
            self.client.post(reverse('mail:send_current'), {'dashboard_token': token})
        send.assert_not_called()
        first.refresh_from_db()
        self.assertEqual(first.status, 'draft')

    def test_oneclick_dashboard_post_still_requires_csrf(self):
        draft = self.draft('CSRF protected')
        strict = Client(enforce_csrf_checks=True)
        strict.force_login(self.executive)
        page = self.dashboard(strict)
        token = next(item.dashboard_token for item in page.context['drafts'] if item.pk == draft.pk)
        with patch('mail.views.send_message') as send:
            self.assertEqual(self.post_send(draft, token, strict).status_code, 403)
            self.assertEqual(strict.post(reverse('mail:send_current'), {
                'dashboard_token': page.context['dashboard_batch_token']}).status_code, 403)
        send.assert_not_called()
