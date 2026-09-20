from django import forms
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import SetPasswordForm
from django.shortcuts import get_object_or_404, redirect, render
from django.db import transaction
from django.views.decorators.http import require_http_methods
from .models import AuditEvent, Membership
from .services import require_executive
from .views import member_required


class AssistantProfileForm(forms.ModelForm):
    class Meta:
        model = get_user_model()
        fields = ['first_name']
        labels = {'first_name': 'Name'}
        widgets = {'first_name': forms.TextInput(attrs={'class': 'form-control'})}


@member_required
@require_http_methods(['GET', 'POST'])
def assistant_profile(request, pk):
    member = require_executive(request.user)
    with transaction.atomic():
        assistant = get_object_or_404(Membership.objects.select_related('user'), pk=pk, workspace=member.workspace, role='assistant')
        user = get_user_model().objects.select_for_update().get(pk=assistant.user_id)
        form = AssistantProfileForm(request.POST if request.method == 'POST' else None, instance=user)
        if request.method == 'POST' and form.is_valid():
            form.save()
            AuditEvent.objects.create(workspace=member.workspace, actor=request.user, action='assistant.profile_updated', detail=f'User {user.pk}')
            messages.success(request, 'Worker details saved. Assistants sign in with their assigned username and password.')
            return redirect('mail:team')
    return render(request, 'mail/assistant_profile.html', {'form': form, 'assistant': assistant, 'active_nav': 'team'})


@member_required
@require_http_methods(['GET', 'POST'])
def assistant_password(request, pk):
    member = require_executive(request.user)
    assistant = get_object_or_404(Membership.objects.select_related('user'), pk=pk, workspace=member.workspace, role='assistant')
    form = SetPasswordForm(assistant.user, request.POST if request.method == 'POST' else None)
    if request.method == 'POST' and form.is_valid():
        form.save()
        AuditEvent.objects.create(workspace=member.workspace, actor=request.user, action='assistant.password_changed', detail=f'User {assistant.user_id}')
        messages.success(request, 'Assistant password changed. Their existing sessions will be signed out. Share the new password securely.')
        return redirect('mail:team')
    return render(request, 'mail/assistant_password.html', {'form': form, 'assistant': assistant, 'active_nav': 'team'})
