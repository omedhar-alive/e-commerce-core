"""Role-aware test database harness (phase plan section 4, decision 19).

* A local superuser creates the test database; ``bootstrap_db``'s two parts
  run against it exactly as they do on Neon.
* Migrations run as the migration role.
* Tests connect as ``commerce_web`` (or ``commerce_job`` where a test says so).
* Transactional tests flush as the migration role: web holds no ``TRUNCATE``,
  and granting it would change the thing under test.
"""

import os
from contextlib import contextmanager

import psycopg
from django.core.management import call_command
from django.db import connections
from psycopg import sql

from commerce_core.platform.db import bootstrap, roles

SUPERUSER_URL = os.environ.get("COMMERCE_TEST_SUPERUSER_URL", "postgresql:///postgres")
ROLE_PASSWORD = os.environ.get("COMMERCE_TEST_ROLE_PASSWORD", "commerce-test-only")


def _settings():
    return connections["default"].settings_dict


def db_name() -> str:
    return _settings()["NAME"]


def conninfo(role: str, dbname: str | None = None) -> str:
    s = _settings()
    parts = {
        "dbname": dbname or s["NAME"],
        "user": role,
        "password": ROLE_PASSWORD,
    }
    if s.get("HOST"):
        parts["host"] = s["HOST"]
    if s.get("PORT"):
        parts["port"] = str(s["PORT"])
    return psycopg.conninfo.make_conninfo(**parts)


def superuser_conninfo(dbname: str | None = None) -> str:
    if dbname is None:
        return SUPERUSER_URL
    return psycopg.conninfo.make_conninfo(SUPERUSER_URL, dbname=dbname)


def role_connection(role: str, *, autocommit: bool = True) -> psycopg.Connection:
    return psycopg.connect(conninfo(role), autocommit=autocommit)


def create_test_database() -> None:
    name = db_name()
    with psycopg.connect(SUPERUSER_URL, autocommit=True) as conn:
        bootstrap.bootstrap_cluster(conn, password_for=lambda role: ROLE_PASSWORD)
        conn.execute(
            sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(name))
        )
        conn.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
    with psycopg.connect(superuser_conninfo(name), autocommit=True) as conn:
        bootstrap.bootstrap_database(conn)


def drop_test_database() -> None:
    connections.close_all()
    with psycopg.connect(SUPERUSER_URL, autocommit=True) as conn:
        conn.execute(
            sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(db_name()))
        )


def use_role(role: str) -> None:
    """Point the default alias (and every thread's copy of it) at ``role``."""
    connections["default"].close()
    s = _settings()
    s["USER"] = role
    s["PASSWORD"] = ROLE_PASSWORD


@contextmanager
def as_role(role: str):
    previous = _settings()["USER"]
    use_role(role)
    try:
        yield
    finally:
        use_role(previous)


def migrate_as_migration_role() -> None:
    with as_role(roles.MIGRATION):
        call_command("migrate", verbosity=0, interactive=False)


def install_flush_as_migration_role() -> None:
    """Route Django's test flush through a migration-role connection."""
    from django.db.backends.postgresql.operations import DatabaseOperations

    def execute_sql_flush(self, sql_list):
        with role_connection(roles.MIGRATION, autocommit=False) as conn:
            with conn.cursor() as cur:
                for statement in sql_list:
                    cur.execute(statement)
            conn.commit()

    DatabaseOperations.execute_sql_flush = execute_sql_flush
