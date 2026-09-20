"""Tenant-owned mail drafts and an explicit, auditable delivery lifecycle."""

import uuid
import re
from pathlib import Path

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone


def attachment_path(instance, filename):
    # Never use supplied names as a filesystem path (including Windows paths).
    suffix = Path(filename.replace("\\", "/")).suffix[:16]
    if not re.fullmatch(r"\.[A-Za-z0-9]+", suffix):
        suffix = ""
    return f"attachments/{instance.message.workspace_id}/{uuid.uuid4().hex}{suffix}"


class Workspace(models.Model):
    name = models.CharField(max_length=160)
    executive = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="owned_workspace"
    )
    signature = models.TextField(blank=True)

    def __str__(self):
        return self.name


class Membership(models.Model):
    class Role(models.TextChoices):
        EXECUTIVE = "executive", "Executive"
        ASSISTANT = "assistant", "Assistant"

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="membership"
    )
    workspace = models.ForeignKey(Workspace, on_delete=models.CASCADE, related_name="memberships")
    role = models.CharField(max_length=16, choices=Role.choices)

    class Meta:
        constraints = [
            models.CheckConstraint(condition=models.Q(role__in=["executive", "assistant"]), name="valid_membership_role"),
            models.UniqueConstraint(fields=["workspace"], condition=models.Q(role="executive"), name="one_executive_membership"),
        ]

    def clean(self):
        super().clean()
        if self.workspace_id and self.user_id:
            owner_id = self.workspace.executive_id
            if (self.role == self.Role.EXECUTIVE) != (owner_id == self.user_id):
                raise ValidationError("The workspace owner must be its executive; other members must be assistants.")

    def __str__(self):
        return f"{self.user} · {self.get_role_display()}"


class Message(models.Model):
    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        SENDING = "sending", "Sending"
        SENT = "sent", "Sent"
        FAILED = "failed", "Not sent"
        UNCERTAIN = "uncertain", "Delivery needs checking"

    workspace = models.ForeignKey(Workspace, on_delete=models.CASCADE, related_name="messages")
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="mail_drafts")
    to = models.TextField()
    cc = models.TextField(blank=True)
    bcc = models.TextField(blank=True)
    subject = models.CharField(max_length=255)
    body = models.TextField()
    send_date = models.DateField(default=timezone.localdate)
    send_time = models.TimeField(null=True, blank=True)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.DRAFT, db_index=True)
    version = models.PositiveIntegerField(default=1)
    sent_at = models.DateTimeField(null=True, blank=True)
    sent_signature = models.TextField(blank=True)
    provider_id = models.CharField(max_length=255, blank=True)
    last_error = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["send_date", "created_at", "pk"]
        indexes = [models.Index(fields=["workspace", "status", "send_date"], name="mail_workspace_outbox")]
        constraints = [
            models.CheckConstraint(condition=models.Q(status__in=["draft", "sending", "sent", "failed", "uncertain"]), name="valid_message_status"),
            models.CheckConstraint(condition=models.Q(version__gte=1), name="positive_message_version"),
        ]

    def clean(self):
        super().clean()
        from .services import MAX_BODY_CHARS, parse_addresses, validate_recipient_count, validate_subject

        errors = {}
        for field in ("to", "cc", "bcc"):
            try:
                setattr(self, field, parse_addresses(getattr(self, field), required=field == "to"))
            except ValidationError as exc:
                errors[field] = exc.messages
        try:
            validate_subject(self.subject)
        except ValidationError as exc:
            errors["subject"] = exc.messages
        if len(self.body or "") > MAX_BODY_CHARS:
            errors["body"] = f"Message bodies cannot exceed {MAX_BODY_CHARS:,} characters."
        if not any(field in errors for field in ("to", "cc", "bcc")):
            try:
                validate_recipient_count(self.to, self.cc, self.bcc)
            except ValidationError as exc:
                errors["to"] = exc.messages
        if self.workspace_id and self.created_by_id:
            if not Membership.objects.filter(workspace_id=self.workspace_id, user_id=self.created_by_id).exists():
                errors["created_by"] = "The author must belong to this workspace."
        if errors:
            raise ValidationError(errors)

    def __str__(self):
        return self.subject


class Attachment(models.Model):
    message = models.ForeignKey(Message, on_delete=models.CASCADE, related_name="attachments")
    file = models.FileField(upload_to=attachment_path, max_length=255)
    original_name = models.CharField(max_length=255)
    size = models.PositiveBigIntegerField(default=0)
    content_type = models.CharField(max_length=127, default="application/octet-stream")

    def save(self, *args, **kwargs):
        if self.file:
            if not self.original_name:
                self.original_name = Path(self.file.name.replace("\\", "/")).name[:255]
            if not self.size:
                self.size = self.file.size
        return super().save(*args, **kwargs)

    def __str__(self):
        return self.original_name


class GoogleCredential(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="google_credential")
    encrypted_data = models.TextField()
    subject_hash = models.CharField(max_length=64, unique=True, null=True, blank=True)
    connected = models.BooleanField(default=True)
    updated_at = models.DateTimeField(auto_now=True)


class AuditEvent(models.Model):
    workspace = models.ForeignKey(Workspace, on_delete=models.CASCADE, related_name="audit_events")
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)
    message = models.ForeignKey(Message, null=True, blank=True, on_delete=models.SET_NULL, related_name="audit_events")
    action = models.CharField(max_length=80)
    detail = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-pk"]

    def __str__(self):
        return self.action


class MergeReceipt(models.Model):
    """A database-backed, one-use receipt for an approved CSV draft preview."""

    token = models.CharField(max_length=64, unique=True)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    created_at = models.DateTimeField(auto_now_add=True)
