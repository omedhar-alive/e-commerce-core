"""Account services."""

from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from django.db.models import F

from commerce_core.accounts.models import User
from commerce_core.platform.errors.exceptions import NotFound, ValidationFailed


def bump_token_version(user: User) -> int:
    """Invalidate every credential issued to ``user`` (A4b).

    One atomic ``UPDATE … SET token_version = token_version + 1``. Returns the
    new version and refreshes it on ``user``.
    """
    updated = User.objects.filter(pk=user.pk).update(token_version=F("token_version") + 1)
    if updated != 1:
        raise NotFound()
    user.refresh_from_db(fields=["token_version"])
    return user.token_version


def deactivate_user(user: User) -> None:
    with transaction.atomic():
        User.objects.filter(pk=user.pk).update(is_active=False)
        bump_token_version(user)
    user.is_active = False


def change_password(user: User, raw_password: str) -> None:
    """Validate, hash with Argon2id (A1b), store, and bump the token version."""
    try:
        validate_password(raw_password, user)
    except DjangoValidationError as exc:
        raise ValidationFailed(
            field="password",
            fields=[
                {"field": "password", "code": e.code or "invalid", "message": str(e.message)}
                for e in exc.error_list
            ],
        ) from None
    user.set_password(raw_password)
    with transaction.atomic():
        user.save(update_fields=["password"])
        bump_token_version(user)
