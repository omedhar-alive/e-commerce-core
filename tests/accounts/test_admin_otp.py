"""A6b: staff reach the admin only with TOTP; idle sessions end."""

from datetime import timedelta

import pytest
import time_machine
from django.utils import timezone

from tests.accounts.helpers import make_staff, otp_login

pytestmark = pytest.mark.django_db


def test_admin_login_page_responds(client):
    assert client.get("/admin/login/").status_code == 200


def test_login_with_device_and_token_reaches_admin(client):
    user, device = make_staff()
    response = otp_login(client, user, device)
    assert response.status_code == 302 and response["Location"] == "/admin/"
    assert client.get("/admin/").status_code == 200


def test_staff_without_device_cannot_log_in(client):
    user, _ = make_staff(device=False)
    response = otp_login(client, user, None)
    assert response.status_code == 200  # form redisplayed with errors
    assert client.get("/admin/").status_code == 302


def test_wrong_token_is_refused(client):
    user, device = make_staff()
    response = otp_login(client, user, device, token="000000")
    assert response.status_code == 200
    assert client.get("/admin/").status_code == 302


def test_password_session_without_second_factor_is_refused(client):
    user, _ = make_staff()
    client.force_login(user)  # authenticated, never OTP-verified
    response = client.get("/admin/")
    assert response.status_code == 302 and "/admin/login/" in response["Location"]


def test_idle_session_expires(client):
    user, device = make_staff()
    start = timezone.now()
    with time_machine.travel(start, tick=False) as traveller:
        otp_login(client, user, device)
        assert client.get("/admin/").status_code == 200
        traveller.shift(timedelta(minutes=29))
        assert client.get("/admin/").status_code == 200
        traveller.shift(timedelta(minutes=31))
        response = client.get("/admin/")
    assert response.status_code == 302 and "/admin/login/" in response["Location"]
