"""Health, split in three (N3, N6, W3).

* ``/health``: public liveness. 200 when the database answers, 503 otherwise.
  Empty body. Job staleness never appears here.
* ``/health/jobs``: public. 200 when no registered job is stale, 503 when one
  is. Empty body: no job names, no timestamps.
* ``/health/detail``: a staff session (TOTP-verified) or the monitoring token.
  Each job's last success, the core version and open critical alerts. The
  token opens this view and nothing else; the previous token is accepted only
  inside its rotation window.
"""

import hmac
from importlib.metadata import PackageNotFoundError, version

from django.db import DatabaseError, connection
from django.http import HttpResponse, JsonResponse
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET

from commerce_core.platform.conf import get_setting
from commerce_core.platform.errors.exceptions import Unauthenticated
from commerce_core.platform.errors.handlers import response_for


def core_version() -> str:
    try:
        return version("commerce-core")
    except PackageNotFoundError:
        return "unknown"


def _empty(status: int) -> HttpResponse:
    return HttpResponse(status=status, content=b"")


@never_cache
@require_GET
def health(request):
    try:
        with connection.cursor() as cur:
            cur.execute("SELECT 1")
    except DatabaseError:
        return _empty(503)
    return _empty(200)


@never_cache
@require_GET
def health_jobs(request):
    from commerce_core.platform.jobs.registry import stale_jobs

    try:
        stale = stale_jobs()
    except DatabaseError:
        return _empty(503)
    return _empty(503 if stale else 200)


def _bearer(request) -> str | None:
    header = request.headers.get("Authorization", "")
    scheme, _, token = header.partition(" ")
    return token.strip() if scheme.lower() == "bearer" and token.strip() else None


def monitoring_token_valid(token: str, now=None) -> bool:
    now = now or timezone.now()
    current = get_setting("MONITORING_TOKEN")
    if current and hmac.compare_digest(token.encode(), current.encode()):
        return True
    previous = get_setting("MONITORING_TOKEN_PREVIOUS")
    rotated_at = get_setting("MONITORING_TOKEN_ROTATED_AT")
    if previous and rotated_at is not None:
        in_window = now < rotated_at + get_setting("MONITORING_TOKEN_ROTATION_WINDOW")
        # Compare first, then check the window, so timing does not reveal which failed.
        matches = hmac.compare_digest(token.encode(), previous.encode())
        return matches and in_window
    return False


def _staff_session(request) -> bool:
    user = getattr(request, "user", None)
    return bool(user and user.is_active and user.is_staff and user.is_verified())


@never_cache
@require_GET
def health_detail(request):
    from commerce_core.platform.jobs.registry import JOBS, stale_jobs
    from commerce_core.platform.models import Alert, AlertSeverity, AlertStatus, JobSchedule

    token = _bearer(request)
    if not (_staff_session(request) or (token and monitoring_token_valid(token))):
        return response_for(Unauthenticated(), request)

    now = timezone.now()
    rows = {r.name: r for r in JobSchedule.objects.filter(name__in=list(JOBS))}
    stale = set(stale_jobs(now))
    alerts = (
        Alert.objects.filter(severity=AlertSeverity.CRITICAL)
        .exclude(status=AlertStatus.RESOLVED)
        .order_by("first_raised_at")
        .values("code", "subject_type", "subject_id", "status", "first_raised_at")[:100]
    )
    return JsonResponse(
        {
            "version": core_version(),
            "jobs": [
                {
                    "name": name,
                    "last_succeeded_at": (
                        rows[name].last_succeeded_at.isoformat()
                        if name in rows and rows[name].last_succeeded_at
                        else None
                    ),
                    "stale": name in stale,
                }
                for name in sorted(JOBS)
            ],
            "open_critical_alerts": [
                {**a, "first_raised_at": a["first_raised_at"].isoformat()} for a in alerts
            ],
        }
    )
