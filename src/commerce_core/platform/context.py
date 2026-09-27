"""Per-request context shared with logging and error reporting (X10a, X13)."""

from contextvars import ContextVar

request_id: ContextVar[str | None] = ContextVar("request_id", default=None)
upstream_request_id: ContextVar[str | None] = ContextVar("upstream_request_id", default=None)
