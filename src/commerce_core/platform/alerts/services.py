"""Raising and handling alerts (N5).

``raise_alert()`` runs inside the caller's transaction, so the alert commits
or rolls back with the condition it reports. One statement,
``INSERT … ON CONFLICT … DO UPDATE``, against the partial unique index on
(code, subject) while not resolved: a retry updates the open row instead of
opening a second one.
"""

import json

from django.db import connection, transaction
from django.utils import timezone

from commerce_core.platform.actors import Actor
from commerce_core.platform.alerts.codes import ALERT_CODES
from commerce_core.platform.errors.exceptions import NotFound, ValidationFailed
from commerce_core.platform.models import Alert, AlertStatus

_UPSERT = """
INSERT INTO platform_alert (
    code, severity, subject_type, subject_id, status, context,
    first_raised_at, last_raised_at, raise_count,
    acknowledged_by_type, acknowledged_by_id, resolved_by_type, resolved_by_id
) VALUES (%s, %s, %s, %s, 'open', %s, %s, %s, 1, '', '', '', '')
ON CONFLICT (code, subject_type, subject_id) WHERE status <> 'resolved'
DO UPDATE SET last_raised_at = EXCLUDED.last_raised_at,
              raise_count = platform_alert.raise_count + 1,
              context = EXCLUDED.context
RETURNING id
"""


class UnknownAlertCode(LookupError):
    pass


def raise_alert(
    code: str, subject_type: str, subject_id: str | int, context: dict | None = None
) -> int:
    """Open (or refresh) the alert for (code, subject). Returns its id."""
    spec = ALERT_CODES.get(code)
    if spec is None:
        raise UnknownAlertCode(code)
    now = timezone.now()
    with connection.cursor() as cur:
        cur.execute(
            _UPSERT,
            [
                code,
                spec.severity,
                subject_type,
                str(subject_id),
                json.dumps(context or {}),
                now,
                now,
            ],
        )
        return cur.fetchone()[0]


def _transition(alert_id: int, actor: Actor, to: str) -> Alert:
    with transaction.atomic():
        alert = Alert.objects.select_for_update().filter(pk=alert_id).first()
        if alert is None:
            raise NotFound()
        allowed = {
            AlertStatus.ACKNOWLEDGED: {AlertStatus.OPEN},
            AlertStatus.RESOLVED: {AlertStatus.OPEN, AlertStatus.ACKNOWLEDGED},
        }[to]
        if alert.status not in allowed:
            raise ValidationFailed(field="status")
        prefix = "acknowledged" if to == AlertStatus.ACKNOWLEDGED else "resolved"
        fields = {
            "status": to,
            f"{prefix}_at": timezone.now(),
            f"{prefix}_by_type": actor.type,
            f"{prefix}_by_id": actor.id,
        }
        Alert.objects.filter(pk=alert.pk).update(**fields)
        alert.refresh_from_db()
        return alert


def acknowledge_alert(alert_id: int, actor: Actor) -> Alert:
    return _transition(alert_id, actor, AlertStatus.ACKNOWLEDGED)


def resolve_alert(alert_id: int, actor: Actor) -> Alert:
    return _transition(alert_id, actor, AlertStatus.RESOLVED)


def open_alerts(code: str | None = None):
    qs = Alert.objects.exclude(status=AlertStatus.RESOLVED)
    return qs.filter(code=code) if code else qs
