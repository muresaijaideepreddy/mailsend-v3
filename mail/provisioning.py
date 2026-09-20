"""Create a workspace's first worker without issuing usable credentials."""

from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import F

from .models import Membership, Workspace


def ensure_initial_worker(workspace):
    """Preserve existing assistants; newly provisioned workers need a password."""
    User = get_user_model()
    assistants = Membership.objects.filter(workspace_id=workspace.pk, role=Membership.Role.ASSISTANT).select_related("user")
    existing = assistants.first()
    if existing:
        return existing
    with transaction.atomic():
        # Acquire a write lock before reading inside the transaction. SQLite's
        # select_for_update is a no-op; concurrent first visits must serialize.
        Workspace.objects.filter(pk=workspace.pk).update(name=F("name"))
        locked_workspace = Workspace.objects.get(pk=workspace.pk)
        existing = assistants.first()
        if existing:
            return existing
        base = f"worker-{locked_workspace.executive_id}"
        username = base
        suffix = 1
        while User.objects.filter(username__iexact=username).exists():
            suffix += 1
            username = f"{base}-{suffix}"
        user = User.objects.create_user(username=username, email="", password=None)
        return Membership.objects.create(user=user, workspace=locked_workspace, role=Membership.Role.ASSISTANT)
