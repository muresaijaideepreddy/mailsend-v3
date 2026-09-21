"""Hide unused generated placeholders while preserving accounts and memberships."""

import re

from django.conf import settings
from django.contrib.auth.hashers import is_password_usable
from django.db import migrations


ACTION = "assistant.default_retired"


def untouched(apps, alias, membership, user, marker_ids=()):
    base = f"worker-{membership.workspace.executive_id}"
    if not re.fullmatch(re.escape(base) + r"(?:-(?:[2-9]|[1-9][0-9]+))?", user.username):
        return False
    if (
        user.email or user.first_name or user.last_name
        or is_password_usable(user.password) or user.last_login is not None
        or user.is_staff or user.is_superuser
        or user.groups.using(alias).exists() or user.user_permissions.using(alias).exists()
        or apps.get_model("mail", "Workspace").objects.using(alias).filter(executive_id=user.pk).exists()
    ):
        return False
    for model_name, field in (("Message", "created_by_id"), ("GoogleCredential", "user_id"), ("MergeReceipt", "user_id")):
        if apps.get_model("mail", model_name).objects.using(alias).filter(**{field: user.pk}).exists():
            return False
    events = apps.get_model("mail", "AuditEvent").objects.using(alias).exclude(pk__in=marker_ids)
    if events.filter(actor_id=user.pk).exists():
        return False
    # Worker-management events use this reference. A digit boundary keeps, for
    # example, a record for User 10 from being attributed to User 1.
    reference = re.compile(rf"\bUser {user.pk}(?!\d)", re.IGNORECASE)
    details = events.filter(detail__icontains=f"User {user.pk}").values_list("detail", flat=True)
    return not any(reference.search(detail) for detail in details.iterator())


def retire_unused_defaults(apps, schema_editor):
    alias = schema_editor.connection.alias
    User = apps.get_model(settings.AUTH_USER_MODEL)
    Membership = apps.get_model("mail", "Membership")
    AuditEvent = apps.get_model("mail", "AuditEvent")
    members = Membership.objects.using(alias).filter(role="assistant", user__is_active=True).select_related("workspace")
    for membership in members.iterator():
        user = User.objects.using(alias).select_for_update().get(pk=membership.user_id)
        if not user.is_active or not untouched(apps, alias, membership, user):
            continue
        User.objects.using(alias).filter(pk=user.pk).update(is_active=False)
        AuditEvent.objects.using(alias).create(
            workspace_id=membership.workspace_id, actor_id=None,
            action=ACTION, detail=f"User {user.pk}",
        )


def restore_unused_defaults(apps, schema_editor):
    alias = schema_editor.connection.alias
    User = apps.get_model(settings.AUTH_USER_MODEL)
    Membership = apps.get_model("mail", "Membership")
    AuditEvent = apps.get_model("mail", "AuditEvent")
    members = Membership.objects.using(alias).filter(role="assistant", user__is_active=False).select_related("workspace")
    for membership in members.iterator():
        markers = AuditEvent.objects.using(alias).filter(
            workspace_id=membership.workspace_id, actor_id=None, message_id=None,
            action=ACTION, detail=f"User {membership.user_id}",
        )
        marker_ids = list(markers.values_list("pk", flat=True))
        if not marker_ids:
            continue
        user = User.objects.using(alias).select_for_update().get(pk=membership.user_id)
        if not user.is_active and untouched(apps, alias, membership, user, marker_ids):
            User.objects.using(alias).filter(pk=user.pk).update(is_active=True)
            markers.delete()


class Migration(migrations.Migration):
    dependencies = [("mail", "0005_message_date_ordering")]

    operations = [migrations.RunPython(retire_unused_defaults, restore_unused_defaults)]
