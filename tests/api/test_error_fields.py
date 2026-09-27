"""T2 (X7): the error body's ``field`` names the offending input."""

import pytest
from django.contrib.auth.models import Permission

from commerce_core.accounts.models import User
from commerce_core.platform.errors.exceptions import DomainError
from commerce_core.platform.errors.handlers import error_body
from commerce_core.platform.runtime_settings.services import change_runtime_setting

pytestmark = pytest.mark.django_db


@pytest.mark.parametrize(
    "params, field",
    [
        ({"colour": "red"}, "colour"),
        ({"zeta": "1", "alpha": "2"}, "alpha"),
        ({"sort": "owner"}, "sort"),
        ({"sort": "-secret"}, "sort"),
        ({"limit": "abc"}, "limit"),
        ({"limit": "0"}, "limit"),
        ({"limit": "-3"}, "limit"),
        ({"cursor": "not-base64!"}, "cursor"),
    ],
)
def test_list_refusals_name_their_field(client, params, field):
    response = client.get("/test-api/probes", params)
    assert response.status_code == 400
    error = response.json()["error"]
    assert error["code"] == "validation_error"
    assert error["field"] == field


def _manager():
    user = User.objects.create_user("m@x.com", "a-long-password-1", is_staff=True)
    user.user_permissions.add(Permission.objects.get(codename="manage_settings"))
    return User.objects.get(pk=user.pk)


@pytest.mark.parametrize(
    "kwargs, field",
    [
        ({"kind": "dark_mode", "enabled": True, "reason": "x"}, "kind"),
        (
            {"kind": "provider_enabled", "provider_key": "mock", "enabled": False, "reason": "x"},
            "provider_key",
        ),
        (
            {
                "kind": "checkout_kill_switch",
                "provider_key": "mock",
                "enabled": True,
                "reason": "x",
            },
            "provider_key",
        ),
        ({"kind": "checkout_kill_switch", "enabled": True, "reason": "   "}, "reason"),
        ({"kind": "checkout_kill_switch", "enabled": True, "reason": ""}, "reason"),
    ],
)
def test_runtime_setting_refusals_name_their_field(kwargs, field):
    with pytest.raises(DomainError) as info:
        change_runtime_setting(_manager(), **kwargs)
    body = error_body(info.value, "rid-1")["error"]
    assert body["code"] == "validation_error"
    assert body["field"] == field
    assert body["request_id"] == "rid-1"
