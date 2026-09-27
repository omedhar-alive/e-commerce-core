"""Platform models."""

from django.db import models
from django.utils import timezone

from commerce_core.platform.actors import actor_type_check
from commerce_core.platform.db.governed import Governance, GovernedModel


class RuntimeSettingKind(models.TextChoices):
    CHECKOUT_KILL_SWITCH = "checkout_kill_switch"
    PROVIDER_ENABLED = "provider_enabled"


class RuntimeSetting(models.Model):
    """The only settings that change without a deploy (F1c; decision 22).

    Exactly the checkout kill switch (N1) and one enable/disable row per
    payment provider (N2). Changed only through ``change_runtime_setting()``.
    """

    kind = models.CharField(max_length=32, choices=RuntimeSettingKind.choices)
    # NULL for the kill switch; the provider's registry key for a toggle.
    provider_key = models.CharField(max_length=64, null=True, blank=True)  # noqa: DJ001 (NULL = kill switch)
    enabled = models.BooleanField()
    updated_at = models.DateTimeField(default=timezone.now)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(kind__in=RuntimeSettingKind.values),
                name="runtimesetting_kind_allowed",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(
                        kind=RuntimeSettingKind.CHECKOUT_KILL_SWITCH, provider_key__isnull=True
                    )
                    | models.Q(kind=RuntimeSettingKind.PROVIDER_ENABLED, provider_key__isnull=False)
                ),
                name="runtimesetting_provider_key_pairing",
            ),
            models.UniqueConstraint(
                fields=["kind", "provider_key"],
                nulls_distinct=False,
                name="runtimesetting_kind_provider_uniq",
            ),
        ]

    def __str__(self):
        return self.kind if self.provider_key is None else f"{self.kind}:{self.provider_key}"


class SettingChange(GovernedModel):
    """Audit row for every runtime setting change (F1c). Append-only (D7)."""

    GOVERNANCE = Governance(rule="D7")

    kind = models.CharField(max_length=32)
    provider_key = models.CharField(max_length=64, null=True, blank=True)  # noqa: DJ001 (NULL = kill switch)
    before = models.BooleanField()
    after = models.BooleanField()
    actor_type = models.CharField(max_length=20)
    actor_id = models.CharField(max_length=64)
    reason = models.TextField()
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        constraints = [
            actor_type_check("settingchange"),
            models.CheckConstraint(
                condition=~models.Q(reason=""), name="settingchange_reason_required"
            ),
        ]

    def __str__(self):
        return f"SettingChange {self.pk}"
