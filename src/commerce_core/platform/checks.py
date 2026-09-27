"""Startup checks (``manage.py check`` and every process's boot)."""

from django.contrib import admin
from django.core.checks import Error, register

from commerce_core.platform.db.governed import governed_models
from commerce_core.platform.errors.exceptions import DomainError
from commerce_core.platform.errors.registry import ERRORS


class _Superuser:
    is_active = is_staff = is_superuser = True

    def has_perm(self, perm, obj=None):
        return True


class _Request:
    user = _Superuser()
    method = "GET"


@register()
def governed_models_are_read_only_in_admin(app_configs, **kwargs):
    """D7b: no admin change form can save a governed model."""
    errors = []
    request = _Request()
    for model in governed_models():
        model_admin = admin.site._registry.get(model)
        if model_admin is None:
            continue
        if (
            model_admin.has_add_permission(request)
            or model_admin.has_change_permission(request)
            or model_admin.has_delete_permission(request)
        ):
            errors.append(
                Error(
                    f"{model.__name__} is governed by {model.GOVERNANCE.rule} but its admin can "
                    "add, change or delete rows",
                    hint="Subclass commerce_core.platform.admin_base.ReadOnlyModelAdmin.",
                    id="commerce.E001",
                )
            )
    return errors


@register()
def every_error_code_has_a_class(app_configs, **kwargs):
    """X5a: every registered code is bound to exactly one exception class."""
    missing = sorted(set(ERRORS) - set(DomainError.by_code))
    return [
        Error(f"error code {code!r} has no exception class", id="commerce.E002") for code in missing
    ]
