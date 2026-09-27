"""Boot validation: every setting is checked before a process does anything (F1a, A11).

``load()`` reads each declared setting once, parses it, checks its range,
choices and cross-setting rules, and raises one ``ConfigurationError`` naming
every problem. It never includes a value in a message, so a secret cannot
leak through a boot failure (A12).

A setting scoped to database roles is read only by a process connecting as
one of them: a web process never touches ``MIGRATION_DATABASE_URL``
(decision 23).
"""

from collections.abc import Mapping
from typing import Any

from django.core.exceptions import ImproperlyConfigured

from commerce_core.platform.conf.registry import (
    SETTINGS,
    ChangeClass,
    DeploymentEnv,
    Role,
    Setting,
)


class ConfigurationError(ImproperlyConfigured):
    def __init__(self, problems: list[str]):
        self.problems = problems
        super().__init__("Invalid configuration:\n  " + "\n  ".join(problems))


def applies_to(setting: Setting, role: Role | None) -> bool:
    if setting.change_class is ChangeClass.RUNTIME:
        return False
    return setting.roles is None or role in setting.roles


def _parse(setting: Setting, raw: str | None) -> tuple[Any, str | None]:
    if raw is None or raw.strip() == "":
        if setting.required:
            return None, f"{setting.name} is required but not set"
        return setting.default, None
    try:
        value = setting.parse(raw)
    except (ValueError, LookupError):
        return None, f"{setting.name} is not a valid {setting.type_label}"
    if setting.choices is not None and value not in setting.choices:
        return None, f"{setting.name} must be one of {', '.join(setting.choices)}"
    if setting.minimum is not None and value < setting.minimum:
        return None, f"{setting.name} is below its minimum ({setting.minimum})"
    if setting.maximum is not None and value > setting.maximum:
        return None, f"{setting.name} is above its maximum ({setting.maximum})"
    if setting.check is not None:
        try:
            setting.check(value)
        except ValueError as exc:
            detail = "invalid" if setting.secret else str(exc)
            return None, f"{setting.name}: {detail}"
    return value, None


def _cross_checks(values: dict[str, Any]) -> list[str]:
    problems = []
    production = values.get("DEPLOYMENT_ENV") == DeploymentEnv.PRODUCTION
    if production and values.get("DEBUG"):
        problems.append("DEBUG must be false in production (X10)")
    if production and not values.get("ERROR_TRACKING_DSN"):
        problems.append("ERROR_TRACKING_DSN is required in production (X14)")
    installed = values.get("INSTALLED_LANGUAGES")
    default_language = values.get("STORE_DEFAULT_LANGUAGE")
    if installed and default_language and default_language not in installed:
        problems.append("STORE_DEFAULT_LANGUAGE must be one of INSTALLED_LANGUAGES")
    tracker, logs = values.get("ERROR_TRACKING_RETENTION"), values.get("LOG_RETENTION")
    if tracker and logs and tracker > logs:
        problems.append("ERROR_TRACKING_RETENTION may not exceed LOG_RETENTION (X13a, I8a)")
    if values.get("MONITORING_TOKEN_PREVIOUS"):
        if not values.get("MONITORING_TOKEN"):
            problems.append("MONITORING_TOKEN_PREVIOUS is set without MONITORING_TOKEN")
        if values.get("MONITORING_TOKEN_ROTATED_AT") is None:
            problems.append("MONITORING_TOKEN_PREVIOUS needs MONITORING_TOKEN_ROTATED_AT")
        if values.get("MONITORING_TOKEN_PREVIOUS") == values.get("MONITORING_TOKEN"):
            problems.append("MONITORING_TOKEN_PREVIOUS must differ from MONITORING_TOKEN")
    return problems


def load(role: Role | None, env: Mapping[str, str]) -> dict[str, Any]:
    values: dict[str, Any] = {}
    problems: list[str] = []
    for setting in SETTINGS:
        if not applies_to(setting, role):
            continue
        value, problem = _parse(setting, env.get(setting.name))
        if problem:
            problems.append(problem)
        else:
            values[setting.name] = value
    problems.extend(_cross_checks(values))
    if problems:
        raise ConfigurationError(problems)
    return values
