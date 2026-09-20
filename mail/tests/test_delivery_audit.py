"""Adversarial regressions discovered during the independent delivery audit."""

import io
import time
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import close_old_connections
from django.test import TestCase, TransactionTestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from mail.models import AuditEvent, Membership, Message, Workspace
from mail.google_api import SEND_SCOPE, TOKEN_URL, decrypt_credentials, send_gmail, token_values
from mail.services import DeliveryRejected, bcc_from_csv, build_email, merge_preview, parse_addresses, send_message
from mail.tests.test_google import GoogleTestCase


MALFORMED_ADDRESSES = (":;[", "a@example.com " + "(" * 1100 + ")" * 1100)


class AddressParserAuditTests(TestCase):
    def setUp(self):
        self.executive = get_user_model().objects.create_user("parser-audit", email="audit@example.test")
        self.workspace = Workspace.objects.create(name="Parser audit", executive=self.executive)
        Membership.objects.create(user=self.executive, workspace=self.workspace, role="executive")

    def test_malformed_group_and_deep_comments_return_validation_errors(self):
        for value in MALFORMED_ADDRESSES:
            with self.subTest(value=value[:40]), self.assertRaises(ValidationError):
                parse_addresses(value, required=True)

    def test_compose_renders_errors_instead_of_crashing_for_malformed_addresses(self):
        self.client.force_login(self.executive)
        for value in MALFORMED_ADDRESSES:
            with self.subTest(value=value[:40]):
                response = self.client.post(reverse("mail:compose"), {
                    "to": value, "cc": "", "bcc": "", "subject": "Malformed recipient",
                    "body": "Must never become a draft", "send_date": timezone.localdate(), "version": 1,
                    "send_time": "00:00",
                })
                self.assertEqual(response.status_code, 200)
                self.assertIn("to", response.context["form"].errors)
        self.assertFalse(Message.objects.exists())

    def test_csv_workflows_reject_parser_edge_cases_without_partial_results(self):
        for value in MALFORMED_ADDRESSES:
            content = ("email\n" + value + "\n").encode()
            with self.subTest(value=value[:40]):
                with self.assertRaises(ValidationError):
                    bcc_from_csv(io.BytesIO(content))
                with self.assertRaises(ValidationError):
                    merge_preview(io.BytesIO(content), "Valid subject", "Valid body")


@override_settings(MAILSEND_DELIVERY_MODE="demo")
class ConcurrentSendAuditTests(TransactionTestCase):
    def test_simultaneous_sends_accept_one_claim_without_server_errors(self):
        user = get_user_model().objects.create_user("send-audit", email="audit@example.test")
        workspace = Workspace.objects.create(name="Concurrent send audit", executive=user)
        Membership.objects.create(user=user, workspace=workspace, role="executive")
        message = Message.objects.create(workspace=workspace, created_by=user, to="recipient@example.test",
                                         subject="Concurrent approval", body="One delivery only")
        barrier = Barrier(2, timeout=10)

        def ready_to_claim(item):
            outgoing = build_email(item)
            barrier.wait()
            return outgoing

        def send(_):
            close_old_connections()
            try:
                try:
                    return send_message(user, message.pk, expected_version=1).status
                except ValidationError:
                    return "conflict"
            finally:
                close_old_connections()

        with patch("mail.services.build_email", side_effect=ready_to_claim), patch("mail.services._deliver_demo", return_value="demo-concurrency-audit") as deliver:
            with ThreadPoolExecutor(max_workers=2) as executor:
                results = list(executor.map(send, range(2)))
        self.assertEqual(sorted(results), ["conflict", "sent"])
        deliver.assert_called_once()
        message.refresh_from_db()
        self.assertEqual(message.status, "sent")
        self.assertEqual(AuditEvent.objects.filter(message=message, action="send_started").count(), 1)


class GoogleFailureAuditTests(GoogleTestCase):
    def outgoing(self):
        from email.message import EmailMessage

        result = EmailMessage()
        result["From"] = self.executive.email
        result["To"] = "recipient@example.test"
        result["Subject"] = "OAuth failure audit"
        result.set_content("A mocked provider must never send this message.")
        return result

    def test_malformed_token_responses_are_rejected(self):
        base = {"access_token": "test-access", "expires_in": 3600, "scope": SEND_SCOPE}
        changes = (
            {"access_token": "bad\r\nheader"}, {"access_token": ""}, {"token_type": "Basic"},
            {"expires_in": 0}, {"expires_in": -1}, {"expires_in": float("nan")},
            {"expires_in": float("inf")}, {"scope": "openid email"},
        )
        for change in changes:
            with self.subTest(change=change), self.assertRaises(ValueError):
                token_values({**base, **change})

    def test_provider_rejecting_refresh_never_receives_a_gmail_send(self):
        self.connection(expires_at=time.time() - 1)
        with patch("mail.google_api.requests.post", return_value=self.response(status=400)) as post:
            with self.assertRaises(DeliveryRejected):
                send_gmail(self.executive, self.outgoing())
        post.assert_called_once()
        self.assertEqual(post.call_args.args[0], TOKEN_URL)

    def test_corrupt_credentials_fail_before_any_network_request(self):
        record = self.connection()
        record.encrypted_data = "damaged-token-ciphertext"
        record.save(update_fields=["encrypted_data"])
        with patch("mail.google_api.requests.post") as post:
            with self.assertRaises(DeliveryRejected):
                send_gmail(self.executive, self.outgoing())
        post.assert_not_called()

    def test_disconnect_during_refresh_cannot_restore_tokens_or_send(self):
        record = self.connection(expires_at=time.time() - 1)
        self.client.force_login(self.executive)

        def disconnect_during_refresh(*args, **kwargs):
            response = self.client.post(reverse("mail:google_disconnect"))
            self.assertEqual(response.status_code, 302)
            return self.response(data={"access_token": "new-access", "expires_in": 3600})

        with patch("mail.google_api.requests.post", side_effect=disconnect_during_refresh) as post:
            with self.assertRaises(DeliveryRejected):
                send_gmail(self.executive, self.outgoing())
        post.assert_called_once()
        self.assertEqual(post.call_args.args[0], TOKEN_URL)
        record.refresh_from_db()
        self.assertFalse(record.connected)
        self.assertNotIn("access_token", decrypt_credentials(record))
