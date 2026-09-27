"""``manage.py seed_demo``: realistic demo data, through the services (phase plan section 4 item 12).

Idempotent: re-running creates nothing that exists. Phase 1 seeds one staff
user per default group, each with a TOTP device. Credentials are printed
once, for users this run created. Runs as the job role. Each later phase
extends it.
"""

import secrets

from django.contrib.auth.models import Group
from django.core.management.base import BaseCommand
from django.db import transaction
from django_otp.plugins.otp_totp.models import TOTPDevice

from commerce_core.accounts.models import User
from commerce_core.accounts.permissions import DEFAULT_GROUPS
from commerce_core.accounts.services import change_password

DEMO_DOMAIN = "demo.invalid"


class Command(BaseCommand):
    help = "Seed idempotent demo data: one staff user per default group."

    def handle(self, *args, **options):
        for group_name in DEFAULT_GROUPS:
            email = f"{group_name}@{DEMO_DOMAIN}"
            if User.objects.filter(email=email).exists():
                self.stdout.write(f"{email}: exists")
                continue
            password = secrets.token_urlsafe(18)
            with transaction.atomic():
                user = User(email=email, first_name=group_name.title(), is_staff=True)
                user.set_unusable_password()
                user.save(force_insert=True)
                change_password(user, password)
                group = Group.objects.filter(name=group_name).first()
                if group is not None:
                    user.groups.add(group)
                device = TOTPDevice.objects.create(user=user, name="default", confirmed=True)
            self.stdout.write(f"{email}: created. Password: {password}")
            self.stdout.write(f"  TOTP: {device.config_url}")
