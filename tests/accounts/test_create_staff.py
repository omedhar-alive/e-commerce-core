"""create_staff: a staff user with a confirmed TOTP device, URI printed once."""

import io

import pytest
from django.core.management import CommandError, call_command
from django_otp.plugins.otp_totp.models import TOTPDevice

from commerce_core.accounts.models import User

pytestmark = pytest.mark.django_db


class Pipe(io.StringIO):
    def isatty(self):
        return False


def _run(monkeypatch, *args, password="a-long-staff-password-1"):
    monkeypatch.setattr("sys.stdin", Pipe(password + "\n"))
    out = io.StringIO()
    call_command("create_staff", *args, stdout=out)
    return out.getvalue()


def test_creates_staff_with_confirmed_device_and_prints_uri(monkeypatch):
    output = _run(monkeypatch, "Owner@X.com", "--superuser")
    user = User.objects.get(email="owner@x.com")
    assert user.is_staff and user.is_superuser
    assert user.check_password("a-long-staff-password-1")
    device = TOTPDevice.objects.get(user=user)
    assert device.confirmed
    assert output.count("otpauth://totp/") == 1


def test_joins_named_groups(monkeypatch):
    _run(monkeypatch, "s@x.com", "--group", "support")
    assert list(User.objects.get(email="s@x.com").groups.values_list("name", flat=True)) == [
        "support"
    ]


def test_weak_password_is_refused_and_nothing_is_created(monkeypatch):
    with pytest.raises(CommandError):
        _run(monkeypatch, "w@x.com", password="short")
    assert not User.objects.filter(email="w@x.com").exists()


def test_password_is_never_an_argument():
    with pytest.raises(CommandError):
        call_command("create_staff", "a@x.com", "--password", "x")
