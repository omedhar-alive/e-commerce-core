"""A9: the rate-limit store counts atomically per window; expired windows are pruned."""

from datetime import UTC, datetime, timedelta

import pytest
from django.db import connection

from commerce_core.platform.errors.exceptions import RateLimited
from commerce_core.platform.models import RateLimitCounter
from commerce_core.platform.ratelimit import store
from commerce_core.platform.ratelimit.jobs import prune_expired_windows
from commerce_core.platform.ratelimit.policies import POLICIES, RateLimitPolicy, declare

pytestmark = pytest.mark.django_db
POLICY = RateLimitPolicy("test_login", "account", timedelta(minutes=15), 5)
NOW = datetime(2026, 9, 27, 12, 7, tzinfo=UTC)


def test_limit_holds_at_its_boundary():
    results = [store.hit(POLICY, "acct-1", NOW) for _ in range(6)]
    assert [r.allowed for r in results] == [True] * 5 + [False]
    assert results[-1].retry_after == 8 * 60  # window ends at 12:15


def test_enforce_raises_rate_limited_with_retry_after():
    for _ in range(5):
        store.enforce(POLICY, "acct-1", NOW)
    with pytest.raises(RateLimited) as info:
        store.enforce(POLICY, "acct-1", NOW)
    assert info.value.retry_after == 480


def test_windows_and_principals_are_independent():
    for _ in range(5):
        store.hit(POLICY, "acct-1", NOW)
    assert store.hit(POLICY, "acct-2", NOW).allowed
    assert store.hit(POLICY, "acct-1", NOW + timedelta(minutes=15)).allowed


def test_principal_is_never_stored_in_clear():
    store.hit(POLICY, "someone@example.com", NOW)
    row = RateLimitCounter.objects.get()
    assert "someone" not in row.principal_hash and len(row.principal_hash) == 64


def test_increment_is_one_statement():
    from django.test.utils import CaptureQueriesContext

    with CaptureQueriesContext(connection) as ctx:
        store.hit(POLICY, "acct-1", NOW)
    assert len(ctx.captured_queries) == 1
    assert "ON CONFLICT" in ctx.captured_queries[0]["sql"]


def test_pruning_removes_only_expired_windows():
    store.hit(POLICY, "old", datetime.now(UTC) - timedelta(hours=2))
    store.hit(POLICY, "current", datetime.now(UTC))
    prune_expired_windows()
    assert RateLimitCounter.objects.count() == 1


def test_policy_declaration_is_validated():
    with pytest.raises(ValueError):
        declare("bad", principal="ip", window=timedelta(0), maximum=1)
    assert "bad" not in POLICIES
