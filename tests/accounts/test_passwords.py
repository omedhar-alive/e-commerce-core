"""A1b: Argon2id hashes; the validators run on every set or change."""

import pytest

from commerce_core.accounts.models import User
from commerce_core.accounts.services import change_password
from commerce_core.platform.errors.exceptions import ValidationFailed

pytestmark = pytest.mark.django_db


def test_stored_hash_is_argon2id():
    user = User.objects.create_user("h@x.com", "a-long-password-1")
    user.refresh_from_db()
    assert user.password.startswith("argon2$argon2id$")


def test_validator_refuses_weak_password_and_keeps_old_one():
    user = User.objects.create_user("w@x.com", "a-long-password-1")
    with pytest.raises(ValidationFailed) as info:
        change_password(user, "short")
    assert info.value.field == "password"
    assert info.value.fields
    user.refresh_from_db()
    assert user.check_password("a-long-password-1")
