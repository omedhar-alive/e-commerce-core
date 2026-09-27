"""Alert notification and job staleness jobs (N4, N5)."""

import logging
from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from commerce_core.platform.actors import Actor
from commerce_core.platform.alerts.services import open_alerts, raise_alert, resolve_alert
from commerce_core.platform.conf import get_setting
from commerce_core.platform.jobs.registry import Every, register, stale_jobs
from commerce_core.platform.notifications.port import DeliveryFailed, OutboundMessage
from commerce_core.platform.notifications.smtp import email_channel

logger = logging.getLogger("commerce_core.alerts")
BATCH = 50


def _message(alert) -> OutboundMessage:
    subject = f"[{alert.severity}] {alert.code}: {alert.subject_type} {alert.subject_id}"
    body = (
        f"Alert {alert.pk}\n"
        f"Code: {alert.code}\n"
        f"Severity: {alert.severity}\n"
        f"Subject: {alert.subject_type} {alert.subject_id}\n"
        f"First raised: {alert.first_raised_at.isoformat()}\n"
        f"Raised {alert.raise_count} time(s); last at {alert.last_raised_at.isoformat()}\n\n"
        "Acknowledge or resolve it in the admin."
    )
    return OutboundMessage(tuple(get_setting("ALERT_RECIPIENTS")), subject, body)


@register(
    "alert_notification", schedule=Every(timedelta(minutes=1)), max_staleness=timedelta(minutes=15)
)
def notify_alerts() -> None:
    """Email staff about every open alert not yet notified. At-least-once (N5)."""
    from commerce_core.platform.models import Alert

    pending = list(
        open_alerts().filter(notified_at__isnull=True).order_by("first_raised_at")[:BATCH]
    )
    channel = email_channel()
    for alert in pending:
        try:
            channel.send(_message(alert))
        except DeliveryFailed as exc:
            # Left un-notified; the next run retries it.
            logger.warning(
                "alert notification failed",
                extra={"alert_id": alert.pk, "transient": exc.transient},
            )
            continue
        Alert.objects.filter(pk=alert.pk, notified_at__isnull=True).update(
            notified_at=timezone.now()
        )


@register(
    "job_staleness_check", schedule=Every(timedelta(minutes=5)), max_staleness=timedelta(minutes=30)
)
def check_job_staleness() -> None:
    """Open a job_stale alert for each stale job; resolve it when the job recovers (N4)."""
    stale = set(stale_jobs())
    actor = Actor.system("job_staleness_check")
    for name in sorted(stale):
        with transaction.atomic():
            raise_alert("job_stale", "job", name)
    for alert in open_alerts("job_stale").filter(subject_type="job").exclude(subject_id__in=stale):
        resolve_alert(alert.pk, actor)
