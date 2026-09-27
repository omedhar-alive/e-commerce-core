"""One error shape for every error response (X7, X9, X10, X10a).

Every error body is::

    {"error": {"code", "message", "request_id", ["field"], ["fields"], ["details"]}}

``code``, ``message`` and ``request_id`` are always present. ``message`` is
the registry's message rendered in the active language (L3a); ``code`` never
changes with language. Nothing internal reaches the body: no exception class,
stack trace, SQL or path (X10). Anything unhandled becomes ``internal_error``,
is logged with its request id and is sent to error tracking (X13, X14).
"""

import logging

import sentry_sdk
from django.core.exceptions import ObjectDoesNotExist
from django.core.exceptions import PermissionDenied as DjangoPermissionDenied
from django.db import OperationalError
from django.http import Http404, JsonResponse
from django.utils.translation import gettext_lazy as _
from psycopg import errors as pg_errors

from commerce_core.platform import context
from commerce_core.platform.errors import exceptions as exc_types
from commerce_core.platform.errors.exceptions import DomainError
from commerce_core.platform.errors.registry import ERRORS

logger = logging.getLogger("commerce_core.errors")

FIELD_MESSAGE = _("Invalid value.")

# Timeouts the database enforces at role level (T4a): retryable, 503.
_TIMEOUTS = (
    pg_errors.LockNotAvailable,
    pg_errors.QueryCanceled,
    pg_errors.IdleInTransactionSessionTimeout,
)


def is_database_timeout(exc: BaseException) -> bool:
    return isinstance(exc, OperationalError) and isinstance(exc.__cause__, _TIMEOUTS)


def error_body(error: DomainError, request_id: str | None) -> dict:
    spec = ERRORS[error.code]
    body = {
        "code": spec.code,
        "message": str(spec.message),
        "request_id": request_id or context.request_id.get() or "",
    }
    if error.field:
        body["field"] = error.field
    if error.fields:
        body["fields"] = [
            {
                "field": f["field"],
                "code": f["code"],
                "message": str(f.get("message") or FIELD_MESSAGE),
            }
            for f in error.fields
        ]
    if spec.details_keys and error.details:
        body["details"] = error.details
    return {"error": body}


def response_for(error: DomainError, request=None) -> JsonResponse:
    rid = getattr(request, "request_id", None)
    response = JsonResponse(error_body(error, rid), status=ERRORS[error.code].status)
    if isinstance(error, exc_types.RateLimited):
        response["Retry-After"] = str(error.retry_after)
    return response


def _loc_to_field(loc) -> str:
    # ninja prefixes the source and the parameter name: ("body", "payload", "lines", 2, "qty")
    parts = list(loc)
    if parts and parts[0] in {"body", "query", "path", "header", "cookie", "form", "file"}:
        source = parts.pop(0)
        if source == "body" and parts:
            parts.pop(0)
    out = ""
    for part in parts:
        out += f"[{part}]" if isinstance(part, int) else (f".{part}" if out else str(part))
    return out


def from_ninja_validation(errors: list[dict]) -> exc_types.ValidationFailed:
    fields = [
        {"field": _loc_to_field(e.get("loc", ())), "code": e.get("type", "invalid")} for e in errors
    ]
    single = fields[0]["field"] if len(fields) == 1 else None
    return exc_types.ValidationFailed(field=single, fields=fields)


def translate(exc: BaseException, request=None) -> DomainError:
    """Map any exception to a registered error. Unknown ones become internal_error."""
    from ninja.errors import AuthenticationError, AuthorizationError
    from ninja.errors import ValidationError as NinjaValidationError

    if isinstance(exc, DomainError):
        return exc
    if isinstance(exc, NinjaValidationError):
        return from_ninja_validation(exc.errors)
    if isinstance(exc, (Http404, ObjectDoesNotExist)):
        return exc_types.NotFound()
    if isinstance(exc, AuthenticationError):
        return exc_types.Unauthenticated()
    if isinstance(exc, (AuthorizationError, DjangoPermissionDenied)):
        return exc_types.PermissionDenied()
    if is_database_timeout(exc):
        logger.warning("database timeout", extra={"error_code": "service_unavailable"})
        return exc_types.ServiceUnavailable()
    logger.error("unhandled exception", exc_info=exc, extra={"error_code": "internal_error"})
    sentry_sdk.capture_exception(exc)
    return exc_types.InternalError()


def handle(request, exc: BaseException) -> JsonResponse:
    return response_for(translate(exc, request), request)


def install(api) -> None:
    """Replace ninja's default handlers with ours on ``api``."""
    api._exception_handlers = {}
    api.add_exception_handler(Exception, handle)


def handler404(request, exception=None):
    return response_for(exc_types.NotFound(), request)


def handler500(request):
    return response_for(exc_types.InternalError(), request)


def handler403(request, exception=None):
    return response_for(exc_types.PermissionDenied(), request)


def handler400(request, exception=None):
    return response_for(exc_types.ValidationFailed(), request)


class DatabaseTimeoutMiddleware:
    """A role-level lock or statement timeout is a retryable 503 on every view (T4a, X9).

    The transaction has already rolled back whole (X11); this only shapes the
    response. API views reach the same mapping through ``translate``.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        return self.get_response(request)

    def process_exception(self, request, exception):
        if is_database_timeout(exception):
            return response_for(translate(exception, request), request)
        return None
