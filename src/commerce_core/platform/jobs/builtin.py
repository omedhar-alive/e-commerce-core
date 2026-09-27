"""Jobs core registers in phase 1."""

from datetime import timedelta

from django.utils import timezone

from commerce_core.platform.conf import get_setting
from commerce_core.platform.jobs.registry import Every, register

TASK_RESULT_BATCH = 1000


@register(
    "task_result_pruning",
    schedule=Every(timedelta(hours=6)),
    max_staleness=timedelta(hours=26),
)
def prune_task_results() -> None:
    """Delete finished task results older than TASK_RESULT_RETENTION (decision 26)."""
    from django_tasks.base import TaskResultStatus
    from django_tasks_db.models import DBTaskResult

    cutoff = timezone.now() - get_setting("TASK_RESULT_RETENTION")
    finished = [TaskResultStatus.SUCCESSFUL, TaskResultStatus.FAILED]
    while True:
        batch = list(
            DBTaskResult.objects.filter(status__in=finished, finished_at__lt=cutoff).values_list(
                "pk", flat=True
            )[:TASK_RESULT_BATCH]
        )
        if not batch:
            return
        DBTaskResult.objects.filter(pk__in=batch).delete()
