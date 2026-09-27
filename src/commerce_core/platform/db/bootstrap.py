"""One-time database setup, run by the database owner (D6, T4a).

Two parts:

* the cluster part creates the four roles and sets their timeouts at role
  level (``ALTER ROLE … SET``), never per session, because a transaction-mode
  pooler drops session settings (T4a);
* the database part gives the migration role the schema and sets default
  privileges, which PostgreSQL keeps per database.

Both parts are idempotent. Re-running never re-grants privileges on existing
tables: that would undo the revokes the D7 and D7a migrations made.

This module uses psycopg directly. It runs before any migration and before the
application's own database settings exist, so it never goes through the
settings registry.
"""

import secrets
from dataclasses import dataclass, field

import psycopg
from psycopg import sql

from commerce_core.platform.db import roles


@dataclass
class BootstrapResult:
    # Passwords of roles created by this run, keyed by role. Existing roles
    # keep their passwords and do not appear here.
    created: dict[str, str] = field(default_factory=dict)


def bootstrap_cluster(conn: psycopg.Connection, *, password_for=None) -> BootstrapResult:
    """Create any missing role and (re)apply every role's timeouts."""
    result = BootstrapResult()
    for role in roles.ALL_ROLES:
        exists = conn.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (role,)).fetchone()
        if not exists:
            password = password_for(role) if password_for else secrets.token_urlsafe(32)
            conn.execute(
                sql.SQL(
                    "CREATE ROLE {} LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE "
                    "NOREPLICATION NOBYPASSRLS PASSWORD {}"
                ).format(sql.Identifier(role), sql.Literal(password))
            )
            result.created[role] = password
        for name, value in roles.TIMEOUTS[role].as_settings().items():
            conn.execute(
                sql.SQL("ALTER ROLE {} SET {} = {}").format(
                    sql.Identifier(role), sql.Identifier(name), sql.Literal(value)
                )
            )
    return result


def bootstrap_database(conn: psycopg.Connection) -> None:
    """Hand the schema to the migration role and set default privileges.

    Must run connected to the target database, as its owner.
    """
    dbname = conn.info.dbname
    is_superuser = conn.execute(
        "SELECT rolsuper FROM pg_roles WHERE rolname = current_user"
    ).fetchone()[0]
    if not is_superuser:
        # ALTER SCHEMA … OWNER TO needs membership in the new owner. A
        # CREATEROLE owner (Neon) holds ADMIN on roles it created and can
        # grant itself that membership.
        conn.execute(sql.SQL("GRANT {} TO current_user").format(sql.Identifier(roles.MIGRATION)))

    for role in roles.ALL_ROLES:
        conn.execute(
            sql.SQL("GRANT CONNECT ON DATABASE {} TO {}").format(
                sql.Identifier(dbname), sql.Identifier(role)
            )
        )

    migration = sql.Identifier(roles.MIGRATION)
    conn.execute(sql.SQL("ALTER SCHEMA public OWNER TO {}").format(migration))
    conn.execute("REVOKE CREATE ON SCHEMA public FROM PUBLIC")
    for role in (roles.WEB, roles.JOB, roles.RETENTION):
        conn.execute(sql.SQL("GRANT USAGE ON SCHEMA public TO {}").format(sql.Identifier(role)))

    dml = sql.SQL(", ").join(sql.Identifier(r) for r in roles.DML_ROLES)
    default = sql.SQL("ALTER DEFAULT PRIVILEGES FOR ROLE {} IN SCHEMA public ").format(migration)
    # Web and job: DML only (D6). No TRUNCATE, REFERENCES or TRIGGER.
    conn.execute(
        default + sql.SQL("GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO {}").format(dml)
    )
    conn.execute(default + sql.SQL("GRANT USAGE, SELECT ON SEQUENCES TO {}").format(dml))
    # Retention reads; its DELETE grants arrive table by table with the
    # retention job (phase 11).
    conn.execute(
        default + sql.SQL("GRANT SELECT ON TABLES TO {}").format(sql.Identifier(roles.RETENTION))
    )


def bootstrap(owner_url: str, *, password_for=None) -> BootstrapResult:
    """Run both parts against the database named in ``owner_url``."""
    with psycopg.connect(owner_url, autocommit=True) as conn:
        result = bootstrap_cluster(conn, password_for=password_for)
        bootstrap_database(conn)
    return result
