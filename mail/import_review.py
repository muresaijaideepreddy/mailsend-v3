"""Shared import review; normal draft permissions and version checks apply."""
import re
from django.contrib import messages
from django.core import signing
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import F
from django.shortcuts import get_object_or_404, redirect, render
from django.http import Http404
from django.utils import timezone
from django.views.decorators.http import require_http_methods
from .contacts import normalize_name, suggested_name
from .forms import MessageForm
from .models import AuditEvent
from .services import editable_messages, parse_addresses
from .views import member_required, save_draft


@member_required
@require_http_methods(['GET', 'POST'])
def review_imports(request):
    allowed = editable_messages(request.user).exclude(imported_from='')
    error = ''
    if request.method == 'POST':
        try:
            draft_id = int(request.POST.get('draft_id', ''))
        except (TypeError, ValueError):
            raise Http404('Draft not found')
        draft = get_object_or_404(allowed, pk=draft_id)
        form = MessageForm(request.POST, instance=draft)
        if form.is_valid():
            try:
                with transaction.atomic():
                    save_draft(request, form)
                    if request.POST.get('apply_same'):
                        payload = signing.loads(request.POST.get('same_token', ''), salt='import.same-name', max_age=1800)
                        if payload['user'] != request.user.pk or payload['draft'] != draft.pk or not draft.import_batch_id:
                            raise ValidationError('The group changed. Reload and review the affected drafts.')
                        address = parse_addresses(form.cleaned_data['to'], required=True)
                        for pk, version in payload['targets']:
                            target = get_object_or_404(allowed, pk=pk, import_batch_id=draft.import_batch_id)
                            if target.to or normalize_name(suggested_name(target)) != payload['name']:
                                raise ValidationError('A related recipient changed. Reload before applying to the group.')
                            target.to = address
                            target.full_clean()
                            if not allowed.filter(pk=pk, version=version).update(to=address, version=F('version') + 1, updated_at=timezone.now(), status='draft', last_error=''):
                                raise ValidationError('A related draft changed. Reload and try again.')
                            AuditEvent.objects.create(workspace=draft.workspace, actor=request.user, message=target, action='draft.recipient_applied')
                messages.success(request, 'Draft saved. Sending still requires executive approval.')
                return redirect(request.get_full_path())
            except (ValidationError, signing.BadSignature, KeyError, TypeError) as exc:
                error = ' '.join(exc.messages) if isinstance(exc, ValidationError) else 'The group selection expired. Reload and try again.'
        else:
            error = ' '.join(str(e) for errors in form.errors.values() for e in errors)
    drafts = list(allowed.order_by('-created_at', '-pk'))
    total = len(drafts)
    ready = sum(d.ready_to_send for d in drafts)
    mode = request.GET.get('filter', 'needs')
    selected = [d for d in drafts if mode == 'all' or (mode == 'ready' and d.ready_to_send) or (mode not in ('all', 'ready') and not d.ready_to_send)]
    rows = []
    for draft in selected:
        name = normalize_name(suggested_name(draft))
        peers = [d for d in drafts if d.pk != draft.pk and draft.import_batch_id and d.import_batch_id == draft.import_batch_id and not d.to and len(name) > 1 and name not in ('team', 'everyone', 'unknown') and normalize_name(suggested_name(d)) == name]
        candidates = re.findall(r'([^\n<>]+) <([^<>\s]+@[^<>\s]+)> \((\d+)% spelling similarity\)', draft.contact_match_notes)
        rows.append({'draft': draft, 'candidates': [{'name': n.strip(), 'email': e, 'score': s} for n,e,s in candidates], 'peers': peers,
                     'token': signing.dumps({'user': request.user.pk, 'draft': draft.pk, 'name': name, 'targets': [[d.pk,d.version] for d in peers]}, salt='import.same-name')})
    return render(request, 'mail/import_review.html', {'rows': rows, 'total': total, 'ready': ready, 'remaining': total-ready, 'mode': mode, 'error': error})
