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


class JobSchedule(models.Model):
    """One row per registered job (N4a; decision 14).

    ``run_scheduler`` claims due rows with ``FOR UPDATE SKIP LOCKED`` so a
    second scheduler can never enqueue the same run. The worker records start
    and success; ``/health/jobs`` and the staleness check read
    ``last_succeeded_at`` against the job's maximum staleness.
    """

    name = models.CharField(max_length=100, unique=True)
    next_run_at = models.DateTimeField()
    last_enqueued_at = models.DateTimeField(null=True, blank=True)
    last_started_at = models.DateTimeField(null=True, blank=True)
    last_succeeded_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(default=timezone.now)

    def __str__(self):
        return self.name


class BusinessDayRun(models.Model):
    """Marks a business-day job as run for one store-local date (L1a)."""

    job_name = models.CharField(max_length=100)
    local_date = models.DateField()
    ran_at = models.DateTimeField(default=timezone.now)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["job_name", "local_date"], name="businessdayrun_job_date_uniq"
            )
        ]

    def __str__(self):
        return f"{self.job_name} {self.local_date}"
