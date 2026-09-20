"""Regressions from the independent workflow audit; no external delivery."""

from datetime import timedelta
from pathlib import Path
import tempfile
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.files.storage import FileSystemStorage
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TransactionTestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from mail.models import Attachment, Membership, Message, Workspace
from mail.tests.test_security import WorkspaceTestCase


class WorkflowAuditTests(WorkspaceTestCase):
    def test_second_review_tab_cannot_redirect_first_tabs_edits_to_another_draft(self):
        self.login()
        url = reverse('mail:review', args=['all'])
        first_tab = self.client.get(url)
        self.assertContains(first_tab, 'name="review_token"')
        original = first_tab.context['message_obj']
        old_data = self.draft_data(original, subject='Edits from the first tab')
        old_data['review_token'] = first_tab.context['review_token']
        earlier = self.make_message(self.assistant, self.workspace, 'Earlier draft',
                                    send_date=timezone.localdate() - timedelta(days=1))
        second_tab = self.client.get(url)
        self.assertEqual(second_tab.context['message_obj'].pk, earlier.pk)
        response = self.client.post(url, old_data)
        self.assertEqual(response.status_code, 409)
        earlier.refresh_from_db()
        original.refresh_from_db()
        self.assertEqual(earlier.subject, 'Earlier draft')
        self.assertEqual(original.subject, 'Own assistant draft')

    def test_review_rejects_missing_forged_and_wrong_position_tokens(self):
        self.login()
        url = reverse('mail:review', args=['all'])
        page = self.client.get(url)
        for token, query in [('', ''), ('forged', ''),
                             (page.context['review_token'], '?index=1')]:
            with self.subTest(token=token, query=query):
                response = self.client.post(url + query, self.draft_data(
                    subject='Wrong target', review_token=token))
                self.assertEqual(response.status_code, 409)
        self.assertFalse(Message.objects.filter(subject='Wrong target').exists())

    def test_lost_review_session_reports_unsaved_edits(self):
        self.login()
        url = reverse('mail:review', args=['all'])
        page = self.client.get(url)
        session = self.client.session
        session.pop('review_all')
        session.save()
        response = self.client.post(url, self.draft_data(
            subject='This was never saved', review_token=page.context['review_token']))
        self.assertEqual(response.status_code, 409)
        self.assertContains(response, 'not saved', status_code=409)
        self.own.refresh_from_db()
        self.assertEqual(self.own.subject, 'Own assistant draft')

    def test_deleted_review_draft_reports_unsaved_edits(self):
        self.login()
        url = reverse('mail:review', args=['all'])
        page = self.client.get(url)
        data = self.draft_data(page.context['message_obj'],
                               review_token=page.context['review_token'])
        page.context['message_obj'].delete()
        response = self.client.post(url, data)
        self.assertEqual(response.status_code, 409)
        self.assertContains(response, 'not saved', status_code=409)

    def test_unicode_send_confirmation_is_rejected_without_sending(self):
        self.login()
        url = reverse('mail:send', args=[self.own.pk])
        self.client.get(url)
        with patch('mail.views.send_message') as deliver:
            response = self.client.post(url, {'batch_token': 'invalid-\u00e9'})
        self.assertEqual(response.status_code, 302)
        deliver.assert_not_called()

    def test_invalid_send_token_does_not_consume_newer_confirmation(self):
        self.login()
        url = reverse('mail:send', args=[self.own.pk])
        old_tab = self.client.get(url)
        current_tab = self.client.get(url)
        self.client.post(url, {'batch_token': old_tab.context['batch_token']})
        self.client.post(url, {'batch_token': current_tab.context['batch_token']})
        self.own.refresh_from_db()
        self.assertEqual(self.own.status, 'sent')

    def test_unicode_merge_token_is_rejected_without_creating_drafts(self):
        self.login(self.assistant)
        url = reverse('mail:merge')
        self.client.post(url, {
            'action': 'preview',
            'csv_file': SimpleUploadedFile('input.csv', b'email\none@example.test\n'),
            'subject': 'Hello', 'body': 'Welcome', 'send_date': timezone.localdate(), 'send_time': '00:00',
        })
        before = Message.objects.count()
        response = self.client.post(url, {'action': 'commit', 'merge_token': 'invalid-\u00e9'})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(Message.objects.count(), before)

    def test_empty_signature_post_clears_signature_and_invalidates_approval(self):
        self.workspace.signature = 'Remove this signature'
        self.workspace.save(update_fields=['signature'])
        self.login()
        url = reverse('mail:send', args=[self.own.pk])
        approval = self.client.get(url)
        response = self.client.post(reverse('mail:signature'), {})
        self.assertEqual(response.status_code, 302)
        self.workspace.refresh_from_db()
        self.assertEqual(self.workspace.signature, '')
        self.own.refresh_from_db()
        self.assertEqual(self.own.version, 2)
        with patch('mail.views.send_message') as deliver:
            self.client.post(url, {'batch_token': approval.context['batch_token']})
        deliver.assert_not_called()

    def test_empty_required_forms_report_validation_errors(self):
        self.login()
        targets = [('compose', []), ('team', []), ('merge', []),
                   ('assistant_password', [self.assistant.membership.pk])]
        for name, args in targets:
            with self.subTest(name=name):
                response = self.client.post(reverse('mail:' + name, args=args), {})
                self.assertEqual(response.status_code, 200)
                self.assertTrue(response.context['form'].is_bound)
                self.assertTrue(response.context['form'].errors)

    def test_attachment_storage_failure_reports_error_without_saving_draft(self):
        self.login(self.assistant)
        with patch('django.core.files.storage.FileSystemStorage.save',
                   side_effect=OSError('No storage space')):
            response = self.client.post(reverse('mail:edit', args=[self.own.pk]),
                                        self.draft_data(subject='Should not persist',
                                            attachment_1=SimpleUploadedFile('new.txt', b'new')))
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context['form'].non_field_errors())
        self.own.refresh_from_db()
        self.assertEqual(self.own.subject, 'Own assistant draft')
        self.assertEqual(self.own.attachments.count(), 0)

    def test_failed_old_attachment_cleanup_does_not_delete_new_attachment(self):
        old = Attachment.objects.create(message=self.own,
                                        file=SimpleUploadedFile('old.txt', b'old'),
                                        original_name='old.txt', size=3)
        self.login(self.assistant)
        with patch('django.core.files.storage.FileSystemStorage.delete',
                   side_effect=OSError('File temporarily locked')):
            with self.captureOnCommitCallbacks(execute=True):
                response = self.client.post(reverse('mail:edit', args=[self.own.pk]),
                                            self.draft_data(subject='Replacement saved',
                                                remove_attachments=[old.pk],
                                                attachment_1=SimpleUploadedFile('new.txt', b'new')))
        self.assertEqual(response.status_code, 302)
        self.own.refresh_from_db()
        self.assertEqual(self.own.subject, 'Replacement saved')
        replacement = self.own.attachments.get()
        self.assertTrue(Path(replacement.file.path).exists())


class AttachmentCommitAuditTests(TransactionTestCase):
    def test_actual_commit_cleanup_failure_keeps_new_attachment_intact(self):
        # TestCase holds an outer rollback transaction, so use a real commit to
        # ensure post-commit cleanup cannot enter save_draft's rollback cleanup.
        with tempfile.TemporaryDirectory(prefix='mailsend-commit-audit-') as folder:
            with override_settings(MEDIA_ROOT=folder, MAILSEND_DELIVERY_MODE='demo'):
                owner = get_user_model().objects.create_user('commit-owner', 'owner@example.test')
                workspace = Workspace.objects.create(name='Commit audit', executive=owner)
                Membership.objects.create(user=owner, workspace=workspace, role='executive')
                draft = Message.objects.create(workspace=workspace, created_by=owner,
                                               to='recipient@example.test', subject='Before', body='Body')
                old = Attachment.objects.create(message=draft, original_name='old.txt', size=3,
                                                file=SimpleUploadedFile('old.txt', b'old'))
                original_delete = FileSystemStorage.delete

                def delete_with_old_file_locked(storage, name):
                    if name == old.file.name:
                        raise OSError('Old attachment is temporarily locked')
                    return original_delete(storage, name)

                self.client.force_login(owner)
                with patch.object(FileSystemStorage, 'delete', autospec=True,
                                  side_effect=delete_with_old_file_locked):
                    with self.assertLogs('django.db.backends.base', level='ERROR'):
                        response = self.client.post(reverse('mail:edit', args=[draft.pk]), {
                            'to': draft.to, 'cc': '', 'bcc': '', 'subject': 'After',
                            'body': draft.body, 'version': draft.version, 'send_date': draft.send_date,
                            'send_time': '00:00',
                            'remove_attachments': [old.pk],
                            'attachment_1': SimpleUploadedFile('new.txt', b'new'),
                        })
                self.assertEqual(response.status_code, 302)
                draft.refresh_from_db()
                self.assertEqual(draft.subject, 'After')
                replacement = draft.attachments.get()
                self.assertEqual(Path(replacement.file.path).read_bytes(), b'new')
