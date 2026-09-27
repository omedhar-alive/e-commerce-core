"""The only way code reads configuration (F1a).

``get_setting(name)`` returns the value validated at boot. Reading
``os.environ`` or ``django.conf.settings`` for configuration anywhere else is
refused by a static check (W8a).
"""

from typing import Any

from commerce_core.platform.conf.registry import BY_NAME, ChangeClass

_loaded: dict[str, Any] | None = None


class SettingNotAvailable(LookupError):
    """The setting is undeclared, runtime-class, or not read by this process."""


def install(values: dict[str, Any]) -> None:
    global _loaded
    _loaded = dict(values)


def get_setting(name: str) -> Any:
    setting = BY_NAME.get(name)
    if setting is None:
        raise SettingNotAvailable(f"{name} is not declared in the settings registry")
    if setting.change_class is ChangeClass.RUNTIME:
        raise SettingNotAvailable(f"{name} is a runtime setting; read it from RuntimeSetting")
    if _loaded is None:
        raise SettingNotAvailable("settings have not been loaded; boot has not run")
    try:
        return _loaded[name]
    except KeyError:
        raise SettingNotAvailable(f"{name} is not read by this process") from None
