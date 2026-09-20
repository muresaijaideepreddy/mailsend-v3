from django.conf import settings
from django.utils import timezone

def workspace_context(request):
    from .google_api import oauth_configured
    result = {'delivery_mode': settings.MAILSEND_DELIVERY_MODE, 'demo_enabled': settings.MAILSEND_DEMO_ENABLED, 'google_enabled': oauth_configured(), 'send_timezone': timezone.get_current_timezone_name()}
    if request.user.is_authenticated:
        from .models import Membership, GoogleCredential
        membership = Membership.objects.select_related('workspace', 'workspace__executive').filter(user=request.user).first()
        if membership:
            result.update(membership=membership, workspace=membership.workspace, is_executive=membership.role == 'executive', google_connected=GoogleCredential.objects.filter(user=membership.workspace.executive, connected=True).exists(), google_identity_connected=GoogleCredential.objects.filter(user=request.user, subject_hash__isnull=False).exists())
    return result


