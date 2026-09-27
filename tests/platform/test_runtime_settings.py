"""F1c, A6a, D7, S4: runtime settings change only through the audited service."""

import pytest
from django.contrib.auth.models import Permission
from django.db import IntegrityError, transaction
from psycopg import errors

from commerce_core.accounts.models import User
from commerce_core.platform.db import roles
from commerce_core.platform.errors.exceptions import PermissionDenied, ValidationFailed
from commerce_core.platform.models import RuntimeSetting, SettingChange
from commerce_core.platform.runtime_settings import services
from tests.accounts.helpers import current_token, make_staff

pytestmark = pytest.mark.django_db

KILL = "checkout_kill_switch"


def _manager(email="m@x.com"):
    user = User.objects.create_user(email, "a-long-password-1", is_staff=True)
    user.user_permissions.add(Permission.objects.get(codename="manage_settings"))
    return User.objects.get(pk=user.pk)


def test_kill_switch_row_is_seeded_off():
    row = RuntimeSetting.objects.get(kind=KILL)
    assert row.provider_key is None and row.enabled is False
    assert services.is_checkout_disabled() is False


def test_change_writes_audit_row_with_typed_actor():
    user = _manager()
    change = services.change_runtime_setting(user, kind=KILL, enabled=True, reason="card testing")
    assert services.is_checkout_disabled() is True
    change.refresh_from_db()
    assert (change.kind, change.before, change.after) == (KILL, False, True)
    assert (change.actor_type, change.actor_id) == ("staff", str(user.pk))
    assert change.reason == "card testing"


def test_no_op_change_writes_no_audit_row():
    assert services.change_runtime_setting(_manager(), kind=KILL, enabled=False, reason="x") is None
    assert not SettingChange.objects.exists()


def test_refused_without_manage_settings():
    user = User.objects.create_user("n@x.com", "a-long-password-1", is_staff=True)
    with pytest.raises(PermissionDenied):
        services.change_runtime_setting(user, kind=KILL, enabled=True, reason="x")
    assert not services.is_checkout_disabled()
    assert not SettingChange.objects.exists()


def test_reason_is_required():
    with pytest.raises(ValidationFailed) as info:
        services.change_runtime_setting(_manager(), kind=KILL, enabled=True, reason="  ")
    assert info.value.field == "reason"


def test_failure_rolls_back_both(monkeypatch):
    user = _manager()

    def fail(*args, **kwargs):
        raise IntegrityError("audit insert failed")

    monkeypatch.setattr(SettingChange.objects, "create", fail)
    with pytest.raises(IntegrityError):
        services.change_runtime_setting(user, kind=KILL, enabled=True, reason="x")
    assert not services.is_checkout_disabled()


def test_provider_kind_refused_without_registered_provider():
    with pytest.raises(ValidationFailed) as info:
        services.change_runtime_setting(
            _manager(), kind="provider_enabled", provider_key="mock", enabled=False, reason="x"
        )
    assert info.value.field == "provider_key"


def test_unknown_kind_refused():
    with pytest.raises(ValidationFailed):
        services.change_runtime_setting(_manager(), kind="dark_mode", enabled=True, reason="x")


def _insert(role_conn, kind, provider_key):
    conn = role_conn(roles.WEB)
    conn.execute(
        "INSERT INTO platform_runtimesetting (kind, provider_key, enabled, updated_at)"
        " VALUES (%s, %s, false, now())",
        (kind, provider_key),
    )


def test_unknown_kind_refused_by_db(role_conn):
    with pytest.raises(errors.CheckViolation, match="runtimesetting_kind_allowed"):
        _insert(role_conn, "dark_mode", None)


def test_kill_switch_with_provider_key_refused_by_db(role_conn):
    with pytest.raises(errors.CheckViolation, match="runtimesetting_provider_key_pairing"):
        _insert(role_conn, KILL, "mock")


def test_provider_toggle_without_key_refused_by_db(role_conn):
    with pytest.raises(errors.CheckViolation, match="runtimesetting_provider_key_pairing"):
        _insert(role_conn, "provider_enabled", None)


def test_second_kill_switch_row_refused_by_db(role_conn):
    with pytest.raises(errors.UniqueViolation, match="runtimesetting_kind_provider_uniq"):
        _insert(role_conn, KILL, None)


@pytest.mark.parametrize("role", roles.DML_ROLES)
@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE platform_settingchange SET reason = 'rewritten'",
        "DELETE FROM platform_settingchange",
    ],
)
def test_web_and_job_cannot_update_or_delete_setting_change(role_conn, role, statement):
    conn = role_conn(role, autocommit=False)
    try:
        conn.execute(
            "INSERT INTO platform_settingchange (kind, before, after, actor_type, actor_id,"
            " reason, created_at) VALUES ('checkout_kill_switch', false, true, 'staff', '1',"
            " 'r', now())"
        )
        with pytest.raises(errors.InsufficientPrivilege):
            conn.execute(statement)
    finally:
        conn.rollback()


def test_actor_type_is_a_closed_set_in_the_db():
    with pytest.raises(IntegrityError, match="settingchange_actor_type_valid"):
        with transaction.atomic():
            SettingChange.objects.create(
                kind=KILL, before=False, after=True, actor_type="someone", actor_id="1", reason="r"
            )


def _admin_client(client, *, grant):
    user, device = make_staff("admin@x.com")
    user.user_permissions.add(
        *Permission.objects.filter(codename__in=["view_runtimesetting", "view_settingchange"])
    )
    if grant:
        user.user_permissions.add(Permission.objects.get(codename="manage_settings"))
    client.post(
        "/admin/login/?next=/admin/",
        {
            "username": user.email,
            "password": "a-long-staff-password-1",
            "otp_device": device.persistent_id,
            "otp_token": current_token(device),
        },
    )
    return user


def test_admin_forms_are_read_only_even_for_superusers(admin_user, rf):
    from django.contrib import admin

    request = rf.get("/")
    request.user = admin_user
    for model in (RuntimeSetting, SettingChange):
        model_admin = admin.site._registry[model]
        assert not model_admin.has_add_permission(request)
        assert not model_admin.has_change_permission(request)
        assert not model_admin.has_delete_permission(request)


def test_admin_change_view_changes_setting_with_permission(client):
    _admin_client(client, grant=True)
    row = RuntimeSetting.objects.get(kind=KILL)
    response = client.post(
        f"/admin/platform/runtimesetting/{row.pk}/change-setting/",
        {"enabled": "on", "reason": "incident 42"},
    )
    assert response.status_code == 302
    assert services.is_checkout_disabled()
    assert SettingChange.objects.get().reason == "incident 42"


def test_admin_change_view_refused_without_permission(client):
    _admin_client(client, grant=False)
    row = RuntimeSetting.objects.get(kind=KILL)
    client.post(
        f"/admin/platform/runtimesetting/{row.pk}/change-setting/",
        {"enabled": "on", "reason": "x"},
    )
    assert not services.is_checkout_disabled()
    assert not SettingChange.objects.exists()


def test_governed_admin_check_passes_and_catches_a_writable_admin():
    from django.contrib import admin

    from commerce_core.platform import checks

    assert checks.governed_models_are_read_only_in_admin(None) == []
    registry = admin.site._registry
    original = registry[SettingChange]
    registry[SettingChange] = admin.ModelAdmin(SettingChange, admin.site)
    try:
        errors_found = checks.governed_models_are_read_only_in_admin(None)
    finally:
        registry[SettingChange] = original
    assert [e.id for e in errors_found] == ["commerce.E001"]
