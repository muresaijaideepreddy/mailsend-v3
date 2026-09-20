"""Independent requests racing to commit the same merge preview."""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.db import close_old_connections
from django.test import Client, TransactionTestCase
from django.urls import reverse
from django.utils import timezone

from mail.models import Membership, MergeReceipt, Message, Workspace


class ConcurrentMergeTests(TransactionTestCase):
    def test_concurrent_duplicate_commit_creates_one_atomic_batch(self):
        user = get_user_model().objects.create_user("concurrent-executive", email="concurrent@example.test")
        workspace = Workspace.objects.create(name="Concurrency QA", executive=user)
        Membership.objects.create(user=user, workspace=workspace, role="executive")
        token = "concurrent-preview-token"
        preview = {
            "token": token, "at": timezone.now().timestamp(), "user": user.pk,
            "send_date": timezone.localdate().isoformat(),
            "send_time": "00:00",
            "rows": [
                {"to": "one@example.test", "cc": "", "bcc": "", "subject": "Concurrent one", "body": "One"},
                {"to": "two@example.test", "cc": "", "bcc": "", "subject": "Concurrent two", "body": "Two"},
            ],
        }
        clients = [Client(), Client()]
        for client in clients:
            client.force_login(user)
            session = client.session
            session["merge_preview"] = preview
            session.save()
        barrier = Barrier(2, timeout=10)
        create_receipt = MergeReceipt.objects.create

        def simultaneous_insert(*args, **kwargs):
            barrier.wait()
            return create_receipt(*args, **kwargs)

        def commit(client):
            close_old_connections()
            try:
                return client.post(reverse("mail:merge"), {"action": "commit", "merge_token": token}).status_code
            finally:
                close_old_connections()

        with patch("mail.models.MergeReceipt.objects.create", side_effect=simultaneous_insert):
            with ThreadPoolExecutor(max_workers=2) as executor:
                statuses = list(executor.map(commit, clients))
        # Disk SQLite normally waits and returns the unique-receipt collision;
        # shared-memory SQLite may immediately report a competing writer.
        self.assertIn(sorted(statuses), ([302, 302], [302, 409]))
        for client, status in zip(clients, statuses):
            if status == 409:
                self.assertEqual(client.post(reverse("mail:merge"), {"action": "commit", "merge_token": token}).status_code, 302)
        self.assertEqual(MergeReceipt.objects.filter(token=token).count(), 1)
        self.assertEqual(Message.objects.filter(workspace=workspace).count(), 2)
        self.assertEqual(set(Message.objects.values_list("subject", flat=True)), {"Concurrent one", "Concurrent two"})
