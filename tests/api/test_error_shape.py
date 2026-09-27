"""X7, X9, X10, X10a, X5a, T4a: one error shape, registered codes, no internals."""

import pytest
from django.db import connection

from commerce_core.platform.db import roles
from commerce_core.platform.errors.registry import ERRORS
from tests.testapp.models import LockProbe

pytestmark = pytest.mark.django_db


def _error(response):
    body = response.json()
    assert set(body) == {"error"}
    error = body["error"]
    assert {"code", "message", "request_id"} <= set(error)
    assert error["code"] in ERRORS
    assert response.status_code == ERRORS[error["code"]].status
    assert error["request_id"] == response["X-Request-ID"]
    return error


def test_domain_error_body(client):
    error = _error(client.get("/test-api/missing"))
    assert error["code"] == "not_found"
    assert "details" not in error


def test_validation_error_names_each_field(client):
    response = client.post(
        "/test-api/validate",
        {"lines": [{"quantity": 1}, {"quantity": "x"}, {"nope": 1}]},
        content_type="application/json",
    )
    error = _error(response)
    assert error["code"] == "validation_error"
    fields = {f["field"] for f in error["fields"]}
    assert fields == {"lines[1].quantity", "lines[2].quantity"}
    assert all(f["message"] and f["code"] for f in error["fields"])


def test_rate_limited_carries_retry_after_and_details(client):
    response = client.get("/test-api/limited")
    error = _error(response)
    assert error["code"] == "rate_limited"
    assert error["details"] == {"retry_after": 17}
    assert response["Retry-After"] == "17"


def test_unhandled_becomes_internal_error_without_internals(client, monkeypatch):
    captured = []
    monkeypatch.setattr("sentry_sdk.capture_exception", captured.append)
    response = client.get("/test-api/boom")
    error = _error(response)
    assert error["code"] == "internal_error"
    raw = response.content.decode()
    for leak in ("RuntimeError", "secret internals", "/srv/app.py", "SELECT", "Traceback"):
        assert leak not in raw
    assert len(captured) == 1 and isinstance(captured[0], RuntimeError)


def test_unknown_url_uses_the_error_shape(client):
    assert _error(client.get("/api/definitely-not-a-route"))["code"] == "not_found"


def test_class_status_map_per_x9():
    expected = {
        "validation_error": 400,
        "unauthenticated": 401,
        "permission_denied": 403,
        "not_found": 404,
        "payload_too_large": 413,
        "rate_limited": 429,
        "service_unavailable": 503,
        "internal_error": 500,
    }
    assert {code: ERRORS[code].status for code in expected} == expected


@pytest.mark.django_db(transaction=True)
def test_lock_timeout_is_a_retryable_503(client, role_conn):
    LockProbe.objects.create(id=1, name="held")
    holder = role_conn(roles.JOB, autocommit=False)
    holder.execute("SELECT id FROM testapp_lockprobe WHERE id = 1 FOR UPDATE")
    try:
        response = client.get("/test-api/lock")
    finally:
        holder.rollback()
    error = _error(response)
    assert error["code"] == "service_unavailable"
    assert ERRORS["service_unavailable"].retryable
    connection.close()
