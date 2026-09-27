"""One phone format (E.164), one normalization function."""

import pytest

from commerce_core.accounts.models import User
from commerce_core.accounts.normalize import normalize_phone
from commerce_core.platform.errors.exceptions import ValidationFailed

pytestmark = pytest.mark.django_db


@pytest.mark.parametrize(
    "raw, e164",
    [("+20 100 123 4567", "+201001234567"), ("+965 5000 1234", "+96550001234")],
)
def test_normalizes_to_e164(raw, e164):
    assert normalize_phone(raw) == e164


@pytest.mark.parametrize("raw", ["01001234567", "+20 12", "not a phone"])
def test_invalid_phone_raises_validation_error(raw):
    with pytest.raises(ValidationFailed) as info:
        normalize_phone(raw)
    assert info.value.code == "validation_error"
    assert info.value.field == "phone"


def test_field_normalizes_on_save_and_update():
    user = User.objects.create_user("p@x.com", "a-long-password-1", phone="+20 100 123 4567")
    assert user.phone == "+201001234567"
    User.objects.filter(pk=user.pk).update(phone="+965 5000 1234")
    user.refresh_from_db()
    assert user.phone == "+96550001234"


def test_invalid_phone_on_write_raises_validation_error():
    with pytest.raises(ValidationFailed):
        User.objects.create_user("q@x.com", "a-long-password-1", phone="12345")
