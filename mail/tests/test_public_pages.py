"""Public information stays accessible without opening workspace data."""

from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from mail.models import AuditEvent, GoogleCredential, Membership, Message, Workspace


class PublicInformationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.owner = get_user_model().objects.create_user(
            'private-public-page-test-user', email='private-account@example.com')
        cls.workspace = Workspace.objects.create(
            executive=cls.owner, name='Confidential workspace marker')
        Membership.objects.create(user=cls.owner, workspace=cls.workspace, role='executive')
        cls.message = Message.objects.create(
            workspace=cls.workspace, created_by=cls.owner,
            to='private-recipient@example.com', bcc='private-bcc@example.com',
            subject='Confidential subject marker', body='Confidential body marker', status='sent')
        GoogleCredential.objects.create(user=cls.owner, encrypted_data='private-ciphertext-marker')
        AuditEvent.objects.create(workspace=cls.workspace, actor=cls.owner,
                                  action='private-audit-marker')

    def test_anonymous_pages_render_without_workspace_queries_or_provider_calls(self):
        sensitive = (
            self.owner.username, self.owner.email, self.workspace.name,
            self.message.subject, self.message.body, self.message.to, self.message.bcc,
            'private-ciphertext-marker', 'private-audit-marker',
        )
        with patch('requests.sessions.Session.request') as provider_request:
            for name in ('about', 'privacy', 'terms'):
                with self.subTest(page=name):
                    with self.assertNumQueries(0):
                        response = self.client.get(reverse(f'mail:{name}'), {
                            'workspace': self.workspace.pk, 'message': self.message.pk,
                        })
                    self.assertEqual(response.status_code, 200)
                    self.assertContains(response, 'MailSend')
                    for value in sensitive:
                        self.assertNotContains(response, value)
            provider_request.assert_not_called()

    def test_public_information_is_linked_from_login_and_each_page(self):
        for name in ('login', 'about', 'privacy', 'terms'):
            with self.subTest(page=name):
                response = self.client.get(reverse(f'mail:{name}'))
                for destination in ('about', 'privacy', 'terms'):
                    self.assertContains(response, f'href="{reverse(f"mail:{destination}")}"')
        self.assertContains(self.client.get(reverse('mail:about')),
                            f'href="{reverse("mail:login")}"')
        self.assertContains(self.client.get(reverse('mail:privacy')),
                            'href="https://developers.google.com/terms/api-services-user-data-policy"')

    def test_public_pages_do_not_accept_mutating_requests(self):
        for name in ('about', 'privacy', 'terms'):
            with self.subTest(page=name):
                with self.assertNumQueries(0):
                    response = self.client.post(reverse(f'mail:{name}'), {'delete': self.workspace.pk})
                self.assertEqual(response.status_code, 405)

    def test_dashboard_and_mail_remain_protected(self):
        for url in (reverse('mail:dashboard'), reverse('mail:detail', args=[self.message.pk]),
                    reverse('mail:sent'), reverse('mail:team')):
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertRedirects(response, f'{reverse("mail:login")}?next={url}',
                                     fetch_redirect_response=False)
