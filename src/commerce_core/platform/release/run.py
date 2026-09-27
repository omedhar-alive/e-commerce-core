"""The release step (D2a, D2g, D2h, D3, W5, W6).

Runs once per deploy, before new code starts, as the migration role:

1. refuses to migrate a deployment more than one minor version behind (W5);
2. refuses any plan that would unapply a migration in production (D2h);
3. refuses a flagged destructive migration without ``--restore-point``, in
   every environment (D3; decision 19). In production the restore point
   must also be verified against a passed D4 restore test, which lands in
   phase 11, so a destructive production migration is refused until then;
4. migrates, retrying a lock timeout with exponential backoff up to
   ``MIGRATION_LOCK_RETRIES`` (D2a);
5. creates missing job schedule rows (N4a) and records the release.
"""

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass

from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import DEFAULT_DB_ALIAS, OperationalError, connections
from django.db.migrations.executor import MigrationExecutor
from psycopg import errors as pg_errors

from commerce_core.platform.conf import get_setting
from commerce_core.platform.conf.registry import DeploymentEnv
from commerce_core.platform.release.safety import Finding, classify
from commerce_core.platform.version import core_version

logger = logging.getLogger("commerce_core.release")


class ReleaseRefused(CommandError):
    pass


@dataclass(frozen=True)
class Version:
    major: int
    minor: int
    patch: int

    @classmethod
    def parse(cls, text: str) -> "Version":
        core = text.split("+")[0].split("-")[0]
        major, minor, patch = (int(p) for p in core.split(".")[:3])
        return cls(major, minor, patch)


def check_version_gate(current: str, recorded: str | None) -> None:
    """W5, W6: one minor at a time. A code rollback (recorded ahead) migrates nothing new."""
    if recorded is None:
        return
    now, before = Version.parse(current), Version.parse(recorded)
    if (now.major, now.minor) <= (before.major, before.minor):
        return
    if now.major != before.major or now.minor - before.minor > 1:
        raise ReleaseRefused(
            f"This deployment runs core {recorded}; upgrading to {current} skips a minor version. "
            "Upgrade one minor version at a time (W5)."
        )


def check_forwards_only(plan, env: str) -> None:
    """D2h: production rollback is a code rollback, never a schema rollback."""
    backwards = [f"{m.app_label}.{m.name}" for m, is_backwards in plan if is_backwards]
    if backwards and env == DeploymentEnv.PRODUCTION:
        raise ReleaseRefused(
            f"Refusing to unapply migrations in production: {', '.join(backwards)} (D2h)"
        )


def check_restore_point(findings: list[Finding], restore_point: str, env: str) -> list[str]:
    destructive = sorted(
        {f"{f.app_label}.{f.migration}" for f in findings if f.kind == "destructive"}
    )
    if not destructive:
        return []
    if not restore_point:
        raise ReleaseRefused(
            f"Destructive migrations pending: {', '.join(destructive)}. Take a backup or restore "
            "point first and pass its identifier with --restore-point (D3)."
        )
    if env == DeploymentEnv.PRODUCTION:
        raise ReleaseRefused(
            "A destructive migration in production needs a restore point verified against a passed "
            "D4 restore test; restore verification lands in phase 11 (D3, D4)."
        )
    return destructive


def is_lock_timeout(exc: BaseException) -> bool:
    return isinstance(exc, OperationalError) and isinstance(
        exc.__cause__, pg_errors.LockNotAvailable
    )


def migrate_with_retry(
    migrate: Callable[[], None], retries: int, sleep: Callable[[float], None] = time.sleep
) -> int:
    """Run ``migrate``; on a lock timeout retry with backoff 1, 2, 4… s. Returns attempts used."""
    for attempt in range(retries + 1):
        try:
            migrate()
            return attempt + 1
        except OperationalError as exc:
            if not is_lock_timeout(exc) or attempt == retries:
                if is_lock_timeout(exc):
                    raise ReleaseRefused(
                        f"Migration could not get its lock after {retries + 1} attempts (D2a)"
                    ) from exc
                raise
            delay = min(2**attempt, 30)
            logger.warning(
                "migration lock timeout; retrying", extra={"attempt": attempt + 1, "delay_s": delay}
            )
            sleep(delay)
    raise AssertionError("unreachable")


def _recorded_version() -> str | None:
    from commerce_core.platform.models import ReleaseRecord

    connection = connections[DEFAULT_DB_ALIAS]
    if ReleaseRecord._meta.db_table not in connection.introspection.table_names():
        return None
    latest = ReleaseRecord.objects.order_by("-applied_at", "-pk").first()
    return latest.core_version if latest else None


def run_release(
    *, restore_point: str = "", target: tuple[str, str] | None = None, sleep=time.sleep, stdout=None
):
    from commerce_core.platform.jobs.registry import sync_schedules
    from commerce_core.platform.models import ReleaseRecord

    env = get_setting("DEPLOYMENT_ENV")
    version = core_version()
    check_version_gate(version, _recorded_version())

    connection = connections[DEFAULT_DB_ALIAS]
    executor = MigrationExecutor(connection)
    targets = [target] if target else executor.loader.graph.leaf_nodes()
    plan = executor.migration_plan(targets)
    check_forwards_only(plan, env)

    forwards = [(m.app_label, m.name) for m, backwards in plan if not backwards]
    applied_tables = _tables_before(executor)
    findings = classify(executor.loader, forwards, applied_tables)
    destructive = check_restore_point(findings, restore_point, env)

    args = list(target) if target else []
    migrate_with_retry(
        lambda: call_command("migrate", *args, interactive=False, verbosity=1, stdout=stdout),
        retries=get_setting("MIGRATION_LOCK_RETRIES"),
        sleep=sleep,
    )
    sync_schedules()
    return ReleaseRecord.objects.create(
        core_version=version,
        deployment_env=env,
        restore_point=restore_point,
        restore_point_verified=False,
        destructive_migrations=destructive,
        applied_migrations=[f"{a}.{n}" for a, n in forwards],
    )


def _tables_before(executor) -> frozenset[str]:
    """Tables that already exist, so D2b's blocking checks apply to them."""
    return frozenset(executor.connection.introspection.table_names())
