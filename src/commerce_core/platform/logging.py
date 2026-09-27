"""Structured logs with request context and redaction (X10a, X13, X13a, A12).

Every record carries ``request_id`` (and ``upstream_request_id`` when a
valid one came in). The redacting filter runs on every handler before
formatting. People are identified by internal id only.
"""

import json
import logging
import traceback
from datetime import UTC, datetime

from commerce_core.platform import context
from commerce_core.platform.redaction import scrub, scrub_text

_STANDARD = set(vars(logging.makeLogRecord({}))) | {
    "message",
    "asctime",
    "request_id",
    "upstream_request_id",
}


class RequestContextFilter(logging.Filter):
    def filter(self, record):
        record.request_id = getattr(record, "request_id", None) or context.request_id.get()
        record.upstream_request_id = (
            getattr(record, "upstream_request_id", None) or context.upstream_request_id.get()
        )
        return True


class RedactingFilter(logging.Filter):
    def filter(self, record):
        record.msg = scrub_text(str(record.msg))
        if record.args:
            record.args = (
                tuple(scrub(a) for a in record.args)
                if isinstance(record.args, tuple)
                else scrub(record.args)
            )
        for key in [k for k in vars(record) if k not in _STANDARD]:
            setattr(record, key, scrub(getattr(record, key), key))
        if record.exc_info:
            record.exc_text = scrub_text("".join(traceback.format_exception(*record.exc_info)))
            record.exc_info = None
        return True


class JsonFormatter(logging.Formatter):
    def format(self, record):
        payload = {
            "time": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": getattr(record, "request_id", None),
        }
        upstream = getattr(record, "upstream_request_id", None)
        if upstream:
            payload["upstream_request_id"] = upstream
        payload.update(
            {k: v for k, v in vars(record).items() if k not in _STANDARD and k != "exc_text"}
        )
        if getattr(record, "exc_text", None):
            payload["exception"] = record.exc_text
        return json.dumps(payload, default=str)


def logging_config(debug: bool) -> dict:
    return {
        "version": 1,
        "disable_existing_loggers": False,
        "filters": {
            "context": {"()": "commerce_core.platform.logging.RequestContextFilter"},
            "redact": {"()": "commerce_core.platform.logging.RedactingFilter"},
        },
        "formatters": {"json": {"()": "commerce_core.platform.logging.JsonFormatter"}},
        "handlers": {
            "console": {
                "class": "logging.StreamHandler",
                "filters": ["context", "redact"],
                "formatter": "json",
            }
        },
        "root": {"handlers": ["console"], "level": "DEBUG" if debug else "INFO"},
        "loggers": {
            "django": {"handlers": ["console"], "level": "INFO", "propagate": False},
            "django.request": {"handlers": ["console"], "level": "WARNING", "propagate": False},
            "django.security": {"handlers": ["console"], "level": "WARNING", "propagate": False},
        },
    }
