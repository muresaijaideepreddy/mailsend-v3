from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core import signing
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import F
from django.shortcuts import get_object_or_404, render, redirect
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods

from .contacts import contact_matches, fetch_contacts, suggested_name
from .models import AuditEvent, Message
from .services import DeliveryRejected, require_executive, parse_addresses

SALT = 'contact-choice-v1'


@login_required
@never_cache
@require_http_methods(['GET', 'POST'])
def match_contacts(request, pk):
    member = require_executive(request.user)
    draft = get_object_or_404(Message, pk=pk, workspace=member.workspace, status__in=('draft', 'failed'))
    name = request.POST.get('name', suggested_name(draft)).strip()[:100]
    field = request.POST.get('field', 'to')
    results, error = [], ''
    if field not in ('to', 'cc', 'bcc'):
        field = 'to'
    if request.method == 'POST':
        if request.POST.get('choice'):
            try:
                choice = signing.loads(request.POST['choice'], salt=SALT, max_age=600)
                if (choice['user'], choice['draft'], choice['version']) != (request.user.pk, draft.pk, draft.version):
                    raise ValueError()
                field = choice['field']
                if field not in ('to', 'cc', 'bcc'):
                    raise ValueError()
                value = parse_addresses(', '.join(filter(None, [getattr(draft, field), choice['email']])))
                setattr(draft, field, value)
                draft.full_clean()
                with transaction.atomic():
                    changed = Message.objects.filter(pk=draft.pk, workspace=member.workspace, version=choice['version'], status__in=('draft', 'failed')).update(
                        **{field: value}, version=F('version') + 1, status='draft', last_error='', updated_at=timezone.now())
                    if changed != 1:
                        raise ValueError()
                    AuditEvent.objects.create(workspace=member.workspace, actor=request.user, message=draft, action='draft.contact_selected')
                messages.success(request, 'Contact added to the draft. Review all recipients before sending.')
                return redirect('mail:edit', pk=draft.pk)
            except (signing.BadSignature, ValueError, KeyError, TypeError, ValidationError):
                error = 'This choice expired or the draft changed. Search again before selecting a contact.'
        else:
            try:
                results = contact_matches(name, fetch_contacts(request.user))
                for item in results:
                    item['choice'] = signing.dumps({'user': request.user.pk, 'draft': draft.pk, 'version': draft.version,
                                                   'field': field, 'email': item['email']}, salt=SALT)
                if not results:
                    error = 'No matching contacts with valid email addresses. Try a fuller name or enter the email manually.'
            except DeliveryRejected as exc:
                error = str(exc)
    return render(request, 'mail/contact_matches.html', {'message_obj': draft, 'name': name, 'field': field, 'results': results, 'error': error})
