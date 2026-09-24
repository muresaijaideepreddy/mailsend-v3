from django.urls import reverse
from mail.models import Message, DocumentImport, AuditEvent
from mail.tests.test_security import WorkspaceTestCase


class ImportReviewTests(WorkspaceTestCase):
    def setUp(self):
        self.batch = DocumentImport.objects.create(token='review-tests', workspace=self.workspace,user=self.executive,filename='test.pdf',status='complete')
        self.draft = Message.objects.create(workspace=self.workspace,created_by=self.executive,imported_from='test.pdf',import_batch=self.batch,to='',subject='First',body='Hi John Smith,\nTest',contact_match_notes='John Smith <john@example.test> (100% spelling similarity)')
        self.peer = Message.objects.create(workspace=self.workspace,created_by=self.executive,imported_from='test.pdf',import_batch=self.batch,to='',subject='Second',body='Hi John Smith,\nSecond')

    def test_worker_review_and_save_without_send(self):
        self.login(self.assistant)
        response=self.client.get(reverse('mail:import_review'))
        self.assertContains(response,'0 of 2 drafts ready')
        self.assertContains(response,'john@example.test')
        data=self.draft_data(self.draft,to='john@example.test');data['draft_id']=self.draft.pk
        self.assertEqual(self.client.post(reverse('mail:import_review'),data).status_code,302)
        self.draft.refresh_from_db();self.assertEqual(self.draft.version,2);self.assertEqual(self.draft.status,'draft')
        self.assertContains(self.client.get(reverse('mail:import_review')),'1 of 2 drafts ready')

    def test_group_apply_and_audit(self):
        self.login(self.assistant)
        response=self.client.get(reverse('mail:import_review'))
        row=next(r for r in response.context['rows'] if r['draft'].pk==self.draft.pk)
        data=self.draft_data(self.draft,to='john@example.test');data.update(draft_id=self.draft.pk,apply_same='on',same_token=row['token'])
        self.assertEqual(self.client.post(reverse('mail:import_review'),data).status_code,302)
        self.peer.refresh_from_db();self.assertEqual(self.peer.to,'john@example.test')
        self.assertTrue(AuditEvent.objects.filter(message=self.peer,action='draft.recipient_applied').exists())

    def test_stale_peer_rolls_back_all(self):
        self.login()
        response=self.client.get(reverse('mail:import_review'))
        row=next(r for r in response.context['rows'] if r['draft'].pk==self.draft.pk)
        Message.objects.filter(pk=self.peer.pk).update(version=2)
        data=self.draft_data(self.draft,to='john@example.test');data.update(draft_id=self.draft.pk,apply_same='on',same_token=row['token'])
        self.assertEqual(self.client.post(reverse('mail:import_review'),data).status_code,200)
        self.draft.refresh_from_db();self.assertEqual(self.draft.to,'')

    def test_other_workspace_and_sent_drafts_excluded(self):
        self.login(self.outsider)
        self.assertNotContains(self.client.get(reverse('mail:import_review')),'First')
        data=self.draft_data(self.draft,to='john@example.test');data['draft_id']=self.draft.pk
        self.assertEqual(self.client.post(reverse('mail:import_review'),data).status_code,404)

    def test_ready_filter_and_no_group_for_legacy_drafts(self):
        self.login()
        self.assertNotContains(self.client.get(reverse('mail:import_review')+'?filter=ready'),'First')
        Message.objects.filter(pk=self.draft.pk).update(import_batch=None)
        row=next(r for r in self.client.get(reverse('mail:import_review')).context['rows'] if r['draft'].pk==self.draft.pk)
        self.assertEqual(row['peers'],[])
