from django.contrib import messages
from django.db import transaction
from django.db.models import F
from django.shortcuts import get_object_or_404, redirect, render
from django.http import HttpResponseBadRequest
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from .models import SenderAccount, Message, AuditEvent
from .services import require_executive
from .views import member_required


@member_required
@require_http_methods(['GET', 'POST'])
def senders(request):
    member = require_executive(request.user)
    if request.method == 'POST':
        try:
            sender_id = int(request.POST.get('sender', ''))
        except (TypeError, ValueError):
            return HttpResponseBadRequest('Choose a sender from this workspace.')
        with transaction.atomic():
            sender = get_object_or_404(SenderAccount.objects.select_for_update(), workspace=member.workspace, pk=sender_id)
            if request.POST.get('action') == 'disconnect':
                sender.connected = False
                sender.encrypted_data = ''
                sender.save(update_fields=['connected', 'encrypted_data', 'updated_at'])
                Message.objects.filter(sender=sender, status__in=['draft', 'failed']).update(version=F('version') + 1, updated_at=timezone.now())
                AuditEvent.objects.create(workspace=member.workspace, actor=request.user, action='sender.disconnected', detail=sender.email)
                messages.success(request, 'Sender disconnected. Its drafts must be reassigned or the sender reconnected before sending.')
        return redirect('mail:senders')
    return render(request, 'mail/senders.html', {'senders': member.workspace.senders.all(), 'active_nav': 'senders'})
