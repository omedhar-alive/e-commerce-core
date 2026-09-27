"""M1, M1a, M1b, M2: integer minor units, one ISO table, never negative."""

import pytest
from django.db import IntegrityError, connection, transaction

from commerce_core.platform.money import ISO_4217, UnknownCurrency, exponent
from tests.testapp.models import MoneyProbe

pytestmark = pytest.mark.django_db


@pytest.mark.parametrize(
    "code, exp",
    [
        ("EGP", 2),
        ("USD", 2),
        ("KWD", 3),
        ("BHD", 3),
        ("OMR", 3),
        ("JOD", 3),
        ("TND", 3),
        ("JPY", 0),
        ("VND", 0),
    ],
)
def test_exponents_come_from_the_iso_table(code, exp):
    assert exponent(code) == exp


def test_unknown_currency_raises():
    with pytest.raises(UnknownCurrency):
        exponent("XYZ")


def test_table_has_only_three_letter_codes():
    assert all(len(c) == 3 and c.isupper() for c in ISO_4217)


def test_money_column_is_bigint():
    with connection.cursor() as cur:
        cur.execute(
            "SELECT data_type FROM information_schema.columns "
            "WHERE table_name = 'testapp_moneyprobe' AND column_name = 'amount'"
        )
        assert cur.fetchone()[0] == "bigint"


def test_negative_amount_refused_by_db():
    MoneyProbe.objects.create(amount=0, currency="EGP")
    MoneyProbe.objects.create(amount=2**62, currency="EGP")
    with pytest.raises(IntegrityError, match="check constraint"):
        with transaction.atomic():
            MoneyProbe.objects.create(amount=-1, currency="EGP")
