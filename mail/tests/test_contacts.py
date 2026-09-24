import json
from unittest.mock import patch, MagicMock
from urllib.parse import urlparse, parse_qs

from django.core import signing
from django.test import SimpleTestCase, override_settings
from django.urls import reverse

from mail.contacts import contact_matches, fetch_contacts, suggested_name, enrich_import_recipients
from mail.contact_views import SALT
from mail.google_api import CONTACTS_SCOPE, SEND_SCOPE
from mail.models import Message, AuditEvent
from mail.services import DeliveryRejected
from mail.tests.test_security import WorkspaceTestCase

CONTACTS = [dict(name='Jaideep Reddy', email='jai@example.test'), dict(name='Chao Wang', email='chao@example.test'),
            dict(name='John Smith', email='john1@example.test'), dict(name='John Smith', email='john2@example.test'),
            dict(name='José García', email='jose@example.test')]


class MatchingTests(SimpleTestCase):
    @patch('mail.contacts.fetch_contacts', return_value=CONTACTS)
    def test_unresolved_headers_never_choose_a_different_greeting_contact(self, fetch):
        for notes in ('TO: Alex <alex@invalid>', 'TO: alex@invalid',
                      'TO: Chao Wang <chao@invalid>', 'TO: Alex\nTO: Chao Wang',
                      'TO: Jaideep Reddy', ' to: alex@invalid'):
            with self.subTest(notes=notes):
                row = dict(to='', body='Hi Chao Wang,\nKeep the original words.', imported_recipient_notes=notes)
                enrich_import_recipients(None, [row])
                self.assertEqual(row['to'], '')
                self.assertEqual(row['body'], 'Hi Chao Wang,\nKeep the original words.')

    @patch('mail.contacts.fetch_contacts', return_value=CONTACTS)
    def test_consistent_header_and_greeting_still_match(self, fetch):
        for notes in ('TO: Chao Wang', 'TO: Dr. Wang Chao', 'TO: Chao Wang\nTO: Chao Wang'):
            with self.subTest(notes=notes):
                row = dict(to='', body='Hi Chao Wang,', imported_recipient_notes=notes)
                enrich_import_recipients(None, [row])
                self.assertEqual(row['to'], 'chao@example.test')

    @patch('mail.contacts.fetch_contacts', return_value=CONTACTS)
    def test_import_unique_exact_fill_and_other_cases_require_review(self, fetch):
        rows = [dict(to='', body='Hi '+name+',\nOriginal body') for name in ('Chao Wang', 'Chao', 'Jaidep Reddy', 'John Smith', 'Unknown Person', 'Jose Garcia')]
        enrich_import_recipients(object(), rows)
        self.assertEqual([row['to'] for row in rows], ['chao@example.test','','','','','jose@example.test'])
        self.assertEqual(fetch.call_count, 1)
        self.assertEqual(rows[2]['body'], 'Hi Jaidep Reddy,\nOriginal body')
        self.assertIn('suggestions', rows[2]['contact_match_notes'])

    @patch('mail.contacts.fetch_contacts')
    def test_existing_address_never_overwritten_or_looked_up(self, fetch):
        row = dict(to='existing@example.test', body='Hi Chao Wang,')
        self.assertEqual(enrich_import_recipients(object(), [row])[0]['to'], 'existing@example.test')
        fetch.assert_not_called()

    @patch('mail.contacts.fetch_contacts', side_effect=DeliveryRejected('private provider error'))
    def test_contact_failure_does_not_block_import_or_leak_error(self, fetch):
        row = dict(to='', body='Hi Chao Wang,')
        enrich_import_recipients(object(), [row])
        self.assertEqual(row['to'], '')
        self.assertIn('unavailable', row['contact_match_notes'])
        self.assertNotIn('private provider', row['contact_match_notes'])

    @patch('mail.contacts.fetch_contacts', return_value=CONTACTS)
    def test_invalid_cc_keeps_to_blank_for_review(self, fetch):
        row = dict(to='', body='Hi Chao Wang,', imported_recipient_notes='CC: unresolved name')
        enrich_import_recipients(object(), [row])
        self.assertEqual(row['to'], '')

    def test_exact_case_accents_titles_and_reordered_names(self):
        for query, email in [('JAIDEEP REDDY', 'jai@example.test'), ('Reddy Jaideep', 'jai@example.test'),
                             ('Dr. Chao Wang', 'chao@example.test'), ('Jose Garcia', 'jose@example.test')]:
            with self.subTest(query=query):
                rows = contact_matches(query, CONTACTS)
                self.assertEqual(rows[0]['email'], email)
                self.assertEqual(rows[0]['score'], 100)

    def test_fuzzy_typo_is_reviewable(self):
        for name in ('Jaidep Reddy', 'Jaidep'):
            rows = contact_matches(name, CONTACTS)
            self.assertEqual(rows[0]['email'], 'jai@example.test')
            self.assertIn('review', rows[0]['reason'])

    def test_duplicate_names_and_multiple_addresses_are_not_collapsed(self):
        self.assertEqual(len(contact_matches('John Smith', CONTACTS)), 2)

    def test_duplicate_same_email_deduplicated(self):
        self.assertEqual(len(contact_matches('Chao', CONTACTS + [CONTACTS[1]])), 1)

    def test_partial_name_needs_review(self):
        self.assertIn('review', contact_matches('Chao', CONTACTS)[0]['reason'])

    def test_unknown_short_and_unrelated_names(self):
        for name in ('X', '', 'Team', 'No Such Person', 'Qz'):
            self.assertEqual(contact_matches(name, CONTACTS), [])

    def test_name_comes_from_recipient_or_greeting_not_body_mentions(self):
        draft = Message(body='Hi Chao,\nPlease ask John to join.', imported_recipient_notes='')
        self.assertEqual(suggested_name(draft), 'Chao')
        draft.imported_recipient_notes = 'TO: Brent'
        self.assertEqual(suggested_name(draft), 'Brent')

    @patch('mail.contacts._access_token', return_value='synthetic')
    @patch('mail.contacts.requests.get')
    def test_google_pagination_and_invalid_contact_email(self, get, token):
        def response(data):
            item = MagicMock(); item.__enter__.return_value = item; item.status_code = 200; item.json.return_value = data
            return item
        get.side_effect = [response({'connections':[{'names':[{'displayName':'Chao Wang'}], 'emailAddresses':[{'value':'chao@example.test'}, {'value':'invalid'}]}], 'nextPageToken':'page2'}), response({'connections':[]})]
        self.assertEqual(fetch_contacts(object()), [CONTACTS[1]])
        self.assertEqual(get.call_count, 2)
        self.assertEqual(get.call_args.kwargs['params']['pageToken'], 'page2')
        self.assertEqual(token.call_args.kwargs['required_scopes'], (CONTACTS_SCOPE,))

    @patch('mail.contacts._access_token', return_value='synthetic')
    @patch('mail.contacts.requests.get')
    def test_google_error_is_safe(self, get, token):
        get.return_value.__enter__.return_value.status_code = 403
        with self.assertRaises(DeliveryRejected):
            fetch_contacts(object())


class ContactWorkflowTests(WorkspaceTestCase):
    def draft(self):
        return Message.objects.create(workspace=self.workspace, created_by=self.executive, imported_from='synthetic.docx', subject='Test', body='Hi Chao,\nTest', to='')

    @patch('mail.contact_views.fetch_contacts', return_value=CONTACTS)
    def test_search_is_read_only_and_selection_is_audited(self, fetch):
        draft = self.draft(); self.login()
        url = reverse('mail:contact_matches', args=[draft.pk])
        response = self.client.post(url, {'name':'Chao', 'field':'to'})
        self.assertContains(response, 'chao@example.test')
        draft.refresh_from_db(); self.assertEqual(draft.to, '')
        choice = response.context['results'][0]['choice']
        self.assertEqual(self.client.post(url, {'choice':choice}).status_code, 302)
        draft.refresh_from_db(); self.assertEqual(draft.to, 'chao@example.test'); self.assertEqual(draft.version, 2)
        self.assertTrue(AuditEvent.objects.filter(message=draft, action='draft.contact_selected').exists())
        self.assertContains(self.client.post(url, {'choice':choice}), 'draft changed')

    def test_worker_and_other_workspace_cannot_read_contacts(self):
        draft = self.draft(); url = reverse('mail:contact_matches', args=[draft.pk])
        for user in (self.assistant, self.outsider):
            self.login(user)
            with patch('mail.contact_views.fetch_contacts') as fetch:
                self.assertIn(self.client.post(url, {'name':'Chao'}).status_code, (403,404))
                fetch.assert_not_called()

    def test_tampered_choice_does_not_change_draft(self):
        draft = self.draft(); self.login()
        self.client.post(reverse('mail:contact_matches', args=[draft.pk]), {'choice':'tampered'})
        draft.refresh_from_db(); self.assertEqual(draft.to, '')

    @override_settings(GOOGLE_CLIENT_ID='synthetic', GOOGLE_CLIENT_SECRET='synthetic', GOOGLE_REDIRECT_URI='http://localhost/callback/')
    @patch('mail.oauth_views.oauth_configured', return_value=True)
    def test_contacts_scope_only_requested_explicitly_by_executive(self, configured):
        self.login()
        response = self.client.get(reverse('mail:google_contacts'))
        scopes = parse_qs(urlparse(response.url).query)['scope'][0].split()
        self.assertIn(CONTACTS_SCOPE, scopes); self.assertIn(SEND_SCOPE, scopes)
        self.login(self.assistant)
        self.assertEqual(self.client.get(reverse('mail:google_contacts')).status_code, 403)
