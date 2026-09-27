"""D6 and T4a: roles run only what their work needs, with role-level timeouts."""

import re

import psycopg
import pytest
from psycopg import errors

from commerce_core.platform.db import roles

pytestmark = pytest.mark.django_db

_UNIT_MS = {"ms": 1, "s": 1000, "min": 60_000, "h": 3_600_000}


def _to_ms(value: str) -> int:
    match = re.fullmatch(r"(\d+)(ms|s|min|h)?", value)
    number, unit = match.groups()
    return int(number) * _UNIT_MS[unit or "ms"]


def _setting_ms(conn: psycopg.Connection, name: str) -> int:
    setting, unit = conn.execute(
        "SELECT setting, unit FROM pg_settings WHERE name = %s", (name,)
    ).fetchone()
    return int(setting) * _UNIT_MS[unit]


@pytest.mark.parametrize("role", roles.ALL_ROLES)
def test_role_reports_its_timeouts(role_conn, role):
    conn = role_conn(role)
    for name, expected in roles.TIMEOUTS[role].as_settings().items():
        assert _setting_ms(conn, name) == _to_ms(expected), (role, name)


def test_web_and_job_timeouts_match_t4a():
    assert roles.TIMEOUTS[roles.WEB].statement_timeout == "30s"
    assert roles.TIMEOUTS[roles.JOB].statement_timeout == "10min"
    for role in roles.DML_ROLES:
        assert roles.TIMEOUTS[role].lock_timeout == "5s"
        assert roles.TIMEOUTS[role].idle_in_transaction_session_timeout == "60s"


def test_migration_role_has_d2a_lock_timeout_and_no_statement_timeout():
    assert roles.TIMEOUTS[roles.MIGRATION].lock_timeout == "3s"
    assert roles.TIMEOUTS[roles.MIGRATION].statement_timeout == "0"


@pytest.mark.parametrize("role", roles.DML_ROLES)
@pytest.mark.parametrize(
    "ddl",
    [
        "CREATE TABLE ddl_probe (id int)",
        "ALTER TABLE django_content_type ADD COLUMN ddl_probe int",
        "DROP TABLE django_content_type",
        "CREATE INDEX ddl_probe_idx ON django_content_type (model)",
        "TRUNCATE django_content_type",
    ],
)
def test_web_and_job_cannot_run_ddl(role_conn, role, ddl):
    conn = role_conn(role)
    with pytest.raises(errors.InsufficientPrivilege):
        conn.execute(ddl)


@pytest.mark.parametrize("role", roles.ALL_ROLES)
def test_roles_are_not_privileged(role_conn, role):
    conn = role_conn(role)
    row = conn.execute(
        "SELECT rolsuper, rolcreatedb, rolcreaterole, rolbypassrls "
        "FROM pg_roles WHERE rolname = current_user"
    ).fetchone()
    assert row == (False, False, False, False)


def test_migration_role_owns_schema_and_tables(role_conn):
    conn = role_conn(roles.MIGRATION)
    owner = conn.execute(
        "SELECT pg_get_userbyid(nspowner) FROM pg_namespace WHERE nspname = 'public'"
    ).fetchone()[0]
    assert owner == roles.MIGRATION
    table_owners = {
        r[0]
        for r in conn.execute(
            "SELECT tableowner FROM pg_tables WHERE schemaname = 'public'"
        ).fetchall()
    }
    assert table_owners == {roles.MIGRATION}


def test_retention_role_reads_but_cannot_write_by_default(role_conn):
    conn = role_conn(roles.RETENTION)
    conn.execute("SELECT count(*) FROM django_content_type")
    with pytest.raises(errors.InsufficientPrivilege):
        conn.execute("DELETE FROM django_content_type")
