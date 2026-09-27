"""T1, T4: the shared client refuses to run inside atomic() and always has timeouts."""

import httpx
import pytest
from django.db import transaction

from commerce_core.platform.http import (
    DEFAULT_TIMEOUT,
    HttpClient,
    HttpInsideTransaction,
    TimeoutRequired,
)


def _client(calls):
    def handler(request):
        calls.append(request)
        return httpx.Response(200, json={"ok": True})

    return HttpClient(transport=httpx.MockTransport(handler))


@pytest.mark.django_db
def test_raises_inside_atomic_before_any_request():
    calls = []
    with transaction.atomic():
        with pytest.raises(HttpInsideTransaction):
            _client(calls).get("https://provider.test/x")
    assert calls == []


@pytest.mark.django_db(transaction=True)
def test_works_outside_a_transaction():
    calls = []
    assert _client(calls).get("https://provider.test/x").json() == {"ok": True}
    assert len(calls) == 1


def test_default_timeouts_are_all_set():
    assert None not in (
        DEFAULT_TIMEOUT.connect,
        DEFAULT_TIMEOUT.read,
        DEFAULT_TIMEOUT.write,
        DEFAULT_TIMEOUT.pool,
    )


def test_client_refuses_a_missing_timeout():
    with pytest.raises(TimeoutRequired):
        HttpClient(timeout=httpx.Timeout(None))
    with pytest.raises(TimeoutRequired):
        HttpClient(timeout=httpx.Timeout(5.0, read=None))


@pytest.mark.django_db(transaction=True)
def test_request_refuses_disabling_the_timeout():
    with pytest.raises(TimeoutRequired):
        _client([]).get("https://provider.test/x", timeout=None)
