"""L1, L1a, L2: store-local days, correct across DST; once per local date."""

from datetime import UTC, date, datetime, timedelta

import pytest

from commerce_core.platform.jobs.business_day import day_bounds, local_date, run_for_local_date
from commerce_core.platform.models import BusinessDayRun

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def berlin(override_setting):
    override_setting("STORE_TIMEZONE", "Europe/Berlin")


def test_spring_forward_day_is_23_hours():
    start, end = day_bounds(date(2026, 3, 29))
    assert start == datetime(2026, 3, 28, 23, 0, tzinfo=UTC)
    assert end == datetime(2026, 3, 29, 22, 0, tzinfo=UTC)
    assert end - start == timedelta(hours=23)


def test_fall_back_day_is_25_hours():
    start, end = day_bounds(date(2026, 10, 25))
    assert end - start == timedelta(hours=25)


def test_local_date_of_a_utc_instant():
    assert local_date(datetime(2026, 3, 28, 23, 30, tzinfo=UTC)) == date(2026, 3, 29)
    assert local_date(datetime(2026, 3, 28, 22, 59, tzinfo=UTC)) == date(2026, 3, 28)


@pytest.mark.parametrize("first_day", [date(2026, 3, 27), date(2026, 10, 23)])
def test_business_day_job_runs_exactly_once_per_local_date_across_dst(first_day):
    runs = []
    moment = datetime.combine(first_day, datetime.min.time(), tzinfo=UTC)
    for _ in range(4 * 24 * 4):  # every 15 minutes for four days
        run_for_local_date("probe_report", runs.append, now=moment)
        moment += timedelta(minutes=15)
    assert len(runs) == len(set(runs))
    assert runs == [runs[0] + timedelta(days=i) for i in range(len(runs))]
    assert BusinessDayRun.objects.filter(job_name="probe_report").count() == len(runs)


def test_failed_run_leaves_no_marker_and_reruns():
    def boom(day):
        raise RuntimeError("report failed")

    now = datetime(2026, 5, 1, 12, tzinfo=UTC)
    with pytest.raises(RuntimeError):
        run_for_local_date("probe_report", boom, now=now)
    assert not BusinessDayRun.objects.exists()
    assert run_for_local_date("probe_report", lambda day: None, now=now) is True
    assert run_for_local_date("probe_report", lambda day: None, now=now) is False


def test_timestamps_are_stored_in_utc():
    from django.conf import settings

    assert settings.USE_TZ is True and settings.TIME_ZONE == "UTC"
