"""N4, N4a, decision 14 and 26: registered jobs, one scheduler, recorded runs."""

import ast
import inspect
from datetime import timedelta
from pathlib import Path

import pytest
from django.core.management import call_command
from django.utils import timezone
from django_tasks.base import TaskResultStatus
from django_tasks_db.models import DBTaskResult

import commerce_core
from commerce_core.platform.jobs import registry
from commerce_core.platform.jobs.registry import (
    JOBS,
    run_registered_job,
    stale_jobs,
    sync_schedules,
)
from commerce_core.platform.jobs.scheduler import tick
from commerce_core.platform.models import JobSchedule

pytestmark = pytest.mark.django_db


def test_task_result_pruning_is_registered():
    spec = JOBS["task_result_pruning"]
    assert spec.max_staleness > spec.schedule.interval


def test_every_registered_job_has_a_schedule_row_after_release():
    assert registry.missing_schedules() == []
    assert set(JobSchedule.objects.values_list("name", flat=True)) >= set(JOBS)


def test_sync_is_idempotent():
    assert sync_schedules() == []


def test_tick_enqueues_each_due_job_once_and_advances(django_capture_on_commit_callbacks):
    now = timezone.now()
    JobSchedule.objects.update(next_run_at=now - timedelta(seconds=1))
    with django_capture_on_commit_callbacks(execute=True):
        first = tick(now)
    assert sorted(first) == sorted(JOBS)
    assert DBTaskResult.objects.filter(status=TaskResultStatus.READY).count() == len(JOBS)
    with django_capture_on_commit_callbacks(execute=True):
        assert tick(now) == []
    for row in JobSchedule.objects.all():
        assert row.last_enqueued_at == now
        assert row.next_run_at > now


def test_nothing_is_enqueued_before_commit(django_capture_on_commit_callbacks):
    JobSchedule.objects.update(next_run_at=timezone.now() - timedelta(seconds=1))
    with django_capture_on_commit_callbacks(execute=False) as callbacks:
        tick()
    assert DBTaskResult.objects.count() == 0
    assert len(callbacks) == len(JOBS)


def test_run_records_start_and_success(monkeypatch):
    calls = []
    monkeypatch.setitem(
        JOBS,
        "probe",
        registry.JobSpec(
            "probe", registry.Every(timedelta(hours=1)), timedelta(hours=2), lambda: calls.append(1)
        ),
    )
    JobSchedule.objects.create(name="probe", next_run_at=timezone.now())
    run_registered_job.call("probe")
    row = JobSchedule.objects.get(name="probe")
    assert calls == [1] and row.last_started_at and row.last_succeeded_at


def test_failed_run_records_start_only(monkeypatch):
    def boom():
        raise RuntimeError("job failed")

    monkeypatch.setitem(
        JOBS,
        "probe",
        registry.JobSpec("probe", registry.Every(timedelta(hours=1)), timedelta(hours=2), boom),
    )
    JobSchedule.objects.create(name="probe", next_run_at=timezone.now())
    with pytest.raises(RuntimeError):
        run_registered_job.call("probe")
    row = JobSchedule.objects.get(name="probe")
    assert row.last_started_at and row.last_succeeded_at is None


def test_staleness():
    now = timezone.now()
    JobSchedule.objects.update(created_at=now, last_succeeded_at=None)
    assert stale_jobs(now) == []
    spec = JOBS["task_result_pruning"]
    assert stale_jobs(now + spec.max_staleness + timedelta(seconds=1)) == ["task_result_pruning"]
    JobSchedule.objects.update(last_succeeded_at=now + spec.max_staleness)
    assert stale_jobs(now + spec.max_staleness + timedelta(seconds=1)) == []


def test_a_registered_job_without_a_row_is_stale():
    JobSchedule.objects.filter(name="task_result_pruning").delete()
    assert "task_result_pruning" in stale_jobs()


def test_daily_schedule_is_in_utc():
    from datetime import UTC, datetime, time

    daily = registry.DailyAtUTC(time(3, 0))
    assert daily.next_after(datetime(2026, 3, 29, 2, 0, tzinfo=UTC)) == datetime(
        2026, 3, 29, 3, 0, tzinfo=UTC
    )
    assert daily.next_after(datetime(2026, 3, 29, 3, 0, tzinfo=UTC)) == datetime(
        2026, 3, 30, 3, 0, tzinfo=UTC
    )


def _result(status, finished_at):
    return DBTaskResult.objects.create(
        status=status,
        finished_at=finished_at,
        args_kwargs={"args": [], "kwargs": {}},
        task_path="commerce_core.platform.jobs.registry.run_registered_job",
        queue_name="default",
        backend_name="default",
        run_after=timezone.now(),
    )


def test_task_result_pruning_only_finished_past_retention():
    old = timezone.now() - timedelta(days=8)
    recent = timezone.now() - timedelta(days=6)
    gone = [_result(TaskResultStatus.SUCCESSFUL, old), _result(TaskResultStatus.FAILED, old)]
    kept = [
        _result(TaskResultStatus.SUCCESSFUL, recent),
        _result(TaskResultStatus.READY, None),
        _result(TaskResultStatus.RUNNING, None),
    ]
    JOBS["task_result_pruning"].fn()
    remaining = set(DBTaskResult.objects.values_list("pk", flat=True))
    assert remaining == {r.pk for r in kept}
    assert not remaining & {r.pk for r in gone}


def test_no_periodic_enqueue_outside_the_scheduler():
    """N4a: only the scheduler enqueues registered jobs."""
    root = Path(inspect.getfile(commerce_core)).parent
    offenders = []
    for path in root.rglob("*.py"):
        if path.name == "scheduler.py" and path.parent.name == "jobs":
            continue
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.Attribute) and node.attr == "enqueue":
                offenders.append(str(path.relative_to(root)))
    assert offenders == []


@pytest.mark.django_db(transaction=True)
def test_worker_runs_an_enqueued_job_end_to_end():
    sync_schedules()
    JobSchedule.objects.update(next_run_at=timezone.now() - timedelta(seconds=1))
    tick()
    call_command("run_worker", "--batch")
    assert JobSchedule.objects.exclude(last_succeeded_at=None).count() == len(JOBS)


def test_scheduler_refuses_to_start_without_rows():
    from django.core.management import CommandError

    JobSchedule.objects.all().delete()
    with pytest.raises(CommandError, match="without a JobSchedule row"):
        call_command("run_scheduler", "--once")
