"""The in-core scheduler (N4a; decision 14).

``tick()`` claims every due ``JobSchedule`` row with
``SELECT … FOR UPDATE SKIP LOCKED``, advances ``next_run_at`` and records
``last_enqueued_at`` in the same transaction, and enqueues the run on
commit (T2). A second scheduler skips rows the first holds, so a run is
never enqueued twice.
"""

import logging
from datetime import datetime

from django.db import transaction
from django.utils import timezone

from commerce_core.platform.jobs.registry import JOBS, run_registered_job

logger = logging.getLogger("commerce_core.scheduler")


def tick(now: datetime | None = None) -> list[str]:
    """Enqueue every due job once. Returns the names enqueued."""
    from commerce_core.platform.models import JobSchedule

    now = now or timezone.now()
    enqueued: list[str] = []
    with transaction.atomic():
        due = list(
            JobSchedule.objects.select_for_update(skip_locked=True)
            .filter(name__in=list(JOBS), next_run_at__lte=now)
            .order_by("next_run_at")
        )
        for row in due:
            spec = JOBS[row.name]
            JobSchedule.objects.filter(pk=row.pk).update(
                next_run_at=spec.schedule.next_after(now), last_enqueued_at=now
            )
            transaction.on_commit(lambda name=row.name: run_registered_job.enqueue(name))
            enqueued.append(row.name)
    if enqueued:
        logger.info("enqueued jobs", extra={"jobs": enqueued})
    return enqueued
