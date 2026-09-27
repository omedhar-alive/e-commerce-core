"""bootstrap_db: owner URL handling and idempotency (D6)."""

import io

import pytest
from django.core.management import CommandError, call_command
from psycopg import errors, sql

from commerce_core.platform.db import bootstrap, roles
from commerce_core.platform.management.commands.bootstrap_db import read_owner_url
from tests import harness

pytestmark = pytest.mark.django_db


class _Pipe(io.StringIO):
    def isatty(self):
        return False


def test_owner_url_is_never_an_argument():
    with pytest.raises(CommandError):
        call_command("bootstrap_db", "postgresql://owner:secret@host/db")


def test_owner_url_read_from_stdin_when_piped():
    assert read_owner_url(_Pipe("postgresql:///x\n")) == "postgresql:///x"


def test_owner_url_prompted_without_echo_on_a_terminal(monkeypatch):
    class _Tty(io.StringIO):
        def isatty(self):
            return True

    monkeypatch.setattr("getpass.getpass", lambda prompt: " postgresql:///y ")
    assert read_owner_url(_Tty()) == "postgresql:///y"


def test_command_module_reads_no_environment_or_settings():
    import ast
    import inspect

    from commerce_core.platform.management.commands import bootstrap_db as module

    imported = set()
    for node in ast.walk(ast.parse(inspect.getsource(module))):
        if isinstance(node, ast.Import):
            imported |= {alias.name for alias in node.names}
        elif isinstance(node, ast.ImportFrom):
            imported |= {f"{node.module}.{alias.name}" for alias in node.names}
    assert "os" not in imported
    assert not any(name.startswith("django.conf") for name in imported)
    assert not any("conf" in name.split(".")[-2:] for name in imported if "commerce_core" in name)


def test_rerun_never_regrants_on_existing_tables(role_conn):
    migration = role_conn(roles.MIGRATION)
    migration.execute("CREATE TABLE bootstrap_probe (id int)")
    try:
        migration.execute(
            sql.SQL("REVOKE UPDATE ON bootstrap_probe FROM {}").format(sql.Identifier(roles.WEB))
        )
        with bootstrap_superuser_connection() as owner:
            bootstrap.bootstrap_cluster(owner, password_for=lambda r: harness.ROLE_PASSWORD)
            bootstrap.bootstrap_database(owner)
        web = role_conn(roles.WEB)
        with pytest.raises(errors.InsufficientPrivilege):
            web.execute("UPDATE bootstrap_probe SET id = 1")
    finally:
        migration.execute("DROP TABLE bootstrap_probe")


def test_rerun_creates_no_role_and_returns_no_password():
    with bootstrap_superuser_connection() as owner:
        result = bootstrap.bootstrap_cluster(owner)
    assert result.created == {}


def bootstrap_superuser_connection():
    import psycopg

    return psycopg.connect(harness.superuser_conninfo(harness.db_name()), autocommit=True)
