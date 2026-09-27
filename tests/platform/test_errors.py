"""X5, X5a, X9: every code is registered once, with a class and a legal status."""

import pytest

from commerce_core.platform.errors.exceptions import (
    DomainError,
    RateLimited,
    UnregisteredErrorCode,
    ValidationFailed,
)
from commerce_core.platform.errors.registry import CLASS_STATUSES, ERRORS

PHASE_1_CODES = {
    "validation_error",
    "unauthenticated",
    "permission_denied",
    "not_found",
    "payload_too_large",
    "rate_limited",
    "service_unavailable",
    "internal_error",
}


def test_registry_starts_with_the_phase_1_codes():
    assert set(ERRORS) >= PHASE_1_CODES


def test_every_code_has_exactly_one_exception_class():
    assert set(DomainError.by_code) == set(ERRORS)


def test_every_status_matches_its_x9_class():
    for spec in ERRORS.values():
        assert spec.status in CLASS_STATUSES[spec.error_class], spec.code


def test_unregistered_code_fails_at_import():
    with pytest.raises(UnregisteredErrorCode):

        class Bogus(DomainError):
            code = "no_such_code"


def test_second_class_for_a_code_fails_at_import():
    with pytest.raises(UnregisteredErrorCode):

        class AnotherValidation(DomainError):
            code = "validation_error"


def test_undeclared_details_are_refused():
    with pytest.raises(ValueError):
        ValidationFailed(details={"anything": 1})


def test_rate_limited_carries_retry_after():
    exc = RateLimited(retry_after=30)
    assert exc.details == {"retry_after": 30}
    assert exc.spec().status == 429
