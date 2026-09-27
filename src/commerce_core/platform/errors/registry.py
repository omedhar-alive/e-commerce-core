"""The error-code registry (X5a): the single source of every error code.

Each code is declared once with its HTTP status, its X9 class, its message
(translated per request, L3a; never a literal at the raise site, L4) and the
shape of its ``details``. The exception class bound to each code registers
itself in ``exceptions.py``; a code without exactly one class fails at import.

Codes are public API (X8): removing one or changing its status is a breaking
change, and CI diffs this table against the previous release tag. Phase 1
declares only the codes it raises. Each later phase adds its own; X5a's full
table is the v1 end state (owner ruling, 2026-09-27).
"""

from dataclasses import dataclass
from enum import StrEnum

from django.utils.translation import gettext_lazy as _


class ErrorClass(StrEnum):
    VALIDATION = "validation"
    AUTHENTICATION = "authentication"
    AUTHORIZATION = "authorization"
    NOT_FOUND = "not_found"
    TOO_LARGE = "too_large"
    DOMAIN = "domain"
    RATE_LIMITED = "rate_limited"
    INFRASTRUCTURE = "infrastructure"


# X9: which statuses each class may use.
CLASS_STATUSES: dict[ErrorClass, frozenset[int]] = {
    ErrorClass.VALIDATION: frozenset({400}),
    ErrorClass.AUTHENTICATION: frozenset({401}),
    ErrorClass.AUTHORIZATION: frozenset({403}),
    ErrorClass.NOT_FOUND: frozenset({404}),
    ErrorClass.TOO_LARGE: frozenset({413}),
    ErrorClass.DOMAIN: frozenset({409, 422}),
    ErrorClass.RATE_LIMITED: frozenset({429}),
    ErrorClass.INFRASTRUCTURE: frozenset({500, 503}),
}


@dataclass(frozen=True)
class ErrorSpec:
    code: str
    status: int
    error_class: ErrorClass
    message: str
    # Keys ``details`` may carry; empty means the code never carries details.
    details_keys: frozenset[str] = frozenset()
    retryable: bool = False


_SPECS = (
    ErrorSpec("validation_error", 400, ErrorClass.VALIDATION, _("The request is not valid.")),
    ErrorSpec("unauthenticated", 401, ErrorClass.AUTHENTICATION, _("Authentication is required.")),
    ErrorSpec(
        "permission_denied",
        403,
        ErrorClass.AUTHORIZATION,
        _("You do not have permission to do this."),
    ),
    ErrorSpec("not_found", 404, ErrorClass.NOT_FOUND, _("Not found.")),
    ErrorSpec("payload_too_large", 413, ErrorClass.TOO_LARGE, _("The request body is too large.")),
    ErrorSpec(
        "rate_limited",
        429,
        ErrorClass.RATE_LIMITED,
        _("Too many requests. Try again later."),
        details_keys=frozenset({"retry_after"}),
    ),
    ErrorSpec(
        "service_unavailable",
        503,
        ErrorClass.INFRASTRUCTURE,
        _("The service is temporarily unavailable. Try again."),
        retryable=True,
    ),
    ErrorSpec("internal_error", 500, ErrorClass.INFRASTRUCTURE, _("An unexpected error occurred.")),
)

ERRORS: dict[str, ErrorSpec] = {}
for _spec in _SPECS:
    if _spec.code in ERRORS:
        raise ImportError(f"error code {_spec.code!r} declared twice")
    if _spec.status not in CLASS_STATUSES[_spec.error_class]:
        raise ImportError(
            f"error code {_spec.code!r}: status {_spec.status} is not allowed "
            f"for class {_spec.error_class} (X9)"
        )
    ERRORS[_spec.code] = _spec
del _spec


def spec(code: str) -> ErrorSpec:
    return ERRORS[code]
