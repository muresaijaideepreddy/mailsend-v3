import time
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse
from django.core.exceptions import ValidationError
from django.test import override_settings
from django.urls import reverse
from django.core.files.uploadedfile import SimpleUploadedFile
from mail.models import SenderAccount, Message, GoogleCredential
from mail.google_api import encrypt_credentials, subject_hash, send_gmail, SEND_SCOPE, decrypt_credentials
from mail.oauth_views import _connect_sender, SESSION_KEY
from mail.services import build_email, send_message, DeliveryRejected
from mail.forms import MessageForm
from mail.tests.test_google import GoogleTestCase


class SenderTests(GoogleTestCase):
    def setUp(self):
        self.sender = SenderAccount.objects.create(workspace=self.workspace, email='personal@example.test', subject_hash=subject_hash('secondary'),
            encrypted_data=encrypt_credentials(self.tokens(sub='secondary', email='personal@example.test', access_token='secondary-token')))

    def draft(self, **kw):
        values=dict(workspace=self.workspace,created_by=self.executive,sender=self.sender,to='recipient@example.test',subject='Hello',body='Original body')
        values.update(kw)
        return Message.objects.create(**values)

    def test_secondary_mime_and_signature(self):
        self.workspace.signature='Sai\nResearch Lab'; self.workspace.save()
        outgoing=build_email(self.draft())
        self.assertEqual(outgoing['From'],self.sender.email)
        self.assertEqual(outgoing.get_content().count('Research Lab'),1)

    @patch('mail.google_api.requests.post')
    def test_selected_token_used_without_primary_connection(self, post):
        post.return_value=self.response()
        send_gmail(self.executive,build_email(self.draft()),sender=self.sender)
        self.assertEqual(post.call_args.kwargs['headers']['Authorization'],'Bearer secondary-token')

    @patch('mail.google_api.requests.post')
    def test_other_workspace_and_disconnected_blocked(self, post):
        with self.assertRaises(DeliveryRejected):
            send_gmail(self.other,build_email(self.draft()),sender=self.sender)
        self.sender.connected=False;self.sender.save()
        with self.assertRaises(DeliveryRejected):
            send_gmail(self.executive,build_email(self.draft()),sender=self.sender)
        post.assert_not_called()

    @patch('mail.google_api.requests.post')
    def test_refresh_updates_only_selected_account(self, post):
        primary=self.connection()
        original=primary.encrypted_data
        self.sender.encrypted_data=encrypt_credentials(self.tokens(sub='secondary',email=self.sender.email,expires_at=0))
        self.sender.save()
        post.side_effect=[self.response(data={'access_token':'renewed','expires_in':3600,'scope':SEND_SCOPE+' https://www.googleapis.com/auth/contacts.readonly'}),self.response()]
        send_gmail(self.executive,build_email(self.draft()),sender=self.sender)
        primary.refresh_from_db(); self.assertEqual(primary.encrypted_data,original)
        self.assertEqual(post.call_args.kwargs['headers']['Authorization'],'Bearer renewed')

    def test_worker_selects_sender_and_version_changes(self):
        item=self.draft(sender=None)
        self.client.force_login(self.assistant)
        response=self.client.post(reverse('mail:edit',args=[item.pk]),dict(sender=self.sender.pk,to=item.to,subject=item.subject,body=item.body,send_date=item.send_date,version=item.version))
        self.assertEqual(response.status_code,302)
        item.refresh_from_db();self.assertEqual(item.sender_id,self.sender.pk);self.assertEqual(item.version,2)
        with self.assertRaises(ValidationError):send_message(self.executive,item.pk,expected_version=1)

    def test_foreign_sender_form_rejected(self):
        item=self.draft(workspace=self.other_workspace,created_by=self.other,sender=None)
        form=MessageForm(dict(sender=self.sender.pk,to=item.to,subject=item.subject,body=item.body,send_date=item.send_date,version=1),instance=item)
        self.assertFalse(form.is_valid());self.assertIn('sender',form.errors)

    def test_worker_cannot_manage_connections(self):
        self.client.force_login(self.assistant)
        self.assertEqual(self.client.get(reverse('mail:senders')).status_code,403)
        self.assertEqual(self.client.post(reverse('mail:google_sender')).status_code,403)

    def test_sender_flow_requires_post_and_no_login_hint(self):
        self.client.force_login(self.executive)
        self.assertEqual(self.client.get(reverse('mail:google_sender')).status_code,405)
        response=self.client.post(reverse('mail:google_sender'))
        query=parse_qs(urlparse(response.url).query)
        self.assertNotIn('login_hint',query)
        self.assertIn(SEND_SCOPE,query['scope'][0]);self.assertNotIn('contacts',query['scope'][0])
        self.assertEqual(self.client.session[SESSION_KEY]['mode'],'sender')

    def test_connect_secondary_keeps_login_and_primary_credential(self):
        from django.test import RequestFactory
        request=RequestFactory().get('/');request.user=self.executive
        primary=self.connection()
        data={'access_token':'new','refresh_token':'refresh','scope':SEND_SCOPE,'expires_in':3600}
        result=_connect_sender(request,{'sub':'secondary'},self.sender.email,data)
        self.assertEqual(result,self.executive)
        self.assertEqual(GoogleCredential.objects.get().pk,primary.pk)
        self.assertEqual(SenderAccount.objects.count(),1)
        with self.assertRaises(ValueError):_connect_sender(request,{'sub':'new'},'new@example.test',{'access_token':'new','scope':SEND_SCOPE})

    def test_disconnect_preserves_sender_choice_and_invalidates_approval(self):
        item=self.draft();self.client.force_login(self.executive)
        self.client.post(reverse('mail:senders'),{'sender':self.sender.pk,'action':'disconnect'})
        item.refresh_from_db();self.sender.refresh_from_db()
        self.assertEqual(item.sender_id,self.sender.pk);self.assertEqual(item.version,2)
        self.assertEqual(self.sender.encrypted_data,'')
        with self.assertRaises(ValidationError):item.validate_for_delivery()

    @patch('mail.google_api.send_gmail', return_value='receipt')
    @override_settings(MAILSEND_DELIVERY_MODE='gmail')
    def test_sent_sender_snapshot(self, send):
        item=send_message(self.executive,self.draft().pk)
        self.assertEqual(item.sent_from,self.sender.email)
        self.assertEqual(send.call_args.kwargs['sender'].pk,self.sender.pk)

    def test_merge_personalization_and_sender_preserved(self):
        self.client.force_login(self.assistant)
        csv=SimpleUploadedFile('people.csv',b'email,first_name\na@example.test,Alice\nb@example.test,Bob\n')
        response=self.client.post(reverse('mail:merge'),dict(sender=self.sender.pk,csv_file=csv,subject='Hi {{first_name}}',body='Dear {{first_name}},\nFull message.',send_date='2026-10-01'))
        self.assertEqual(response.status_code,200)
        saved=self.client.session['merge_preview']
        response=self.client.post(reverse('mail:merge'),{'action':'commit','merge_token':saved['token']})
        self.assertEqual(response.status_code,302)
        self.assertEqual(list(Message.objects.values_list('subject',flat=True)),['Hi Alice','Hi Bob'])
        self.assertEqual(Message.objects.filter(sender=self.sender,status='draft').count(),2)
        self.assertNotIn('{{',Message.objects.first().body)

    def test_merge_disconnect_after_preview_creates_nothing(self):
        self.client.force_login(self.executive)
        csv=SimpleUploadedFile('people.csv',b'email,name\na@example.test,Alice\n')
        self.client.post(reverse('mail:merge'),dict(sender=self.sender.pk,csv_file=csv,subject='Hello',body='Hello',send_date='2026-10-01'))
        saved=self.client.session['merge_preview'];self.sender.connected=False;self.sender.save()
        response=self.client.post(reverse('mail:merge'),{'action':'commit','merge_token':saved['token']})
        self.assertEqual(response.status_code,400);self.assertEqual(Message.objects.count(),0)

    def test_import_review_shows_and_preserves_sender(self):
        item=self.draft(imported_from='synthetic.docx')
        self.client.force_login(self.assistant)
        response=self.client.get(reverse('mail:import_review')+'?filter=all')
        self.assertContains(response,'name="sender"')
        self.assertContains(response,self.sender.email)
        response=self.client.post(reverse('mail:import_review'),dict(draft_id=item.pk,version=1,sender=self.sender.pk,to=item.to,subject=item.subject,body=item.body,send_date=item.send_date))
        self.assertEqual(response.status_code,302)
        item.refresh_from_db();self.assertEqual(item.sender_id,self.sender.pk)

    @patch('mail.google_api.requests.post')
    def test_mixed_primary_and_secondary_use_distinct_tokens(self, post):
        self.connection()
        post.return_value=self.response()
        send_gmail(self.executive,build_email(self.draft(sender=None)))
        send_gmail(self.executive,build_email(self.draft()),sender=self.sender)
        self.assertEqual([c.kwargs['headers']['Authorization'] for c in post.call_args_list],['Bearer test-access-token','Bearer secondary-token'])

    @patch('mail.google_api.requests.post')
    def test_forged_from_and_corrupted_identity_cannot_send(self, post):
        outgoing=build_email(self.draft(sender=None))
        with self.assertRaises(DeliveryRejected):send_gmail(self.executive,outgoing,sender=self.sender)
        self.sender.encrypted_data=encrypt_credentials(self.tokens(sub='wrong',email=self.sender.email))
        self.sender.save()
        with self.assertRaises(DeliveryRejected):send_gmail(self.executive,build_email(self.draft()),sender=self.sender)
        post.assert_not_called()

    @patch('mail.oauth_views.id_token.verify_oauth2_token')
    @patch('mail.oauth_views.requests.post')
    def test_callback_links_sender_without_switching_user(self, post, verify):
        self.client.force_login(self.executive)
        self.client.post(reverse('mail:google_sender'))
        flow=self.client.session[SESSION_KEY]
        post.return_value=self.response(data={'id_token':'verified-test','access_token':'new','refresh_token':'offline','scope':SEND_SCOPE})
        verify.return_value={'iss':'https://accounts.google.com','email_verified':True,'nonce':flow['nonce'],'sub':'third','email':'third@example.test'}
        result=self.client.get(reverse('mail:google_callback'),{'state':flow['state'],'code':'test-code'})
        self.assertRedirects(result,reverse('mail:senders'))
        self.assertEqual(int(self.client.session['_auth_user_id']),self.executive.pk)
        self.assertTrue(SenderAccount.objects.filter(email='third@example.test',workspace=self.workspace).exists())
