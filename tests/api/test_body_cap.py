"""Q3c: a body over 1 MB is refused with 413 before anything parses it."""

import pytest

from commerce_core.platform.api.middleware import MAX_BODY_BYTES

pytestmark = pytest.mark.django_db


def test_body_over_cap_is_413(client):
    body = b'{"lines": [' + b" " * MAX_BODY_BYTES + b"]}"
    response = client.post("/test-api/validate", body, content_type="application/json")
    assert response.status_code == 413
    assert response.json()["error"]["code"] == "payload_too_large"


def test_refused_before_parsing(client, monkeypatch):
    import json

    calls = []
    monkeypatch.setattr(json, "loads", lambda *a, **k: calls.append(1))
    client.post("/test-api/validate", b"x" * (MAX_BODY_BYTES + 1), content_type="application/json")
    assert calls == []


def test_body_at_cap_is_accepted(client):
    payload = b'{"lines": []}'
    body = payload + b" " * (MAX_BODY_BYTES - len(payload))
    response = client.post("/test-api/validate", body, content_type="application/json")
    assert response.status_code == 200
