"""F1, F1a, F1e, A11, X10, X14, M3a, D4a: the settings registry validates at boot."""

from datetime import timedelta

import pytest

from commerce_core.platform import conf
from commerce_core.platform.conf import boot
from commerce_core.platform.conf.registry import SETTINGS, ChangeClass, Role
from tests.settings import TEST_ENV


def _env(**changes):
    env = dict(TEST_ENV)
    for key, value in changes.items():
        if value is None:
            env.pop(key, None)
        else:
            env[key] = value
    return env


def _problems(role=None, **changes):
    with pytest.raises(boot.ConfigurationError) as info:
        boot.load(role, _env(**changes))
    return info.value.problems


def test_test_env_is_valid():
    boot.load(None, TEST_ENV)


def test_missing_required_secret_fails_boot():
    assert _problems(SECRET_KEY=None) == ["SECRET_KEY is required but not set"]


def test_missing_required_setting_fails_boot():
    assert "STORE_TIMEZONE is required but not set" in _problems(STORE_TIMEZONE=None)


def test_mistyped_setting_fails_boot():
    assert "MIGRATION_LOCK_RETRIES is not a valid integer" in _problems(
        MIGRATION_LOCK_RETRIES="five"
    )
    assert "STORE_TIMEZONE is not a valid timezone" in _problems(STORE_TIMEZONE="Mars/Base")


def test_out_of_range_setting_fails_boot():
    assert any(
        "ADMIN_SESSION_IDLE_TIMEOUT is above" in p
        for p in _problems(ADMIN_SESSION_IDLE_TIMEOUT="9h")
    )
    assert any(
        "MIGRATION_LOCK_RETRIES is below" in p for p in _problems(MIGRATION_LOCK_RETRIES="-1")
    )


def test_task_result_retention_out_of_range_fails_boot():
    assert any(
        "TASK_RESULT_RETENTION is above" in p for p in _problems(TASK_RESULT_RETENTION="366d")
    )
    assert any(
        "TASK_RESULT_RETENTION is below" in p for p in _problems(TASK_RESULT_RETENTION="12h")
    )


def test_task_result_retention_defaults_to_seven_days():
    assert boot.load(None, TEST_ENV)["TASK_RESULT_RETENTION"] == timedelta(days=7)


def test_unknown_store_currency_fails_boot():
    assert any("STORE_CURRENCY" in p for p in _problems(STORE_CURRENCY="XYZ"))


def test_store_currency_validated_against_iso_table():
    for code in ("EGP", "KWD", "JPY"):
        boot.load(None, _env(STORE_CURRENCY=code))


def test_production_requires_error_tracking_dsn():
    assert "ERROR_TRACKING_DSN is required in production (X14)" in _problems(
        DEPLOYMENT_ENV="production"
    )


def test_production_refuses_debug():
    problems = _problems(
        DEPLOYMENT_ENV="production", DEBUG="true", ERROR_TRACKING_DSN="https://k@e.test/1"
    )
    assert problems == ["DEBUG must be false in production (X10)"]


def test_demo_may_run_without_error_tracking():
    boot.load(None, _env(DEPLOYMENT_ENV="demo"))


def test_default_language_must_be_installed():
    assert "STORE_DEFAULT_LANGUAGE must be one of INSTALLED_LANGUAGES" in _problems(
        INSTALLED_LANGUAGES="ar", STORE_DEFAULT_LANGUAGE="en"
    )


def test_secret_values_never_appear_in_boot_errors():
    secret = "short-secret-value"
    problems = _problems(SECRET_KEY=secret, MONITORING_TOKEN="tiny-token")
    assert not any(secret in p or "tiny-token" in p for p in problems)


def test_every_setting_has_default_or_manual_step():
    for setting in SETTINGS:
        assert not setting.required or setting.manual_step, setting.name


def test_backup_rpo_and_rto_declared_with_defaults():
    values = boot.load(None, TEST_ENV)
    assert values["BACKUP_RPO"] == timedelta(hours=1)
    assert values["BACKUP_RTO"] == timedelta(hours=4)


def test_every_setting_declares_change_class_and_type():
    for setting in SETTINGS:
        assert setting.change_class in ChangeClass
        assert setting.type_label


def test_runtime_settings_are_exactly_the_kill_switch_in_phase_1():
    runtime = {s.name for s in SETTINGS if s.change_class is ChangeClass.RUNTIME}
    assert runtime == {"CHECKOUT_KILL_SWITCH"}


def test_get_setting_refuses_undeclared_runtime_and_unread():
    conf.install(boot.load(Role.JOB, _env(JOB_DATABASE_URL="postgresql://u:p@h/db")))
    with pytest.raises(conf.SettingNotAvailable):
        conf.get_setting("NOT_A_SETTING")
    with pytest.raises(conf.SettingNotAvailable):
        conf.get_setting("CHECKOUT_KILL_SWITCH")
    with pytest.raises(conf.SettingNotAvailable):
        conf.get_setting("WEB_DATABASE_URL")
    assert conf.get_setting("JOB_DATABASE_URL")["NAME"] == "db"
