"""D5: every uniqueness row in phase 1 has a concurrency test on real connections."""

import pytest
from django.db import IntegrityError

from commerce_core.accounts.models import User
from tests.concurrency.helpers import run_concurrently

pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.concurrency]


def test_email_concurrent_insert_one_wins():
    def register(email):
        def work(barrier):
            user = User(email=email)
            user.set_unusable_password()
            barrier.wait()
            user.save(force_insert=True)
            return user.pk

        return work

    outcomes = run_concurrently(register("Race@x.com"), register("race@X.com"))
    winners = [r for r, e in outcomes if e is None]
    losers = [e for r, e in outcomes if e is not None]
    assert len(winners) == 1
    assert len(losers) == 1 and isinstance(losers[0], IntegrityError)
    assert "accounts_user_email_ci_uniq" in str(losers[0])
    assert User.objects.filter(email="race@x.com").count() == 1


def test_runtimesetting_unique_nulls_not_distinct():
    from commerce_core.platform.models import RuntimeSetting

    RuntimeSetting.objects.all().delete()

    def insert(barrier):
        barrier.wait()
        return RuntimeSetting.objects.create(kind="checkout_kill_switch", enabled=False).pk

    outcomes = run_concurrently(insert, insert)
    assert sum(1 for r, e in outcomes if e is None) == 1
    loser = next(e for r, e in outcomes if e is not None)
    assert isinstance(loser, IntegrityError)
    assert "runtimesetting_kind_provider_uniq" in str(loser)


def test_two_schedulers_enqueue_each_run_once():
    from datetime import timedelta

    from django.utils import timezone
    from django_tasks_db.models import DBTaskResult

    from commerce_core.platform.jobs.registry import JOBS, sync_schedules
    from commerce_core.platform.jobs.scheduler import tick
    from commerce_core.platform.models import JobSchedule

    sync_schedules()
    now = timezone.now()
    JobSchedule.objects.update(next_run_at=now - timedelta(seconds=1))

    def scheduler(barrier):
        barrier.wait()
        return tick(now)

    outcomes = run_concurrently(scheduler, scheduler)
    assert all(e is None for _, e in outcomes)
    enqueued = [name for result, _ in outcomes for name in result]
    assert sorted(enqueued) == sorted(JOBS)
    assert DBTaskResult.objects.count() == len(JOBS)


def test_business_day_marker_concurrent_insert_one_wins():
    from datetime import date

    from commerce_core.platform.models import BusinessDayRun

    def mark(barrier):
        barrier.wait()
        return BusinessDayRun.objects.create(job_name="report", local_date=date(2026, 3, 29)).pk

    outcomes = run_concurrently(mark, mark)
    assert sum(1 for _, e in outcomes if e is None) == 1
    assert "businessdayrun_job_date_uniq" in str(next(e for _, e in outcomes if e))


def test_alert_retry_on_two_connections_keeps_one_open_alert():
    from commerce_core.platform.alerts.services import raise_alert
    from commerce_core.platform.models import Alert

    def raise_it(barrier):
        barrier.wait()
        return raise_alert("job_stale", "job", "race")

    outcomes = run_concurrently(raise_it, raise_it, raise_it)
    assert all(e is None for _, e in outcomes)
    assert len({r for r, _ in outcomes}) == 1
    alert = Alert.objects.get(code="job_stale", subject_id="race")
    assert alert.raise_count == 3


def test_rate_limit_holds_at_boundary_under_concurrency():
    """A9, A9a: ten requests on ten connections against a limit of five: exactly five pass."""
    from datetime import timedelta

    from commerce_core.platform.ratelimit import store
    from commerce_core.platform.ratelimit.policies import RateLimitPolicy

    policy = RateLimitPolicy("race", "ip", timedelta(minutes=15), 5)

    def request(barrier):
        barrier.wait()
        return store.hit(policy, "203.0.113.7").allowed

    outcomes = run_concurrently(*[request] * 10)
    assert all(e is None for _, e in outcomes)
    assert sum(1 for allowed, _ in outcomes if allowed) == 5
