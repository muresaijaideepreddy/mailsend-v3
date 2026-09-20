from django.db import DatabaseError
from django.db.migrations.exceptions import InconsistentMigrationHistory
from django.http import JsonResponse
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_safe

from .readiness import database_ready


@never_cache
@require_safe
def health(request):
    request.get_host()  # Validate the host even though this response has no URLs.
    try:
        ready = database_ready()
    except (DatabaseError, InconsistentMigrationHistory, OSError):
        ready = False
    return JsonResponse({'status': 'ready' if ready else 'unavailable'}, status=200 if ready else 503)
