from django_otp.oath import TOTP
from django_otp.plugins.otp_totp.models import TOTPDevice

from commerce_core.accounts.models import User

PASSWORD = "a-long-staff-password-1"


def make_staff(email="staff@x.com", *, device=True, **fields) -> tuple[User, TOTPDevice | None]:
    user = User.objects.create_user(email, PASSWORD, is_staff=True, **fields)
    dev = TOTPDevice.objects.create(user=user, name="default", confirmed=True) if device else None
    return user, dev


def current_token(device: TOTPDevice) -> str:
    totp = TOTP(device.bin_key, device.step, device.t0, device.digits, device.drift)
    return f"{totp.token():0{device.digits}d}"


def otp_login(client, user, device, token=None):
    data = {"username": user.email, "password": PASSWORD}
    if device is not None:
        data |= {"otp_device": device.persistent_id, "otp_token": token or current_token(device)}
    return client.post("/admin/login/?next=/admin/", data)
