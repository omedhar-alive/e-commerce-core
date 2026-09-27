"""Changing a runtime setting (F1c, N1, N2).

Needs ``manage_settings`` (A6a), a reason, and writes one ``SettingChange``
row in the same transaction as the change, under a row lock on the setting.
A failure rolls back both.
"""

from django.db import transaction
from django.utils import timezone

from commerce_core.accounts import permissions
from commerce_core.platform.actors import Actor
from commerce_core.platform.errors.exceptions import NotFound, ValidationFailed
from commerce_core.platform.models import RuntimeSetting, RuntimeSettingKind, SettingChange


def registered_payment_providers() -> frozenset[str]:
    """Provider keys the payment registry knows. None exist before phase 5."""
    return frozenset()


def change_runtime_setting(
    user, *, kind: str, provider_key: str | None = None, enabled: bool, reason: str
) -> SettingChange | None:
    """Set the value; returns the audit row, or ``None`` when nothing changed."""
    permissions.require(user, permissions.MANAGE_SETTINGS)
    if kind not in RuntimeSettingKind.values:
        raise ValidationFailed(field="kind")
    if kind == RuntimeSettingKind.PROVIDER_ENABLED:
        if provider_key not in registered_payment_providers():
            raise ValidationFailed(field="provider_key")
    elif provider_key is not None:
        raise ValidationFailed(field="provider_key")
    reason = (reason or "").strip()
    if not reason:
        raise ValidationFailed(field="reason")

    actor = Actor.staff(user)
    with transaction.atomic():
        try:
            row = RuntimeSetting.objects.select_for_update().get(
                kind=kind, provider_key=provider_key
            )
        except RuntimeSetting.DoesNotExist:
            raise NotFound() from None
        before = row.enabled
        if before == enabled:
            return None
        now = timezone.now()
        RuntimeSetting.objects.filter(pk=row.pk).update(enabled=enabled, updated_at=now)
        return SettingChange.objects.create(
            kind=kind,
            provider_key=provider_key,
            before=before,
            after=enabled,
            actor_type=actor.type,
            actor_id=actor.id,
            reason=reason,
            created_at=now,
        )


def is_checkout_disabled() -> bool:
    """The kill switch (N1). Read from phase 5 onwards."""
    return RuntimeSetting.objects.filter(
        kind=RuntimeSettingKind.CHECKOUT_KILL_SWITCH, enabled=True
    ).exists()
