"""Short-lived dashboard approvals bound to owner, message versions and signature."""

import hashlib

from django.core import signing
from django.core.exceptions import ValidationError
from django.utils import timezone


def dashboard_approval(request, items, action):
    payload = {
        'user': request.user.pk,
        'workspace': request.membership.workspace_id,
        'action': action,
        'items': [[item.pk, item.version] for item in items],
        'signature': hashlib.sha256(request.membership.workspace.signature.encode()).hexdigest(),
        'at': timezone.now().timestamp(),
    }
    return signing.dumps(payload, salt='mail.dashboard-approval', compress=True)


def read_dashboard_approval(request, action):
    try:
        payload = signing.loads(request.POST.get('dashboard_token', ''), salt='mail.dashboard-approval')
        elapsed = timezone.now().timestamp() - payload['at']
        valid = (
            payload['user'] == request.user.pk
            and payload['workspace'] == request.membership.workspace_id
            and payload['action'] == action
            and 0 <= elapsed <= 1800
            and payload['signature'] == hashlib.sha256(request.membership.workspace.signature.encode()).hexdigest()
            and isinstance(payload['items'], list)
            and all(isinstance(pair, list) and len(pair) == 2
                    and all(type(value) is int and value > 0 for value in pair)
                    for pair in payload['items'])
        )
        if not valid:
            raise ValueError('Invalid approval')
    except (signing.BadSignature, ValueError, TypeError, KeyError, AttributeError) as exc:
        raise ValidationError('The outbox changed or expired. Reload it before sending.') from exc
    return payload
