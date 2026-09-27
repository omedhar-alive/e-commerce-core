import pytest

from commerce_core.platform.db import roles
from tests import harness


@pytest.fixture(scope="session")
def django_db_setup(django_db_blocker):
    with django_db_blocker.unblock():
        harness.create_test_database()
        harness.migrate_as_migration_role()
        harness.install_flush_as_migration_role()
        harness.use_role(roles.WEB)
    yield
    with django_db_blocker.unblock():
        harness.drop_test_database()


@pytest.fixture
def role_conn():
    """Open raw autocommit connections as a named role; all closed after the test."""
    opened = []

    def open_(role, **kwargs):
        conn = harness.role_connection(role, **kwargs)
        opened.append(conn)
        return conn

    yield open_
    for conn in opened:
        conn.close()
