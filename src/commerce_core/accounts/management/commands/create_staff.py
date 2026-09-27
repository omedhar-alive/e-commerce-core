"""``manage.py create_staff``: create a staff user and print their TOTP provisioning URI once.

The admin cannot be reached without a confirmed TOTP device (A6b), so the
first device is provisioned here. The password is prompted for (or read from
standard input), never taken from the command line. Runs as the web role.
"""

import getpass
import sys

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django_otp.plugins.otp_totp.models import TOTPDevice

from commerce_core.accounts.models import User
from commerce_core.accounts.normalize import normalize_email
from commerce_core.accounts.services import change_password, check_password_rules
from commerce_core.platform.errors.exceptions import ValidationFailed


def read_password(stdin=None) -> str:
    stdin = stdin or sys.stdin
    if stdin.isatty():
        first = getpass.getpass("Password: ")
        if first != getpass.getpass("Password (again): "):
            raise CommandError("Passwords do not match.")
        return first
    return stdin.readline().rstrip("\n")


class Command(BaseCommand):
    help = "Create a staff user with a TOTP device; prints the provisioning URI once."

    def add_arguments(self, parser):
        parser.add_argument("email")
        parser.add_argument("--first-name", default="")
        parser.add_argument("--last-name", default="")
        parser.add_argument("--group", action="append", default=[], help="Default group to join.")
        parser.add_argument(
            "--superuser",
            action="store_true",
            help="Grant every permission, manage_settings included (the owner's account).",
        )

    def handle(self, *args, email, first_name, last_name, group, superuser, **options):
        from django.contrib.auth.models import Group

        email = normalize_email(email)
        if User.objects.filter(email=email).exists():
            raise CommandError("A user with this email already exists.")
        groups = list(Group.objects.filter(name__in=group))
        if len(groups) != len(set(group)):
            raise CommandError("Unknown group name.")
        password = read_password()
        try:
            check_password_rules(
                User(email=email, first_name=first_name, last_name=last_name), password
            )
        except ValidationFailed as exc:
            raise CommandError(
                "Password refused: " + "; ".join(f["message"] for f in exc.fields)
            ) from None
        with transaction.atomic():
            user = User(
                email=email,
                first_name=first_name,
                last_name=last_name,
                is_staff=True,
                is_superuser=superuser,
            )
            user.set_unusable_password()
            user.save(force_insert=True)
            change_password(user, password)
            user.groups.set(groups)
            device = TOTPDevice.objects.create(user=user, name="default", confirmed=True)
        self.stdout.write(f"Staff user {user.pk} created.")
        self.stdout.write(
            "Enroll this TOTP URI in an authenticator app now; it is not shown again:"
        )
        self.stdout.write(device.config_url)
