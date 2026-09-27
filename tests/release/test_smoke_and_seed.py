"""The smoke script against a live server, and seed_demo's idempotency."""

import io

import pytest
from django.core.management import call_command
from django.utils import timezone

from commerce_core.accounts.models import User
from commerce_core.platform.jobs.registry import sync_schedules
from commerce_core.platform.models import JobSchedule
from commerce_core.scripts import smoke
from tests.settings import TEST_ENV


@pytest.mark.django_db(transaction=True)
def test_smoke_script_passes_against_a_live_server(live_server):
    sync_schedules()
    JobSchedule.objects.update(last_succeeded_at=timezone.now())
    results = smoke.run(live_server.url, TEST_ENV["MONITORING_TOKEN"], "0.1.0")
    assert [name for name, ok, _ in results if not ok] == []
    assert len(results) == 7


@pytest.mark.django_db(transaction=True)
def test_smoke_script_fails_on_a_stale_job(live_server):
    sync_schedules()
    JobSchedule.objects.update(
        last_succeeded_at=None, created_at=timezone.now() - timezone.timedelta(days=2)
    )
    failed = [
        name
        for name, ok, _ in smoke.run(live_server.url, TEST_ENV["MONITORING_TOKEN"], "0.1.0")
        if not ok
    ]
    assert failed == ["/health/jobs is 200"]


def test_smoke_script_needs_the_token_in_the_environment(monkeypatch):
    monkeypatch.delenv("MONITORING_TOKEN", raising=False)
    assert smoke.main(["--base-url", "http://127.0.0.1:9"]) == 2


@pytest.mark.django_db
def test_seed_demo_creates_one_staff_user_per_group_and_is_idempotent():
    out = io.StringIO()
    call_command("seed_demo", stdout=out)
    users = User.objects.filter(email__endswith="@demo.invalid")
    assert {u.email.split("@")[0] for u in users} == {"support", "warehouse", "finance"}
    for user in users:
        assert user.is_staff and not user.is_superuser
        assert list(user.groups.values_list("name", flat=True)) == [user.email.split("@")[0]]
    assert out.getvalue().count("otpauth://") == 3
    again = io.StringIO()
    call_command("seed_demo", stdout=again)
    assert "created" not in again.getvalue()
    assert users.count() == 3
