from django.db import connections
from django.db.utils import OperationalError
from django.http import JsonResponse


def health_check(request):
    """
    GET /healthz/ — used by Render (and any uptime monitor) to know whether
    this instance is actually serving traffic correctly, not just that the
    process is alive. Checks the DB connection since that's the most common
    way an otherwise-running instance is actually broken.
    """
    db_ok = True
    try:
        connections['default'].cursor()
    except OperationalError:
        db_ok = False

    status = 200 if db_ok else 503
    return JsonResponse({'status': 'ok' if db_ok else 'error', 'database': db_ok}, status=status)
