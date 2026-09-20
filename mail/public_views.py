"""Public service information; never expose workspace records."""

from django.shortcuts import render
from django.views.decorators.http import require_safe


@require_safe
def about(request):
    return render(request, 'mail/public/about.html')


@require_safe
def privacy(request):
    return render(request, 'mail/public/privacy.html')


@require_safe
def terms(request):
    return render(request, 'mail/public/terms.html')
