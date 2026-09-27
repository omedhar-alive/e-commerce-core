"""Business-day jobs run keyed on the store-local date, once per date (L1, L1a).

Jobs are scheduled in UTC (N4a). A job tied to a business day calls
``run_for_local_date``: it computes the store-local date of ``now`` in
``STORE_TIMEZONE`` and runs ``work(local_date)`` only if no run marker exists
for (job, date). The marker and the work commit together, so a failed run
leaves no marker and a re-run for the same date is a no-op.
"""

import zoneinfo
from collections.abc import Callable
from datetime import UTC, date, datetime, time, timedelta

from django.db import transaction
from django.utils import timezone

from commerce_core.platform.conf import get_setting
from commerce_core.platform.db.savepoint import on_unique_violation

MARKER_CONSTRAINT = "businessdayrun_job_date_uniq"


def store_timezone() -> zoneinfo.ZoneInfo:
    return zoneinfo.ZoneInfo(get_setting("STORE_TIMEZONE"))


def local_date(moment: datetime) -> date:
    return moment.astimezone(store_timezone()).date()


def day_bounds(day: date) -> tuple[datetime, datetime]:
    """UTC instants bounding the store-local ``day``: correct on 23- and 25-hour days (L1)."""
    tz = store_timezone()
    start = datetime.combine(day, time.min, tzinfo=tz)
    end = datetime.combine(day + timedelta(days=1), time.min, tzinfo=tz)
    return start.astimezone(UTC), end.astimezone(UTC)


def run_for_local_date(
    job_name: str, work: Callable[[date], None], now: datetime | None = None
) -> bool:
    """Run ``work`` for the store-local date of ``now`` unless it already ran. Returns whether it ran."""
    from commerce_core.platform.models import BusinessDayRun

    day = local_date(now or timezone.now())
    with transaction.atomic():
        created = on_unique_violation(
            MARKER_CONSTRAINT,
            insert=lambda: (
                BusinessDayRun.objects.create(job_name=job_name, local_date=day) and True
            ),
            on_violation=lambda: False,
        )
        if created:
            work(day)
    return created
