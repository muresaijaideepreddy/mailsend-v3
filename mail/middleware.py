from django.utils.cache import patch_cache_control


class PrivatePageMiddleware:
    """Prevent shared/browser caches from retaining authenticated mail pages."""
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        if getattr(request, 'user', None) and request.user.is_authenticated:
            patch_cache_control(response, private=True, no_store=True, max_age=0)
        response['Permissions-Policy'] = 'camera=(), microphone=(), geolocation=()'
        return response
