"""The one email and phone normalization functions (A1a, V8).

Every email comparison - login, guest attachment, coupon and fraud limits -
goes through ``normalize_email``. Every stored phone is E.164 via
``normalize_phone``.
"""

import phonenumbers

from commerce_core.platform.errors.exceptions import ValidationFailed


def normalize_email(value: str) -> str:
    """Trim and lowercase the whole address; nothing provider-specific (handoff #41)."""
    return value.strip().lower()


def normalize_phone(value: str, *, field: str = "phone") -> str:
    """Return ``value`` as E.164, or raise ``validation_error``.

    Numbers must be given in international form (leading ``+``): the store's
    country is not a safe default for a customer's phone.
    """
    try:
        parsed = phonenumbers.parse(value.strip(), None)
    except phonenumbers.NumberParseException:
        raise ValidationFailed(field=field) from None
    if not phonenumbers.is_valid_number(parsed):
        raise ValidationFailed(field=field)
    return phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164)
