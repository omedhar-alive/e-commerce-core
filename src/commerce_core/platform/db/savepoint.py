"""The one place an ``IntegrityError`` may be caught (X11a).

Only a unique violation of one named constraint, raised inside a savepoint
that wraps the insert, and only to retry with a new value (O6) or to treat
the request as a replay of the existing row (C10, P5, T2b, G1). Any other
violation re-raises. The savepoint keeps the caller's transaction usable,
which is what X11 otherwise forbids.
"""

from collections.abc import Callable

from django.db import IntegrityError, transaction
from psycopg import errors as pg_errors


def violated_unique_constraint(exc: IntegrityError) -> str | None:
    cause = exc.__cause__
    if isinstance(cause, pg_errors.UniqueViolation):
        return cause.diag.constraint_name
    return None


def on_unique_violation[T](
    constraint: str, insert: Callable[[], T], on_violation: Callable[[], T]
) -> T:
    """Run ``insert`` in a savepoint; on a violation of ``constraint`` only, return ``on_violation()``."""
    try:
        with transaction.atomic():
            return insert()
    except IntegrityError as exc:
        if violated_unique_constraint(exc) != constraint:
            raise
    return on_violation()


class RetriesExhausted(RuntimeError):
    pass


def retry_on_unique_violation[T](
    constraint: str, insert: Callable[[], T], *, attempts: int = 5
) -> T:
    """Retry ``insert`` (which must draw a fresh value each call) while ``constraint`` collides."""
    for _ in range(attempts):
        try:
            with transaction.atomic():
                return insert()
        except IntegrityError as exc:
            if violated_unique_constraint(exc) != constraint:
                raise
    raise RetriesExhausted(f"{constraint}: still colliding after {attempts} attempts")
