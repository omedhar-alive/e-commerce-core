"""A1a: one account per email, case-insensitively."""

import pytest
from django.db import IntegrityError, transaction

from commerce_core.accounts.models import User
from commerce_core.accounts.normalize import normalize_email

pytestmark = pytest.mark.django_db


def test_normalize_trims_and_lowercases_whole_address():
    assert normalize_email("  Foo.Bar+Tag@Example.COM ") == "foo.bar+tag@example.com"


def test_case_variants_cannot_create_two_accounts():
    User.objects.create_user("Foo@x.com", "a-long-password-1")
    with pytest.raises(IntegrityError, match="accounts_user_email_ci_uniq"):
        with transaction.atomic():
            User.objects.create_user("foo@X.COM", "a-long-password-1")


def test_stored_value_is_normalized_on_save():
    user = User(email=" Mixed@Case.com ")
    user.set_unusable_password()
    user.save(force_insert=True)
    assert user.email == "mixed@case.com"
    assert User.objects.values_list("email", flat=True).get(pk=user.pk) == "mixed@case.com"


def test_queryset_update_normalizes():
    user = User.objects.create_user("a@x.com", "a-long-password-1")
    User.objects.filter(pk=user.pk).update(email="  UPPER@X.com")
    user.refresh_from_db()
    assert user.email == "upper@x.com"


def test_lookup_by_any_case_finds_the_account():
    user = User.objects.create_user("a@x.com", "a-long-password-1")
    assert User.objects.get(email="A@X.COM") == user
    assert User.objects.get_by_natural_key(" A@x.com ") == user


def test_database_refuses_raw_case_variant(role_conn):
    """The functional index holds even for a write that bypasses the field."""
    from psycopg import errors

    from commerce_core.platform.db import roles

    conn = role_conn(roles.WEB)
    conn.execute(
        "INSERT INTO accounts_user (email, password, first_name, last_name, country,"
        " preferred_language, is_active, is_staff, is_superuser, date_joined)"
        " VALUES ('raw@x.com', '!', '', '', '', '', true, false, false, now())"
    )
    try:
        with pytest.raises(errors.UniqueViolation):
            conn.execute(
                "INSERT INTO accounts_user (email, password, first_name, last_name, country,"
                " preferred_language, is_active, is_staff, is_superuser, date_joined)"
                " VALUES ('RAW@x.com', '!', '', '', '', '', true, false, false, now())"
            )
    finally:
        conn.execute("DELETE FROM accounts_user WHERE lower(email) = 'raw@x.com'")
