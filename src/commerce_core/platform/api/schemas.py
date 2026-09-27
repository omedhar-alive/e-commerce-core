"""Shared response shapes (Q3b, X7)."""

from ninja import Schema

from commerce_core.platform.money import exponent


class Money(Schema):
    """Every amount in a response: ``{"amount": 1999, "currency": "EGP", "exponent": 2}`` (Q3b)."""

    amount: int
    currency: str
    exponent: int

    @classmethod
    def of(cls, amount: int, currency: str) -> "Money":
        return cls(amount=amount, currency=currency, exponent=exponent(currency))


class ErrorField(Schema):
    field: str
    code: str
    message: str


class ErrorDetail(Schema):
    code: str
    message: str
    request_id: str
    field: str | None = None
    fields: list[ErrorField] | None = None
    details: dict | None = None


class ErrorResponse(Schema):
    error: ErrorDetail
