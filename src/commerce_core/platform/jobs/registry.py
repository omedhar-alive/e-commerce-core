"""The job registry: every scheduled job, declared once (N4, N4a, L1a).

Each job has a name, a schedule in UTC and a maximum staleness. No job is
scheduled anywhere else: not in platform cron, not by a hand-written enqueue
(a test enforces the second). ``run_scheduler`` enqueues due jobs;
``/health/jobs`` and the staleness check read the registry.
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta

from django.utils import timezone
from django_tasks import task


@dataclass(frozen=True)
class Every:
    interval: timedelta

    def next_after(self, moment: datetime) -> datetime:
        return moment + self.interval


@dataclass(frozen=True)
class DailyAtUTC:
    at: time

    def next_after(self, moment: datetime) -> datetime:
        candidate = datetime.combine(moment.date(), self.at, tzinfo=UTC)
        if candidate <= moment:
            candidate += timedelta(days=1)
        return candidate


@dataclass(frozen=True)
class JobSpec:
    name: str
    schedule: Every | DailyAtUTC
    max_staleness: timedelta
    fn: Callable[[], None]
    description: str = ""


JOBS: dict[str, JobSpec] = {}


def register(name: str, *, schedule, max_staleness: timedelta, description: str = ""):
    """Declare ``fn`` as the scheduled job ``name``."""

    def decorator(fn: Callable[[], None]):
        if name in JOBS:
            raise ValueError(f"job {name!r} registered twice")
        JOBS[name] = JobSpec(name, schedule, max_staleness, fn, description or (fn.__doc__ or ""))
        return fn

    return decorator


class UnknownJob(LookupError):
    pass


@task()
def run_registered_job(name: str) -> None:
    """The one task the scheduler enqueues. Records start and success on the schedule row."""
    from commerce_core.platform.models import JobSchedule

    spec = JOBS.get(name)
    if spec is None:
        raise UnknownJob(name)
    JobSchedule.objects.filter(name=name).update(last_started_at=timezone.now())
    spec.fn()
    JobSchedule.objects.filter(name=name).update(last_succeeded_at=timezone.now())


def staleness_reference(row) -> datetime:
    return row.last_succeeded_at or row.created_at


def stale_jobs(now: datetime | None = None) -> list[str]:
    """Registered jobs whose last success (or creation) is older than their max staleness.

    A registered job with no schedule row counts as stale.
    """
    from commerce_core.platform.models import JobSchedule

    now = now or timezone.now()
    rows = {r.name: r for r in JobSchedule.objects.filter(name__in=list(JOBS))}
    stale = []
    for name, spec in JOBS.items():
        row = rows.get(name)
        if row is None or now - staleness_reference(row) > spec.max_staleness:
            stale.append(name)
    return sorted(stale)


def sync_schedules(now: datetime | None = None) -> list[str]:
    """Create a ``JobSchedule`` row for every registered job that lacks one. Returns the names added."""
    from commerce_core.platform.models import JobSchedule

    now = now or timezone.now()
    existing = set(JobSchedule.objects.filter(name__in=list(JOBS)).values_list("name", flat=True))
    missing = [name for name in JOBS if name not in existing]
    JobSchedule.objects.bulk_create(
        [JobSchedule(name=name, next_run_at=now, created_at=now) for name in missing],
        ignore_conflicts=True,
    )
    return missing


def missing_schedules() -> list[str]:
    from commerce_core.platform.models import JobSchedule

    existing = set(JobSchedule.objects.filter(name__in=list(JOBS)).values_list("name", flat=True))
    return sorted(set(JOBS) - existing)
