"""A6a: the named permission set and the three default groups."""

import pytest
from django.contrib.auth.models import Group, Permission

from commerce_core.accounts import permissions as perms
from commerce_core.accounts.models import User
from commerce_core.platform.errors.exceptions import PermissionDenied

pytestmark = pytest.mark.django_db

A6A = {
    "collect_cash",
    "request_refund",
    "approve_refund",
    "approve_cancellation",
    "adjust_stock",
    "resolve_review",
    "manage_returns",
    "change_address",
    "create_shipment",
    "record_delivery",
    "record_receipt",
    "view_payment_events",
    "manage_settings",
}


def test_all_a6a_permissions_exist_in_the_database():
    assert set(perms.PERMISSIONS) == A6A
    stored = set(
        Permission.objects.filter(
            content_type__app_label="accounts", content_type__model="corepermissions"
        ).values_list("codename", flat=True)
    )
    assert stored == A6A


def test_default_groups_match_the_handoff():
    for name, expected in perms.DEFAULT_GROUPS.items():
        group = Group.objects.get(name=name)
        assert set(group.permissions.values_list("codename", flat=True)) == set(expected), name


def test_manage_settings_is_in_no_default_group():
    assert not Group.objects.filter(permissions__codename="manage_settings").exists()


def test_seed_never_overwrites_a_regrouped_deployment():
    from importlib import import_module

    from django.apps import apps

    seed = import_module("commerce_core.accounts.migrations.0003_seed_groups").seed
    support = Group.objects.get(name="support")
    support.permissions.set(Permission.objects.filter(codename="adjust_stock"))
    seed(apps, None)
    assert list(support.permissions.values_list("codename", flat=True)) == ["adjust_stock"]


def test_require_refuses_without_the_named_permission():
    user = User.objects.create_user("n@x.com", "a-long-password-1", is_staff=True)
    with pytest.raises(PermissionDenied):
        perms.require(user, perms.MANAGE_SETTINGS)
    user.user_permissions.add(Permission.objects.get(codename="manage_settings"))
    user = User.objects.get(pk=user.pk)  # fresh permission cache
    perms.require(user, perms.MANAGE_SETTINGS)


def test_require_refuses_inactive_users():
    user = User.objects.create_user("i@x.com", "a-long-password-1", is_active=False)
    user.user_permissions.add(Permission.objects.get(codename="manage_settings"))
    with pytest.raises(PermissionDenied):
        perms.require(User.objects.get(pk=user.pk), perms.MANAGE_SETTINGS)
