import logging
import secrets
from functools import wraps

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import LoginView
from django.core import signing
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, OperationalError, connection, transaction
from django.db.models import F, Q
from django.http import FileResponse, Http404, HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.crypto import constant_time_compare
from django.views.decorators.http import require_http_methods

from .approvals import dashboard_approval, read_dashboard_approval
from .forms import AssistantForm, MergeForm, MessageForm, SignatureForm
from .models import Attachment, AuditEvent, Membership, Message, Workspace
from .services import deletable_messages, editable_messages, merge_preview, require_executive, send_message, visible_messages

EDITABLE = ('draft', 'failed')
logger = logging.getLogger(__name__)


def member_required(view):
    @login_required
    @wraps(view)
    def wrapped(request, *args, **kwargs):
        request.membership = Membership.objects.select_related('workspace').filter(user=request.user).first()
        if request.membership is None:
            raise PermissionDenied('This account has no MailSend workspace. Ask an administrator to assign one.')
        return view(request, *args, **kwargs)
    return wrapped


class MailLoginView(LoginView):
    template_name = 'registration/login.html'
    redirect_authenticated_user = True


def scope_period(queryset, period, *, now=None):
    if period not in ('current', 'future'):
        return queryset
    # V3 defines Current/Future by the workspace-local calendar date.
    today = timezone.localtime(now or timezone.now()).date()
    if period == 'current':
        return queryset.filter(send_date__lte=today)
    return queryset.filter(send_date__gt=today)



def valid_period(period):
    if period not in ('all', 'current', 'future'):
        raise Http404('Unknown review period.')
    return period


@member_required
@require_http_methods(['GET'])
def dashboard(request):
    period = valid_period(request.GET.get('period', 'all'))
    all_messages = visible_messages(request.user)
    drafts = all_messages.exclude(status='sent')
    now = timezone.now()
    counts = {'all': drafts.count(), 'current': scope_period(drafts, 'current', now=now).count(), 'future': scope_period(drafts, 'future', now=now).count(), 'sent': all_messages.filter(status='sent').count()}
    drafts = scope_period(drafts, period, now=now)
    query = request.GET.get('q', '').strip()[:200]
    if query:
        drafts = drafts.filter(Q(subject__icontains=query) | Q(to__icontains=query) | Q(body__icontains=query))
    drafts = list(drafts.select_related('created_by'))
    for draft in drafts:
        draft.can_edit = draft.status in EDITABLE
        draft.can_delete = draft.can_edit and (
            draft.created_by_id == request.user.pk or request.membership.role == Membership.Role.EXECUTIVE
        )
    batch_token = None
    if request.membership.role == Membership.Role.EXECUTIVE:
        require_executive(request.user)
        for draft in drafts:
            if draft.status in EDITABLE:
                draft.dashboard_token = dashboard_approval(request, [draft], f'send_{draft.pk}')
        batch_items = list(scope_period(all_messages.filter(status__in=EDITABLE), 'current', now=now))
        batch_token = dashboard_approval(request, batch_items, 'send_current')
    return render(request, 'mail/dashboard.html', {'drafts': drafts, 'counts': counts, 'period': period, 'query': query, 'today': timezone.localdate(), 'dashboard_batch_token': batch_token, 'active_nav': 'outbox'})


def save_draft(request, form, creating=False):
    """Claim the version before any write, so review/send and edits cannot race."""
    instance = form.instance
    written_files = []
    try:
        with transaction.atomic():
            if creating:
                instance.save()
            else:
                fields = {name: getattr(instance, name) for name in ('to', 'cc', 'bcc', 'subject', 'body', 'send_date')}
                fields.update(send_time=None, version=F('version') + 1, updated_at=timezone.now(), status='draft', last_error='')
                changed = Message.objects.filter(pk=instance.pk, version=form.cleaned_data['version'], status__in=EDITABLE).update(**fields)
                if changed != 1:
                    raise ValidationError('This message changed or was sent while you were editing. Reload it before saving.')
            for attachment in form.cleaned_data.get('remove_attachments', []):
                storage, name = attachment.file.storage, attachment.file.name
                attachment.delete()
                # Cleanup failure must not turn a committed replacement into
                # an apparent rollback or remove its newly saved attachments.
                transaction.on_commit(lambda s=storage, n=name: s.delete(n), robust=True)
            for uploaded in form.new_files:
                attachment = Attachment(message=instance, original_name=uploaded.name[:255], size=uploaded.size, content_type=(uploaded.content_type or 'application/octet-stream')[:127])
                # Track the stored object before inserting its database row, so
                # a failed insert cannot leave an unreferenced private file.
                attachment.file.save(uploaded.name, uploaded, save=False)
                written_files.append((attachment.file.storage, attachment.file.name))
                attachment.save()
            AuditEvent.objects.create(workspace=instance.workspace, actor=request.user, message=instance, action='draft.created' if creating else 'draft.updated')
    except Exception as exc:
        for storage, name in written_files:
            try:
                storage.delete(name)
            except OSError:
                logger.exception('Could not remove a rolled-back attachment: %s', name)
        if isinstance(exc, OSError):
            raise ValidationError('The attachment could not be saved. Your changes were not saved; try uploading the file again.') from exc
        raise
    return instance


@member_required
@require_http_methods(['GET', 'POST'])
def compose(request, pk=None):
    instance = get_object_or_404(editable_messages(request.user), pk=pk) if pk else Message(workspace=request.membership.workspace, created_by=request.user, send_date=timezone.localdate())
    form = MessageForm(request.POST if request.method == 'POST' else None, request.FILES or None, instance=instance)
    if request.method == 'POST' and form.is_valid():
        try:
            save_draft(request, form, creating=pk is None)
        except ValidationError as exc:
            form.add_error(None, exc)
        else:
            messages.success(request, 'Draft saved. Your executive can review and send it from the outbox.')
            return redirect('mail:dashboard')
    return render(request, 'mail/message_form.html', {'form': form, 'message_obj': instance if pk else None, 'attachments': instance.attachments.all() if pk else [], 'review_mode': False, 'active_nav': 'outbox'})


@member_required
@require_http_methods(['GET'])
def detail(request, pk):
    item = get_object_or_404(visible_messages(request.user), pk=pk)
    return render(request, 'mail/message_detail.html', {'message_obj': item, 'attachments': item.attachments.all(), 'can_edit': editable_messages(request.user).filter(pk=item.pk).exists(), 'can_delete': deletable_messages(request.user).filter(pk=item.pk).exists(), 'active_nav': 'sent' if item.status == 'sent' else 'outbox'})


@member_required
@require_http_methods(['GET', 'POST'])
def delete(request, pk):
    item = get_object_or_404(deletable_messages(request.user), pk=pk)
    if request.method == 'POST':
        try:
            version = int(request.POST.get('version', ''))
        except (ValueError, TypeError):
            return HttpResponseBadRequest('Reload the confirmation before deleting.')
        with transaction.atomic():
            claimed = Message.objects.filter(pk=item.pk, version=version, status__in=EDITABLE).update(version=F('version') + 1)
            if not claimed:
                return render(request, 'mail/error.html', {'heading': 'Message changed', 'detail': 'This message changed or was sent. Reload the outbox before deleting.'}, status=409)
            files = [(a.file.storage, a.file.name) for a in item.attachments.all()]
            AuditEvent.objects.create(workspace=item.workspace, actor=request.user, action='draft.deleted', detail=f'Message {item.pk}')
            item.delete()
            for storage, name in files:
                transaction.on_commit(lambda s=storage, n=name: s.delete(n), robust=True)
        messages.success(request, 'Draft deleted from the shared workspace.')
        return redirect('mail:dashboard')
    return render(request, 'mail/confirm.html', {'heading': 'Delete this draft?', 'explanation': 'This removes the draft and its attachments from both dashboards.', 'messages_to_act': [item], 'submit_label': 'Delete draft', 'destructive': True, 'version': item.version, 'active_nav': 'outbox'})


def confirmation_snapshot(request, items, key):
    snapshot = {'token': secrets.token_urlsafe(32), 'items': [[m.pk, m.version] for m in items], 'signature': request.membership.workspace.signature, 'at': timezone.now().timestamp()}
    request.session[key] = snapshot
    return snapshot


def consume_confirmation(request, key):
    snapshot = request.session.get(key)
    if not snapshot or timezone.now().timestamp() - snapshot.get('at', 0) > 1800:
        raise ValidationError('The confirmation expired. Review the messages again.')
    if snapshot.get('signature') != request.membership.workspace.signature:
        raise ValidationError('The email signature changed. Review the messages again.')
    if not constant_time_compare(str(snapshot.get('token', '')), request.POST.get('batch_token', '')):
        raise ValidationError('The confirmation is invalid. Review the messages again.')
    request.session.pop(key, None)
    return snapshot


@member_required
@require_http_methods(['GET', 'POST'])
def send(request, pk):
    require_executive(request.user)
    item = get_object_or_404(visible_messages(request.user), pk=pk)
    if request.method == 'GET':
        if item.status not in EDITABLE:
            return render(request, 'mail/error.html', {'heading': 'Message cannot be sent', 'detail': 'Sent, sending, or uncertain messages cannot be sent again.'}, status=409)
        snapshot = confirmation_snapshot(request, [item], f'send_{pk}')
        return render(request, 'mail/confirm.html', {'heading': 'Send this message now?', 'explanation': 'You are approving this message, recipients, attachments, and the current signature. Confirming sends it immediately, even if its planned date is later.', 'messages_to_act': [item], 'submit_label': 'Send now', 'version': item.version, 'batch_token': snapshot['token'], 'active_nav': 'outbox'})
    try:
        snapshot = (read_dashboard_approval(request, f'send_{pk}') if request.POST.get('dashboard_token')
                    else consume_confirmation(request, f'send_{pk}'))
        if len(snapshot['items']) != 1 or snapshot['items'][0][0] != pk:
            raise ValidationError('The approval does not match this message.')
        result = send_message(request.user, pk, expected_version=snapshot['items'][0][1])
        if result.status == 'sent':
            messages.success(request, 'Message sent.' if settings.MAILSEND_DELIVERY_MODE == 'gmail' else 'Demo delivery saved. No real email was sent.')
        else:
            messages.error(request, result.last_error or 'Delivery needs attention. Check the message before continuing.')
    except ValidationError as exc:
        messages.error(request, ' '.join(exc.messages))
    return redirect('mail:dashboard')


@member_required
@require_http_methods(['GET', 'POST'])
def send_current(request):
    require_executive(request.user)
    if request.method == 'GET':
        items = list(scope_period(visible_messages(request.user).filter(status__in=EDITABLE), 'current'))
        snapshot = confirmation_snapshot(request, items, 'send_current')
        return render(request, 'mail/confirm.html', {'heading': 'Send current messages?', 'explanation': 'All listed drafts dated today or earlier will be sent.', 'messages_to_act': items, 'submit_label': 'Send current messages', 'batch_token': snapshot['token'], 'active_nav': 'outbox'})
    sent_count = 0
    try:
        snapshot = (read_dashboard_approval(request, 'send_current') if request.POST.get('dashboard_token')
                    else consume_confirmation(request, 'send_current'))
        pairs = snapshot['items']
        now = timezone.now()
        for pk, version in pairs:
            if not scope_period(visible_messages(request.user).filter(pk=pk, version=version, status__in=EDITABLE), 'current', now=now).exists():
                raise ValidationError('A draft changed after confirmation. No messages were sent; review the batch again.')
        for pk, version in pairs:
            result = send_message(request.user, pk, expected_version=version)
            if result.status == 'sent':
                sent_count += 1
            else:
                messages.error(request, 'Delivery stopped on a message needing attention. Remaining drafts were not sent.')
                break
        messages.success(request, f'{sent_count} message(s) delivered' + (' to the local demo outbox. No real email was sent.' if settings.MAILSEND_DELIVERY_MODE == 'demo' else '.'))
    except (ValidationError, Http404) as exc:
        detail = ' '.join(exc.messages) if isinstance(exc, ValidationError) else 'A remaining draft was removed while the batch was sending.'
        if sent_count:
            detail = f'{sent_count} message(s) were delivered before the batch stopped. Remaining messages were not sent. {detail}'
        messages.error(request, detail)
    return redirect('mail:dashboard')


@member_required
@require_http_methods(['GET', 'POST'])
def review(request, period):
    require_executive(request.user)
    valid_period(period)
    try:
        index = int(request.GET.get('index', 0))
        if index < 0:
            raise ValueError
    except ValueError:
        return HttpResponseBadRequest('Invalid review position.')
    key = f'review_{period}'
    if request.method == 'GET' and index == 0:
        request.session[key] = list(scope_period(visible_messages(request.user).filter(status__in=EDITABLE), period).values_list('pk', flat=True))
    ids = request.session.get(key, [])
    if index >= len(ids):
        if request.method == 'POST':
            return render(request, 'mail/error.html', {
                'heading': 'Review no longer available',
                'detail': 'This review ended or expired. Your edits were not saved. Open the outbox to review the draft again.',
            }, status=409)
        return render(request, 'mail/review_empty.html', {'period': period, 'active_nav': 'outbox'})
    instance = visible_messages(request.user).filter(pk=ids[index], status__in=EDITABLE).first()
    if instance is None:
        if request.method == 'POST':
            return render(request, 'mail/error.html', {
                'heading': 'Draft no longer editable',
                'detail': 'This draft was removed or delivery started. Your edits were not saved. Return to the outbox to check its status.',
            }, status=409)
        return redirect(reverse('mail:review', args=[period]) + f'?index={index + 1}')
    # A different tab can replace this session's review sequence. Bind the
    # submitted form to the exact draft shown, not only its sequence position:
    # two unrelated drafts can legitimately have the same version number.
    review_target = {
        'user': request.user.pk, 'workspace': request.membership.workspace_id,
        'period': period, 'index': index, 'message': instance.pk,
    }
    if request.method == 'POST':
        try:
            submitted_target = signing.loads(request.POST.get('review_token', ''),
                                             salt='mail.review-target', max_age=1800)
        except signing.BadSignature:
            submitted_target = None
        if submitted_target != review_target:
            return render(request, 'mail/error.html', {
                'heading': 'Review changed',
                'detail': 'This review changed in another tab or expired. Your draft was not changed. Open the outbox and review it again.',
            }, status=409)
    form = MessageForm(request.POST if request.method == 'POST' else None, request.FILES or None, instance=instance)
    if request.method == 'POST' and form.is_valid():
        try:
            save_draft(request, form)
        except ValidationError as exc:
            form.add_error(None, exc)
        else:
            if index + 1 == len(ids):
                request.session.pop(key, None)
                messages.success(request, 'Review complete. Your edits are saved; no messages were sent.')
                return redirect('mail:dashboard')
            return redirect(reverse('mail:review', args=[period]) + f'?index={index + 1}')
    return render(request, 'mail/message_form.html', {'form': form, 'message_obj': instance, 'attachments': instance.attachments.all(), 'review_mode': True, 'review_index': index + 1, 'review_total': len(ids), 'review_token': signing.dumps(review_target, salt='mail.review-target'), 'period': period, 'active_nav': 'outbox'})


@member_required
@require_http_methods(['GET'])
def sent(request):
    items = Message.objects.filter(workspace=request.membership.workspace, status='sent').order_by('-sent_at')
    query = request.GET.get('q', '').strip()[:200]
    if query:
        items = items.filter(Q(subject__icontains=query) | Q(to__icontains=query))
    return render(request, 'mail/sent.html', {'sent_messages': items, 'query': query, 'active_nav': 'sent'})


@member_required
@require_http_methods(['GET', 'POST'])
def signature(request):
    form = SignatureForm(request.POST if request.method == 'POST' else None, instance=request.membership.workspace)
    if request.method == 'POST' and form.is_valid():
        with transaction.atomic():
            workspace = Workspace.objects.select_for_update().get(pk=request.membership.workspace_id)
            updated_signature = form.cleaned_data['signature']
            if workspace.signature != updated_signature:
                # Signature text is part of the approved email. Invalidate all
                # pending edits and delivery approvals when that text changes.
                Message.objects.filter(workspace=workspace, status__in=EDITABLE).update(
                    version=F('version') + 1, updated_at=timezone.now()
                )
                workspace.signature = updated_signature
                workspace.save(update_fields=['signature'])
                AuditEvent.objects.create(workspace=workspace, actor=request.user, action='signature.updated')
        messages.success(request, 'Signature saved. It will be included in future deliveries.')
        return redirect('mail:signature')
    return render(request, 'mail/signature.html', {'form': form, 'active_nav': 'signature'})


@member_required
@require_http_methods(['GET', 'POST'])
def team(request):
    request.membership = require_executive(request.user)
    form = AssistantForm(request.POST if request.method == 'POST' else None)
    if request.method == 'POST' and form.is_valid():
        try:
            with transaction.atomic():
                user = get_user_model().objects.create_user(**form.cleaned_data)
                Membership.objects.create(user=user, workspace=request.membership.workspace, role='assistant')
                AuditEvent.objects.create(workspace=request.membership.workspace, actor=request.user, action='assistant.created', detail=f'User {user.pk}')
        except IntegrityError:
            form.add_error(None, 'This username is already in use. Choose another.')
        else:
            messages.success(request, 'Assistant account created. Share their credentials securely; no email was sent.')
            return redirect('mail:team')
    return render(request, 'mail/team.html', {'form': form, 'assistants': request.membership.workspace.memberships.filter(role='assistant', user__is_active=True).select_related('user'), 'active_nav': 'team'})


@member_required
@require_http_methods(['GET', 'POST'])
def merge(request):
    context = {'active_nav': 'merge'}
    if request.method == 'POST' and request.POST.get('action') == 'commit':
        saved = request.session.get('merge_preview')
        token = request.POST.get('merge_token', '')
        if not saved or not constant_time_compare(saved['token'], token) or timezone.now().timestamp() - saved['at'] > 1800 or saved['user'] != request.user.pk:
            return HttpResponseBadRequest('The preview expired or is invalid. Upload the CSV and preview again.')
        # The unique receipt is the first query in this transaction. A preceding
        # SELECT can cause two SQLite readers to deadlock while upgrading their
        # transactions to writes. Insert-first serializes duplicate commits.
        from .models import MergeReceipt
        try:
            with transaction.atomic():
                MergeReceipt.objects.create(token=token, user=request.user)
                for row in saved['rows']:
                    item = Message(workspace=request.membership.workspace, created_by=request.user, send_date=saved['send_date'], **row)
                    item.full_clean()
                    item.save()
                    AuditEvent.objects.create(workspace=item.workspace, actor=request.user, message=item, action='merge.created')
        except IntegrityError:
            if not MergeReceipt.objects.filter(token=token, user=request.user).exists():
                raise
            request.session.pop('merge_preview', None)
            messages.info(request, 'These drafts have already been created.')
            return redirect('mail:dashboard')
        except OperationalError as exc:
            sqlite_code = getattr(exc.__cause__, 'sqlite_errorcode', 0)
            if connection.vendor != 'sqlite' or sqlite_code & 0xFF not in (5, 6):
                raise
            # SQLite can reject a competing writer immediately in shared-cache
            # mode or after its busy timeout. The whole batch was rolled back;
            # keep its preview available for a safe, receipt-protected retry.
            return render(request, 'mail/error.html', {
                'heading': 'Workspace is busy',
                'detail': 'Another update is finishing. Return to your preview and create these drafts again. Duplicate drafts will not be created.',
            }, status=409)
        request.session.pop('merge_preview', None)
        messages.success(request, f"Created {len(saved['rows'])} drafts. No messages were sent.")
        return redirect('mail:dashboard')
    form = MergeForm(request.POST if request.method == 'POST' else None, request.FILES or None, initial={'send_date': timezone.localdate()})
    if request.method == 'POST' and form.is_valid():
        try:
            data = form.cleaned_data
            rows = merge_preview(data['csv_file'], data['subject'], data['body'], data['cc'], data['bcc'])
        except ValidationError as exc:
            form.add_error(None, exc)
        else:
            token = secrets.token_urlsafe(32)
            request.session['merge_preview'] = {'token': token, 'rows': rows, 'send_date': data['send_date'].isoformat(), 'at': timezone.now().timestamp(), 'user': request.user.pk}
            context.update(preview_rows=rows, merge_token=token, preview_send_date=data['send_date'])
    context['form'] = form
    return render(request, 'mail/merge.html', context)


@member_required
@require_http_methods(['GET'])
def inbox(request):
    return render(request, 'mail/inbox.html', {'active_nav': 'inbox'})


@member_required
@require_http_methods(['GET'])
def attachment(request, pk):
    item = get_object_or_404(Attachment.objects.filter(message__in=visible_messages(request.user)), pk=pk)
    try:
        response = FileResponse(item.file.open('rb'), as_attachment=True, filename=item.original_name, content_type='application/octet-stream')
    except FileNotFoundError:
        raise Http404('The attachment file is no longer available.')
    response['Cache-Control'] = 'private, no-store'
    return response
