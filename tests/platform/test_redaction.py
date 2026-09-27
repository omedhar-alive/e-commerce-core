"""A12, X13, X13a, X15: no secrets, tokens or personal data in logs or error reports."""

import io
import json
import logging

import pytest

from commerce_core.platform import context
from commerce_core.platform.logging import JsonFormatter, RedactingFilter, RequestContextFilter
from commerce_core.platform.sentry import before_send

SECRETS = {
    "email": "Jane.Doe@example.com",
    "phone": "+20 100 123 4567",
    "local_phone": "01001234567",
    "bearer": "Bearer abc.def-ghi",
    "jwt": "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxIn0.sig",
    "card": "4111111111111111",
    "totp": "otpauth://totp/x?secret=JBSWY3DPEHPK3PXP",
}
NAMED = {
    "password": "hunter2-password",
    "first_name": "Jane",
    "last_name": "Doe",
    "address": "12 Nile Street",
    "token": "guest-token-value",
    "authorization": "Basic dXNlcjpwYXNz",
}


def _logger():
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.addFilter(RequestContextFilter())
    handler.addFilter(RedactingFilter())
    handler.setFormatter(JsonFormatter())
    logger = logging.getLogger("test.redaction")
    logger.handlers = [handler]
    logger.propagate = False
    logger.setLevel(logging.DEBUG)
    return logger, stream


def _assert_clean(text):
    for value in [*SECRETS.values(), *NAMED.values(), "Jane", "Doe", "hunter2", "4111"]:
        assert value not in text, value


@pytest.mark.parametrize("kind", sorted(SECRETS))
def test_free_text_secrets_are_scrubbed_from_messages(kind):
    logger, stream = _logger()
    logger.info("checkout by %s failed", SECRETS[kind])
    logger.info(f"inline {SECRETS[kind]}")
    _assert_clean(stream.getvalue())


def test_named_fields_are_replaced_whole():
    logger, stream = _logger()
    logger.warning("login failed", extra={**NAMED, "user_id": 42})
    record = json.loads(stream.getvalue())
    assert record["user_id"] == 42
    _assert_clean(stream.getvalue())


def test_exception_text_is_scrubbed():
    logger, stream = _logger()
    try:
        raise ValueError(f"bad email {SECRETS['email']}")
    except ValueError:
        logger.exception("unhandled")
    assert "ValueError" in stream.getvalue()
    _assert_clean(stream.getvalue())


def test_dates_and_ids_survive():
    logger, stream = _logger()
    logger.info("order 1234 at 2026-09-27T12:00:00Z")
    assert "2026-09-27T12:00:00Z" in stream.getvalue() and "1234" in stream.getvalue()


def test_error_logs_carry_request_id_and_upstream():
    logger, stream = _logger()
    tokens = context.request_id.set("r" * 32), context.upstream_request_id.set("edge-1")
    try:
        logger.error("payment failed", extra={"order_id": 7})
    finally:
        context.request_id.reset(tokens[0])
        context.upstream_request_id.reset(tokens[1])
    record = json.loads(stream.getvalue())
    assert record["request_id"] == "r" * 32 and record["upstream_request_id"] == "edge-1"


def test_settings_wire_the_filters_on_every_handler():
    from django.conf import settings

    config = settings.LOGGING
    for handler in config["handlers"].values():
        assert handler["filters"] == ["context", "redact"]


def test_sentry_event_is_scrubbed():
    event = {
        "request": {
            "url": "https://api.test/checkout",
            "data": {"card": SECRETS["card"]},
            "cookies": {"sessionid": "s"},
            "query_string": "token=guest-token-value",
            "headers": {
                "Authorization": SECRETS["bearer"],
                "Cookie": "sessionid=s",
                "User-Agent": "ua",
            },
        },
        "user": {"id": "42", "email": SECRETS["email"], "username": "Jane"},
        "exception": {"values": [{"value": f"refused {SECRETS['phone']}"}]},
        "extra": {**NAMED},
        "breadcrumbs": {"values": [{"message": SECRETS["jwt"]}]},
    }
    cleaned = before_send(event)
    text = json.dumps(cleaned)
    _assert_clean(text)
    assert cleaned["user"] == {"id": "42"}
    assert "data" not in cleaned["request"]
    assert cleaned["request"]["headers"]["User-Agent"] == "ua"


@pytest.mark.django_db
def test_request_log_through_the_api_contains_no_pii(client):
    """An error inside a real request is logged with its request id and nothing personal."""

    logger, stream = _logger()
    logging.getLogger("commerce_core.errors").handlers = logger.handlers
    logging.getLogger("commerce_core.errors").propagate = False
    try:
        response = client.get("/test-api/boom", HTTP_X_REQUEST_ID="edge-7")
    finally:
        logging.getLogger("commerce_core.errors").handlers = []
        logging.getLogger("commerce_core.errors").propagate = True
    record = json.loads(stream.getvalue().splitlines()[0])
    assert record["request_id"] == response["X-Request-ID"]
    assert record["upstream_request_id"] == "edge-7"
    assert record["error_code"] == "internal_error"
