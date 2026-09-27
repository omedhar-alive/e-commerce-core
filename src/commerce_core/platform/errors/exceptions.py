"""``DomainError`` and the exception bound to each registered code (X5, X5a).

A subclass names its code; an unregistered code, or a second class for the
same code, fails at import, so a bad code can never reach a response.
Raise sites pass no message (L4): the message comes from the registry,
translated for the request (X7, L3a).
"""

from typing import Any, ClassVar

from commerce_core.platform.errors.registry import ERRORS, ErrorSpec


class UnregisteredErrorCode(ImportError):
    pass


class DomainError(Exception):
    code: ClassVar[str]
    by_code: ClassVar[dict[str, type["DomainError"]]] = {}

    def __init_subclass__(cls, abstract: bool = False, **kwargs):
        super().__init_subclass__(**kwargs)
        if abstract:
            return
        code = cls.__dict__.get("code")
        if code not in ERRORS:
            raise UnregisteredErrorCode(
                f"{cls.__qualname__} declares code {code!r}, which is not in the registry (X5a)"
            )
        if code in DomainError.by_code:
            raise UnregisteredErrorCode(
                f"code {code!r} is already bound to {DomainError.by_code[code].__qualname__}"
            )
        DomainError.by_code[code] = cls

    def __init__(
        self,
        *,
        field: str | None = None,
        fields: list[dict[str, str]] | None = None,
        details: dict[str, Any] | None = None,
    ):
        spec = self.spec()
        unknown = set(details or {}) - spec.details_keys
        if unknown:
            raise ValueError(f"{self.code}: details keys {sorted(unknown)} are not declared")
        self.field = field
        self.fields = fields or []
        self.details = details or {}
        super().__init__(self.code)

    @classmethod
    def spec(cls) -> ErrorSpec:
        return ERRORS[cls.code]


class ValidationFailed(DomainError):
    code = "validation_error"


class Unauthenticated(DomainError):
    code = "unauthenticated"


class PermissionDenied(DomainError):
    code = "permission_denied"


class NotFound(DomainError):
    code = "not_found"


class PayloadTooLarge(DomainError):
    code = "payload_too_large"


class RateLimited(DomainError):
    code = "rate_limited"

    def __init__(self, *, retry_after: int, **kwargs):
        super().__init__(details={"retry_after": retry_after}, **kwargs)
        self.retry_after = retry_after


class ServiceUnavailable(DomainError):
    code = "service_unavailable"


class InternalError(DomainError):
    code = "internal_error"
