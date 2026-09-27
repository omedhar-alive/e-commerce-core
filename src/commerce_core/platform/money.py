"""Money: integer minor units in one ISO-4217 table (M1, M1a, M1b, M2).

``ISO_4217`` is the only source of a currency's minor-unit exponent. Every
calculation, formatter and adapter reads it; nothing assumes two decimals.
``MoneyAmountField`` is the only field type for a stored amount: a 64-bit
integer with ``CHECK (amount >= 0)``. Every model with one also has a
currency column (checked statically, W8a).
"""

from django.db import models

# Active ISO 4217 codes and their minor-unit exponents.
_EXPONENT_0 = ("BIF CLP DJF GNF ISK JPY KMF KRW PYG RWF UGX UYI VND VUV XAF XOF XPF").split()
_EXPONENT_3 = "BHD IQD JOD KWD LYD OMR TND".split()
_EXPONENT_4 = "CLF UYW".split()
_EXPONENT_2 = (
    "AED AFN ALL AMD ANG AOA ARS AUD AWG AZN BAM BBD BDT BGN BMD BND BOB BOV BRL BSD "
    "BTN BWP BYN BZD CAD CDF CHE CHF CHW CNY COP COU CRC CUP CVE CZK DKK DOP DZD EGP "
    "ERN ETB EUR FJD FKP GBP GEL GHS GIP GMD GTQ GYD HKD HNL HTG HUF IDR ILS INR IRR "
    "JMD KES KGS KHR KPW KYD KZT LAK LBP LKR LRD LSL MAD MDL MGA MKD MMK MNT MOP MRU "
    "MUR MVR MWK MXN MXV MYR MZN NAD NGN NIO NOK NPR NZD PAB PEN PGK PHP PKR PLN QAR "
    "RON RSD RUB SAR SBD SCR SDG SEK SGD SHP SLE SOS SRD SSP STN SVC SYP SZL THB TJS "
    "TMT TOP TRY TTD TWD TZS UAH USD USN UYU UZS VED VES WST XCD XCG YER ZAR ZMW ZWG"
).split()

ISO_4217: dict[str, int] = {
    **{c: 0 for c in _EXPONENT_0},
    **{c: 2 for c in _EXPONENT_2},
    **{c: 3 for c in _EXPONENT_3},
    **{c: 4 for c in _EXPONENT_4},
}


class UnknownCurrency(LookupError):
    pass


def exponent(currency: str) -> int:
    try:
        return ISO_4217[currency]
    except KeyError:
        raise UnknownCurrency(currency) from None


class MoneyAmountField(models.BigIntegerField):
    """A stored amount in minor units: ``bigint`` with ``CHECK (col >= 0)`` (M1, M1b).

    Direction is carried by the record type, never by sign.
    """

    description = "Non-negative amount in the currency's minor unit"

    def db_check(self, connection):
        return f'"{self.column}" >= 0'


class CurrencyField(models.CharField):
    """An ISO-4217 code paired with the row's money fields (M2)."""

    def __init__(self, *args, **kwargs):
        kwargs["max_length"] = 3
        super().__init__(*args, **kwargs)

    def deconstruct(self):
        name, path, args, kwargs = super().deconstruct()
        kwargs.pop("max_length", None)
        return name, path, args, kwargs
