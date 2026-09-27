"""T4a: a transaction blocked on a lock fails at the role's lock_timeout.

The mapping of this failure to a retryable 503 is tested with the error
handlers (tests/api/test_error_shape.py).
"""

import time

import pytest
from psycopg import errors

from commerce_core.platform.db import roles

pytestmark = pytest.mark.django_db


def test_web_lock_wait_fails_at_lock_timeout(role_conn):
    holder = role_conn(roles.JOB, autocommit=False)
    holder.execute("SELECT id FROM django_content_type ORDER BY id LIMIT 1 FOR UPDATE")
    waiter = role_conn(roles.WEB, autocommit=False)
    started = time.monotonic()
    with pytest.raises(errors.LockNotAvailable):
        waiter.execute("SELECT id FROM django_content_type ORDER BY id LIMIT 1 FOR UPDATE")
    elapsed = time.monotonic() - started
    holder.rollback()
    assert 4.5 <= elapsed < 8, elapsed
