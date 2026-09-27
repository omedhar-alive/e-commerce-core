"""A4b (column and bump only in phase 1): credentials die with deactivation or password change."""

import pytest

from commerce_core.accounts.models import User
from commerce_core.accounts.services import bump_token_version, change_password, deactivate_user

pytestmark = pytest.mark.django_db


def test_new_user_starts_at_zero():
    user = User.objects.create_user("t@x.com", "a-long-password-1")
    user.refresh_from_db()
    assert user.token_version == 0


def test_bump_is_a_single_atomic_increment(django_assert_num_queries):
    user = User.objects.create_user("t@x.com", "a-long-password-1")
    with django_assert_num_queries(2):  # the UPDATE, then the refresh
        assert bump_token_version(user) == 1


def test_deactivation_bumps():
    user = User.objects.create_user("t@x.com", "a-long-password-1")
    deactivate_user(user)
    user.refresh_from_db()
    assert (user.is_active, user.token_version) == (False, 1)


def test_password_change_bumps():
    user = User.objects.create_user("t@x.com", "a-long-password-1")
    change_password(user, "another-long-password-2")
    user.refresh_from_db()
    assert user.token_version == 1
    assert user.check_password("another-long-password-2")


def test_admin_deactivation_bumps(client):
    from tests.accounts.helpers import make_staff, otp_login

    admin_user, device = make_staff("boss@x.com", is_superuser=True)
    otp_login(client, admin_user, device)
    target = User.objects.create_user("t@x.com", "a-long-password-1")
    response = client.post(
        f"/admin/accounts/user/{target.pk}/change/",
        {
            "email": "t@x.com",
            "first_name": "",
            "last_name": "",
            "phone": "",
            "country": "",
            "preferred_language": "",
            "is_staff": "",
            "is_active": "",
            "date_joined_0": "2026-01-01",
            "date_joined_1": "00:00:00",
        },
    )
    assert response.status_code == 302, response.content[:500]
    target.refresh_from_db()
    assert (target.is_active, target.token_version) == (False, 1)
