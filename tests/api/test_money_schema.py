"""M1a, Q3b: every amount in a response carries currency and exponent."""

import pytest

from commerce_core.platform.api.schemas import Money

pytestmark = pytest.mark.django_db


@pytest.mark.parametrize(
    "currency, amount, exp", [("JPY", 1999, 0), ("KWD", 1999, 3), ("EGP", 1999, 2), ("KWD", 0, 3)]
)
def test_zero_and_three_decimal_currencies_round_trip(client, currency, amount, exp):
    body = client.get(f"/test-api/money/{currency}/{amount}").json()
    assert body == {"price": {"amount": amount, "currency": currency, "exponent": exp}}
    assert Money.model_validate(body["price"]) == Money.of(amount, currency)


def test_exponent_is_always_present():
    assert set(Money.model_fields) == {"amount", "currency", "exponent"}
    assert all(f.is_required() for f in Money.model_fields.values())
