"""Actionable Gmail setup errors stay safe through persistence and HTTP views."""

from unittest.mock import patch

from django.test import override_settings
from django.urls import reverse

from mail.models import AuditEvent, Message
from mail.services import DeliveryRejected, send_message
from mail.tests.test_google import GoogleTestCase


RAW_PROVIDER_TEXT = "private-provider-value https://provider.invalid/private?token=private-token"
DISABLED_GUIDANCE = (
    "The Gmail API is disabled for this Google OAuth project. Enable the Gmail API "
    "in Google Cloud, then review and approve this message again."
)
GENERIC_GUIDANCE = "The provider did not accept this message. Check the Google connection and try again."


@override_settings(MAILSEND_DELIVERY_MODE="gmail")
class GmailConfigurationErrorTests(GoogleTestCase):
    def draft(self):
        return Message.objects.create(
            workspace=self.workspace, created_by=self.executive,
            to="recipient@example.test", subject="Synthetic Gmail failure test", body="No real email is sent.",
        )

    def disabled_payloads(self):
        return [
            {"error": {"code": 403, "message": RAW_PROVIDER_TEXT, "errors": [
                {"reason": "accessNotConfigured", "domain": "usageLimits", "message": RAW_PROVIDER_TEXT}
            ]}},
            {"error": {"code": 403, "message": RAW_PROVIDER_TEXT, "details": [
                {"@type": "type.googleapis.com/google.rpc.ErrorInfo", "reason": "SERVICE_DISABLED",
                 "domain": "googleapis.com", "metadata": {"service": "gmail.googleapis.com", "activationUrl": RAW_PROVIDER_TEXT}}
            ]}},
        ]

    def test_disabled_api_has_safe_saved_and_visible_guidance_then_explicit_retry(self):
        self.client.force_login(self.executive)
        for payload in self.disabled_payloads():
            with self.subTest(payload_format=list(payload["error"])[-1]):
                draft = self.draft()
                send_url = reverse("mail:send", args=[draft.pk])
                confirmation = self.client.get(send_url)
                with patch("mail.google_api._access_token", return_value="synthetic-token"), \
                        patch("mail.google_api.requests.post", return_value=self.response(status=403, data=payload)) as post:
                    response = self.client.post(send_url, {"batch_token": confirmation.context["batch_token"]}, follow=True)
                post.assert_called_once()
                self.assertContains(response, DISABLED_GUIDANCE)
                self.assertNotContains(response, "private-provider-value")
                draft.refresh_from_db()
                self.assertEqual(draft.status, "failed")
                self.assertEqual(draft.last_error, DISABLED_GUIDANCE)
                self.assertIsNone(draft.sent_at)
                self.assertEqual(draft.provider_id, "")
                event = AuditEvent.objects.get(message=draft, action="delivery_failed")
                self.assertEqual(event.detail, DISABLED_GUIDANCE)
                detail = self.client.get(reverse("mail:detail", args=[draft.pk]))
                self.assertContains(detail, DISABLED_GUIDANCE)
                self.assertNotContains(detail, "private-token")

                # Enabling the API alone never resends; a fresh approval is required.
                confirmation = self.client.get(send_url)
                with patch("mail.google_api._access_token", return_value="synthetic-token"), \
                        patch("mail.google_api.requests.post", return_value=self.response()) as post:
                    self.client.post(send_url, {"batch_token": confirmation.context["batch_token"]})
                post.assert_called_once()
                draft.refresh_from_db()
                self.assertEqual(draft.status, "sent")
                self.assertEqual(draft.last_error, "")

    def test_malformed_403_json_remains_definitive_generic_rejection(self):
        response = self.response(status=403)
        response.json.side_effect = ValueError(RAW_PROVIDER_TEXT)
        with patch("mail.google_api._access_token", return_value="synthetic-token"), \
                patch("mail.google_api.requests.post", return_value=response) as post:
            result = send_message(self.executive, self.draft().pk)
        post.assert_called_once()
        self.assertEqual(result.status, "failed")
        self.assertEqual(result.last_error, GENERIC_GUIDANCE)

    def test_unrecognized_error_shapes_or_arbitrary_provider_text_are_not_classified(self):
        payloads = [
            [], {"error": "SERVICE_DISABLED " + RAW_PROVIDER_TEXT},
            {"error": {"code": 403, "message": "accessNotConfigured " + RAW_PROVIDER_TEXT}},
            {"error": {"code": 403, "errors": {"reason": "accessNotConfigured", "domain": "usageLimits"}}},
            {"error": {"code": "403", "errors": [{"reason": "accessNotConfigured", "domain": "usageLimits"}]}},
            {"error": {"code": 403, "errors": [None, [], "accessNotConfigured"], "details": [None]}},
            {"error": {"code": 403, "details": [
                {"@type": "type.googleapis.com/google.rpc.ErrorInfo", "reason": "SERVICE_DISABLED",
                 "domain": "googleapis.com", "metadata": {"service": "unrelated.googleapis.com"}}
            ]}},
        ]
        for payload in payloads:
            with self.subTest(payload=payload), \
                    patch("mail.google_api._access_token", return_value="synthetic-token"), \
                    patch("mail.google_api.requests.post", return_value=self.response(status=403, data=payload)) as post:
                result = send_message(self.executive, self.draft().pk)
                post.assert_called_once()
                self.assertEqual(result.status, "failed")
                self.assertEqual(result.last_error, GENERIC_GUIDANCE)

    def test_unknown_rejection_codes_never_persist_exception_text(self):
        with patch("mail.google_api.send_gmail", side_effect=DeliveryRejected(RAW_PROVIDER_TEXT, code=RAW_PROVIDER_TEXT)):
            result = send_message(self.executive, self.draft().pk)
        self.assertEqual(result.status, "failed")
        self.assertEqual(result.last_error, GENERIC_GUIDANCE)
        self.assertEqual(AuditEvent.objects.get(message=result, action="delivery_failed").detail, GENERIC_GUIDANCE)
