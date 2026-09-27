"""D2a, D2h, D3, W5, W6: the release step."""

import io
import time

import pytest
from django.db import connection
from psycopg import errors

from commerce_core.platform.db import roles
from commerce_core.platform.models import ReleaseRecord
from commerce_core.platform.release import run
from commerce_core.platform.release.run import (
    ReleaseRefused,
    check_forwards_only,
    check_restore_point,
    check_version_gate,
    migrate_with_retry,
)
from commerce_core.platform.release.safety import Finding
from tests import harness

DESTRUCTIVE = [Finding("platform", "0099_drop", "destructive", "RemoveField x.y")]


@pytest.mark.parametrize("env", ["production", "demo", "local", "test"])
def test_destructive_migration_refused_without_restore_point_in_every_environment(env):
    with pytest.raises(ReleaseRefused, match="--restore-point"):
        check_restore_point(DESTRUCTIVE, "", env)


@pytest.mark.parametrize("env", ["demo", "local", "test"])
def test_restore_point_accepted_and_returned_outside_production(env):
    assert check_restore_point(DESTRUCTIVE, "neon-branch-br_123", env) == ["platform.0099_drop"]


def test_production_destructive_migration_needs_verified_restore_point():
    with pytest.raises(ReleaseRefused, match="D4"):
        check_restore_point(DESTRUCTIVE, "pitr-2026-09-27T10:00Z", "production")


def test_non_destructive_needs_no_restore_point():
    assert check_restore_point([Finding("a", "b", "blocking", "x")], "", "production") == []


@pytest.mark.django_db
@pytest.mark.parametrize("env", ["production", "demo"])
def test_release_step_refuses_before_migrating(monkeypatch, override_setting, env):
    override_setting("DEPLOYMENT_ENV", env)
    monkeypatch.setattr(run, "classify", lambda *a, **k: DESTRUCTIVE)
    migrated = []
    monkeypatch.setattr(run, "migrate_with_retry", lambda *a, **k: migrated.append(1))
    with pytest.raises(ReleaseRefused):
        run.run_release(restore_point="")
    assert migrated == []


@pytest.mark.django_db(transaction=True)
def test_restore_point_is_recorded_with_the_release(monkeypatch):
    monkeypatch.setattr(run, "classify", lambda *a, **k: DESTRUCTIVE)
    monkeypatch.setattr(run, "migrate_with_retry", lambda *a, **k: 1)
    with harness.as_role(roles.MIGRATION):  # the release step's role
        record = run.run_release(restore_point="dump-2026-09-27.sql", stdout=io.StringIO())
    record = ReleaseRecord.objects.get(pk=record.pk)
    assert record.restore_point == "dump-2026-09-27.sql"
    assert record.restore_point_verified is False
    assert record.destructive_migrations == ["platform.0099_drop"]
    assert record.core_version == "0.1.0"


class _Migration:
    def __init__(self, app, name):
        self.app_label, self.name = app, name


def test_production_refuses_a_backwards_plan():
    plan = [(_Migration("platform", "0005_releaserecord"), True)]
    with pytest.raises(ReleaseRefused, match="D2h"):
        check_forwards_only(plan, "production")
    check_forwards_only(plan, "local")


@pytest.mark.parametrize(
    "current, recorded, ok",
    [
        ("0.2.0", "0.1.0", True),
        ("0.2.3", "0.2.1", True),
        ("0.3.0", "0.1.0", False),
        ("1.0.0", "0.11.0", False),
        ("0.1.0", "0.2.0", True),  # code rollback: nothing new to migrate
        ("0.1.0", None, True),
    ],
)
def test_one_minor_version_at_a_time(current, recorded, ok):
    if ok:
        check_version_gate(current, recorded)
    else:
        with pytest.raises(ReleaseRefused, match="W5"):
            check_version_gate(current, recorded)


@pytest.mark.django_db(transaction=True)
def test_release_refuses_a_deployment_two_minors_behind(monkeypatch):
    monkeypatch.setattr(run, "core_version", lambda: "0.3.0")
    with harness.as_role(roles.MIGRATION):  # the release step's role
        ReleaseRecord.objects.create(core_version="0.1.0", deployment_env="test")
        with pytest.raises(ReleaseRefused, match="W5"):
            run.run_release()


# D6, W5: only the release step writes release history.


@pytest.mark.django_db
@pytest.mark.parametrize("role", roles.DML_ROLES)
def test_web_and_job_cannot_insert_a_release_record(role_conn, role):
    conn = role_conn(role)
    with pytest.raises(errors.InsufficientPrivilege):
        conn.execute(
            "INSERT INTO platform_releaserecord (core_version, deployment_env, restore_point,"
            " restore_point_verified, destructive_migrations, applied_migrations, applied_at)"
            " VALUES ('9.9.9', 'test', '', false, '[]', '[]', now())"
        )


@pytest.mark.django_db
def test_web_process_cannot_record_a_release():
    from django.db import transaction
    from django.db.utils import ProgrammingError

    with pytest.raises(ProgrammingError, match="permission denied"), transaction.atomic():
        ReleaseRecord.objects.create(core_version="9.9.9", deployment_env="test")


@pytest.mark.django_db(transaction=True)
def test_the_release_step_still_records_a_release():
    with harness.as_role(roles.MIGRATION):
        before = ReleaseRecord.objects.count()
        record = run.run_release(stdout=io.StringIO())
        assert ReleaseRecord.objects.count() == before + 1
    assert record.core_version == "0.1.0" and record.applied_migrations == []


def _lock_timeout():
    from django.db import OperationalError

    exc = OperationalError("canceling statement due to lock timeout")
    exc.__cause__ = errors.LockNotAvailable("lock timeout")
    return exc


def test_lock_timeout_retries_with_exponential_backoff():
    attempts, sleeps = [], []

    def migrate():
        attempts.append(1)
        if len(attempts) < 3:
            raise _lock_timeout()

    assert migrate_with_retry(migrate, retries=5, sleep=sleeps.append) == 3
    assert sleeps == [1, 2]


def test_lock_timeout_fails_the_deploy_after_the_last_retry():
    sleeps = []

    def migrate():
        raise _lock_timeout()

    with pytest.raises(ReleaseRefused, match="D2a"):
        migrate_with_retry(migrate, retries=2, sleep=sleeps.append)
    assert sleeps == [1, 2]


def test_other_database_errors_are_not_retried():
    from django.db import OperationalError

    def migrate():
        raise OperationalError("disk full")

    with pytest.raises(OperationalError, match="disk full"):
        migrate_with_retry(migrate, retries=5, sleep=lambda s: pytest.fail("slept"))


@pytest.mark.django_db(transaction=True)
def test_real_migration_lock_fails_at_three_seconds_and_retries(role_conn):
    """D2a on a real lock: the migration role's DDL gives up after ~3 s; the retry then succeeds."""
    holder = role_conn(roles.JOB, autocommit=False)
    holder.execute("SELECT count(*) FROM testapp_lockprobe")  # takes ACCESS SHARE until rollback
    durations = []

    def migrate():
        started = time.monotonic()
        try:
            with connection.cursor() as cur:
                cur.execute("ALTER TABLE testapp_lockprobe ADD COLUMN release_probe int")
        finally:
            durations.append(time.monotonic() - started)

    def sleep(seconds):
        holder.rollback()  # the blocking reader finishes during the backoff

    with harness.as_role(roles.MIGRATION):
        try:
            assert migrate_with_retry(migrate, retries=3, sleep=sleep) == 2
        finally:
            with connection.cursor() as cur:
                cur.execute("ALTER TABLE testapp_lockprobe DROP COLUMN IF EXISTS release_probe")
    assert 2.5 <= durations[0] < 6, durations
    assert durations[1] < 2.5
