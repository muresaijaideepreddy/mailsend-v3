"""Validation, CSV preview and executive-authorized delivery.

Calling code must not wrap send_message in a larger database transaction: the
claim has to commit before contacting a provider. Ambiguous delivery is never
automatically retried; an executive must reconcile it in the provider's Sent mail.
"""

import csv
import io
import json
import mimetypes
import os
import re
import uuid
from email import policy
from email.errors import HeaderParseError
from email.message import EmailMessage
from email.parser import HeaderParser
from email.utils import formataddr, format_datetime, getaddresses, make_msgid
from pathlib import Path

from django.conf import settings
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.validators import validate_email
from django.db import OperationalError, connection, transaction
from django.db.models import F, Q
from django.http import Http404
from django.utils import timezone

from .models import Attachment, AuditEvent, Membership, Message


MAX_ATTACHMENTS = 3
MAX_ATTACHMENT_BYTES = 20 * 1024 * 1024
MAX_RECIPIENTS = 450
MAX_CSV_BYTES = 1024 * 1024
MAX_MERGE_ROWS = 200
MAX_BODY_CHARS = 100_000
MAX_MERGE_PREVIEW_BYTES = 4 * 1024 * 1024
_CONTROLS = re.compile(r"[\x00-\x1f\x7f]")
_PLACEHOLDER = re.compile(r"{{\s*([A-Za-z_][A-Za-z0-9_]*)\s*}}")


class DeliveryRejected(Exception):
    """The provider definitively did not accept this message (safe to retry)."""

    def __init__(self, message, *, code=""):
        super().__init__(message)
        self.code = code


def membership_for(user):
    if not getattr(user, "is_authenticated", False) or not getattr(user, "is_active", False):
        raise PermissionDenied("Sign in to access this workspace.")
    try:
        # Read the current active flag as well: background/service callers may
        # hold a User instance loaded before an administrator disabled access.
        return Membership.objects.select_related("workspace", "workspace__executive").get(user=user, user__is_active=True)
    except Membership.DoesNotExist as exc:
        raise PermissionDenied("This account is not assigned to a workspace.") from exc


def require_executive(user):
    member = membership_for(user)
    if member.role != Membership.Role.EXECUTIVE or member.workspace.executive_id != user.pk:
        raise PermissionDenied("Only the workspace executive can send messages.")
    return member


def visible_messages(user):
    member = membership_for(user)
    messages = Message.objects.filter(workspace=member.workspace)
    if member.role == Membership.Role.EXECUTIVE and member.workspace.executive_id == user.pk:
        return messages
    if member.role != Membership.Role.ASSISTANT:
        raise PermissionDenied("This account has an invalid workspace role.")
    return messages.filter(Q(created_by=user) | Q(status=Message.Status.SENT))


def parse_addresses(value, required=False):
    value = str(value or "")
    if len(value) > 100_000 or _CONTROLS.search(value):
        raise ValidationError("Email addresses cannot contain line breaks or control characters.")
    value = value.strip()
    if not value:
        if required:
            raise ValidationError("Enter at least one recipient email address.")
        return ""
    try:
        header = HeaderParser(policy=policy.default).parsestr(f"To: {value}\n\n")["To"]
        if header.defects or not header.addresses:
            raise ValueError("Invalid address syntax")
        canonical = []
        seen = set()
        for address in header.addresses:
            email = address.addr_spec
            validate_email(email)
            if len(email) > 254 or not address.username or not address.domain:
                raise ValueError("Invalid email address")
            key = email.casefold()
            if key not in seen:
                seen.add(key)
                canonical.append(formataddr((address.display_name, email)))
        if len(canonical) > MAX_RECIPIENTS:
            raise ValidationError(f"A message may have at most {MAX_RECIPIENTS} recipients.")
        return ", ".join(canonical)
    except (ValueError, IndexError, TypeError, UnicodeError, AttributeError, RecursionError, HeaderParseError) as exc:
        # The stdlib's permissive RFC parser can raise internal errors for
        # malformed groups or deeply nested comments instead of listing defects.
        # All such untrusted recipient input must remain a validation failure.
        raise ValidationError("Enter valid email addresses separated by commas.") from exc


def validate_recipient_count(*fields):
    count = sum(len(getaddresses([value])) for value in fields if value)
    if count > MAX_RECIPIENTS:
        raise ValidationError(f"A message may have at most {MAX_RECIPIENTS} recipients across To, CC and BCC.")


def validate_subject(subject):
    if not subject or not str(subject).strip():
        raise ValidationError("Enter a subject.")
    if len(subject) > 255:
        raise ValidationError("The subject cannot exceed 255 characters.")
    if _CONTROLS.search(subject):
        raise ValidationError("The subject cannot contain line breaks or control characters.")


def validate_attachments(files, existing=()):
    uploads = [file for file in files if file is not None]
    retained = list(existing)
    if len(uploads) + len(retained) > MAX_ATTACHMENTS:
        raise ValidationError(f"Attach at most {MAX_ATTACHMENTS} files.")
    total = 0
    for file in [*uploads, *retained]:
        size = getattr(file, "size", None)
        if size is None or size < 0:
            raise ValidationError("The attachment size could not be verified.")
        total += size
        name = getattr(file, "original_name", None) or getattr(file, "name", "")
        if not name or _CONTROLS.search(name):
            raise ValidationError("Attachment names cannot contain control characters.")
    if total > MAX_ATTACHMENT_BYTES:
        raise ValidationError("Attachments must total 20 MiB or less.")


def _csv_rows(csv_file, max_rows):
    if getattr(csv_file, "size", 0) > MAX_CSV_BYTES:
        raise ValidationError("CSV files must be 1 MiB or smaller.")
    raw = csv_file.read(MAX_CSV_BYTES + 1)
    if isinstance(raw, str):
        raw = raw.encode("utf-8")
    if len(raw) > MAX_CSV_BYTES:
        raise ValidationError("CSV files must be 1 MiB or smaller.")
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ValidationError("Upload a UTF-8 encoded CSV file.") from exc
    if "\x00" in text:
        raise ValidationError("The CSV contains an invalid null character.")
    try:
        reader = csv.reader(io.StringIO(text, newline=""), strict=True)
        headers = next(reader, None)
        if not headers:
            raise ValidationError("The CSV must contain a header row and at least one recipient.")
        headers = [header.strip() for header in headers]
        if any(not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", header) for header in headers):
            raise ValidationError("CSV headers must use letters, numbers and underscores, starting with a letter or underscore.")
        if len(headers) != len(set(headers)):
            raise ValidationError("CSV headers must be unique.")
        if "email" not in headers:
            raise ValidationError("The CSV requires an 'email' column.")
        rows = []
        next_line = reader.line_num + 1
        for row in reader:
            # CSV records can span several physical lines, and blank records
            # are ignored. Keep the source line so errors identify the upload
            # row the user must fix rather than its filtered preview index.
            source_line = next_line
            next_line = reader.line_num + 1
            if not row or all(not cell.strip() for cell in row):
                continue
            if len(row) != len(headers):
                raise ValidationError(f"CSV row {source_line} has a different number of columns from its header.")
            rows.append((source_line, dict(zip(headers, [cell.strip() for cell in row]))))
            if len(rows) > max_rows:
                raise ValidationError(f"The CSV may contain at most {max_rows} recipient rows.")
        if not rows:
            raise ValidationError("The CSV must contain at least one recipient row.")
        return headers, rows
    except csv.Error as exc:
        raise ValidationError("The CSV is malformed. Check its commas and quoted fields.") from exc


def _render_merge(value, row, headers, max_chars=MAX_BODY_CHARS):
    if not isinstance(value, str) or len(value) > max_chars:
        raise ValidationError(f"The merge template exceeds the {max_chars:,} character limit.")
    fields = set(_PLACEHOLDER.findall(value))
    remainder = _PLACEHOLDER.sub("", value)
    if "{{" in remainder or "}}" in remainder:
        raise ValidationError("Use placeholders in the form {{field_name}}.")
    missing = fields - set(headers)
    if missing:
        raise ValidationError("CSV columns are missing for: " + ", ".join(sorted(missing)) + ".")
    # Check the final size before substitution: one CSV cell repeated in many
    # placeholders can otherwise turn a small upload into gigabytes of output.
    final_length = len(value)
    for match in _PLACEHOLDER.finditer(value):
        final_length += len(row[match.group(1)]) - len(match.group(0))
    if final_length > max_chars:
        raise ValidationError(f"A merged field exceeds the {max_chars:,} character limit.")
    return _PLACEHOLDER.sub(lambda match: row[match.group(1)], value)


def merge_preview(csv_file, subject, body, cc="", bcc=""):
    if not isinstance(body, str) or len(body) > MAX_BODY_CHARS:
        raise ValidationError(f"Message bodies cannot exceed {MAX_BODY_CHARS:,} characters.")
    headers, rows = _csv_rows(csv_file, MAX_MERGE_ROWS)
    result = []
    preview_bytes = 2  # JSON array brackets; the preview is persisted in session.
    for source_line, row in rows:
        try:
            to = parse_addresses(row["email"], required=True)
            if len(getaddresses([to])) != 1:
                raise ValidationError("Each email cell must contain exactly one recipient.")
            rendered = {"to": to}
            for field, value in (("subject", subject), ("body", body), ("cc", cc), ("bcc", bcc)):
                rendered[field] = _render_merge(value, row, headers, max_chars=255 if field == "subject" else MAX_BODY_CHARS)
            validate_subject(rendered["subject"])
            if not rendered["body"].strip():
                raise ValidationError("Enter a message body.")
            rendered["cc"] = parse_addresses(rendered["cc"])
            rendered["bcc"] = parse_addresses(rendered["bcc"])
            validate_recipient_count(rendered["to"], rendered["cc"], rendered["bcc"])
            preview_bytes += len(json.dumps(rendered, separators=(",", ":")).encode("utf-8")) + 1
            if preview_bytes > MAX_MERGE_PREVIEW_BYTES:
                raise ValidationError("The combined mail merge preview exceeds 4 MiB. Use a smaller CSV batch or shorter messages.")
            result.append(rendered)
        except ValidationError as exc:
            raise ValidationError(f"CSV row {source_line}: " + " ".join(exc.messages)) from exc
    return result


def bcc_from_csv(csv_file):
    _, rows = _csv_rows(csv_file, MAX_RECIPIENTS)
    addresses = []
    for source_line, row in rows:
        try:
            address = parse_addresses(row["email"], required=True)
            if len(getaddresses([address])) != 1:
                raise ValidationError("Each email cell must contain exactly one recipient.")
            addresses.append(address)
        except ValidationError as exc:
            raise ValidationError(f"CSV row {source_line}: " + " ".join(exc.messages)) from exc
    return parse_addresses(", ".join(addresses), required=True)


def build_email(message):
    """Build the exact plain-text MIME message, including the workspace signature."""
    outgoing = EmailMessage(policy=policy.SMTP)
    outgoing["From"] = parse_addresses(message.workspace.executive.email, required=True)
    outgoing["To"] = message.to
    if message.cc:
        outgoing["Cc"] = message.cc
    if message.bcc:
        outgoing["Bcc"] = message.bcc
    outgoing["Subject"] = message.subject
    outgoing["Date"] = format_datetime(timezone.now())
    outgoing["Message-ID"] = make_msgid(domain="mailsend.local")
    body = message.body
    if message.workspace.signature.strip():
        body += "\n\n-- \n" + message.workspace.signature.strip()
    outgoing.set_content(body)
    attachments = list(message.attachments.all())
    validate_attachments([], existing=attachments)
    actual_total = 0
    for attachment in attachments:
        with attachment.file.open("rb") as handle:
            data = handle.read(MAX_ATTACHMENT_BYTES + 1)
        actual_total += len(data)
        if actual_total > MAX_ATTACHMENT_BYTES:
            raise ValidationError("Attachments must total 20 MiB or less.")
        content_type = attachment.content_type or mimetypes.guess_type(attachment.original_name)[0] or "application/octet-stream"
        if (not re.fullmatch(r"[A-Za-z0-9!#$&^_.+-]+/[A-Za-z0-9!#$&^_.+-]+", content_type)
                or content_type.split("/", 1)[0].lower() in {"message", "multipart"}):
            # Uploads are opaque bytes. Structured MIME types require nested
            # message/part objects; assigning them to base64 bytes corrupts
            # saved .eml attachments and produces malformed multipart parts.
            content_type = "application/octet-stream"
        maintype, subtype = content_type.split("/", 1)
        filename = Path(attachment.original_name.replace("\\", "/")).name
        outgoing.add_attachment(data, maintype=maintype, subtype=subtype, filename=filename)
    return outgoing


def _deliver_demo(email_message):
    provider_id = "demo-" + uuid.uuid4().hex
    folder = Path(getattr(settings, "MAILSEND_DEMO_OUTBOX", Path(settings.BASE_DIR) / "demo_outbox"))
    folder.mkdir(parents=True, exist_ok=True)
    with (folder / f"{provider_id}.eml").open("xb") as handle:
        handle.write(email_message.as_bytes())
        handle.flush()
        os.fsync(handle.fileno())
    return provider_id


def send_message(user, message_id, expected_version=None):
    member = require_executive(user)
    try:
        message = Message.objects.select_related("workspace", "workspace__executive").get(pk=message_id, workspace=member.workspace)
    except Message.DoesNotExist as exc:
        raise Http404("Message not found.") from exc
    if message.status == Message.Status.SENT:
        return message
    if message.status not in (Message.Status.DRAFT, Message.Status.FAILED):
        raise ValidationError("Delivery has already started. Check the executive's Sent mail before taking further action.")
    if expected_version is not None and message.version != expected_version:
        raise ValidationError("This message changed after confirmation. Review it again before sending.")
    message.full_clean()
    try:
        outgoing = build_email(message)
    except OSError as exc:
        raise ValidationError("An attachment could not be read. Reattach it before sending.") from exc
    mode = getattr(settings, "MAILSEND_DELIVERY_MODE", "demo")
    if mode not in ("demo", "gmail"):
        raise ValidationError("The configured delivery mode is invalid.")
    try:
        with transaction.atomic():
            claimed = Message.objects.filter(pk=message.pk, workspace=member.workspace, version=message.version, status=message.status).update(
                status=Message.Status.SENDING, version=F("version") + 1, last_error="", updated_at=timezone.now()
            )
            if not claimed:
                raise ValidationError("This message was changed or another send has already started. Refresh the page.")
            AuditEvent.objects.create(workspace=member.workspace, actor=user, message=message, action="send_started", detail=f"Delivery mode: {mode}.")
    except OperationalError as exc:
        sqlite_code = getattr(exc.__cause__, "sqlite_errorcode", 0)
        if connection.vendor != "sqlite" or sqlite_code & 0xFF not in (5, 6):
            raise
        # The claim rolled back and this request has not called the provider.
        # A competing send may still be in progress: refresh before reapproving.
        raise ValidationError("Another workspace update or send is finishing. Refresh the outbox before reviewing and approving delivery again.") from exc
    try:
        if mode == "demo":
            provider_id = _deliver_demo(outgoing)
        else:
            from .google_api import send_gmail
            provider_id = send_gmail(user, outgoing)
        if not isinstance(provider_id, str) or not provider_id or len(provider_id) > 255:
            raise RuntimeError("Provider returned no usable delivery receipt")
    except DeliveryRejected as exc:
        # Persist only application-owned guidance, never provider response text.
        error = "The provider did not accept this message. Check the Google connection and try again."
        if exc.code == "gmail_api_disabled":
            error = "The Gmail API is disabled for this Google OAuth project. Enable the Gmail API in Google Cloud, then review and approve this message again."
        _finish_delivery(message, user, Message.Status.FAILED, error)
    except Exception:
        # Never retry a timeout or unknown error: the provider may have accepted it.
        _finish_delivery(message, user, Message.Status.UNCERTAIN, "Delivery could not be confirmed. Check the executive's Sent mail before trying again; automatic retry is disabled.")
    else:
        _finish_delivery(message, user, Message.Status.SENT, provider_id=provider_id)
    message.refresh_from_db()
    return message


def _finish_delivery(message, user, status, error="", provider_id=""):
    with transaction.atomic():
        updated = Message.objects.filter(pk=message.pk, status=Message.Status.SENDING).update(
            status=status, last_error=error, provider_id=provider_id,
            sent_at=timezone.now() if status == Message.Status.SENT else None,
            sent_signature=message.workspace.signature if status == Message.Status.SENT else "",
            updated_at=timezone.now(), version=F("version") + 1,
        )
        if updated:
            AuditEvent.objects.create(workspace=message.workspace, actor=user, message=message, action=f"delivery_{status}", detail=error)
