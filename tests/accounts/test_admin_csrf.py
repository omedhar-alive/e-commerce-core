"""A2, A5: the admin uses sessions, and a state-changing POST without CSRF is refused."""

import pytest
from django.test import Client

from tests.accounts.helpers import PASSWORD, current_token, make_staff, otp_login

pytestmark = pytest.mark.django_db


def test_login_post_without_csrf_token_is_refused():
    user, _ = make_staff()
    client = Client(enforce_csrf_checks=True)
    response = client.post("/admin/login/", {"username": user.email, "password": PASSWORD})
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "permission_denied"


def test_admin_change_post_without_csrf_token_is_refused():
    user, device = make_staff(is_superuser=True)
    client = Client(enforce_csrf_checks=True)
    client.get("/admin/login/")
    token = client.cookies["csrftoken"].value
    client.post(
        "/admin/login/?next=/admin/",
        {
            "username": user.email,
            "password": PASSWORD,
            "otp_device": device.persistent_id,
            "otp_token": current_token(device),
            "csrfmiddlewaretoken": token,
        },
    )
    assert client.get("/admin/").status_code == 200
    response = client.post(f"/admin/accounts/user/{user.pk}/change/", {"email": "new@x.com"})
    assert response.status_code == 403


def test_admin_uses_session_authentication(client):
    user, device = make_staff()
    otp_login(client, user, device)
    assert "sessionid" in client.cookies
