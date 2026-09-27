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


@register()
def every_route_has_an_explicit_schema(app_configs, **kwargs):
    """Q3a: a route without an explicit response schema fails startup."""
    from commerce_core.platform.api.core import APIS
    from commerce_core.platform.api.guard import check_api

    return [Error(problem, id="commerce.E003") for api in APIS for problem in check_api(api)]


def _index_field_lists(model) -> list[list[str]]:
    lists = [[f.lstrip("-") for f in index.fields] for index in model._meta.indexes]
    lists += [[f.name] for f in model._meta.concrete_fields if f.db_index or f.unique]
    lists += [list(c.fields) for c in model._meta.constraints if getattr(c, "fields", None)]
    return lists


@register()
def every_list_sort_and_filter_is_indexed(app_configs, **kwargs):
    """Q2a, Q2b: each allowed sort has an index on (sort key, public id); each filter leads an index."""
    from commerce_core.platform.api.pagination import REGISTRY

    errors = []
    for spec in REGISTRY:
        indexes = _index_field_lists(spec.model)
        name = spec.model.__name__
        if [spec.public_field] not in indexes:
            errors.append(
                Error(f"{name}.{spec.public_field} is not unique-indexed", id="commerce.E004")
            )
        for sort, column in spec.sorts.items():
            if [column, spec.public_field] not in indexes:
                errors.append(
                    Error(
                        f"{name}: sort {sort!r} has no index on ({column}, {spec.public_field})",
                        id="commerce.E004",
                    )
                )
        for flt, column in spec.filters.items():
            if not any(fields and fields[0] == column for fields in indexes):
                errors.append(
                    Error(
                        f"{name}: filter {flt!r} has no index led by {column}", id="commerce.E004"
                    )
                )
    return errors
