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


class AlertSeverity(models.TextChoices):
    CRITICAL = "critical"
    WARNING = "warning"


class AlertStatus(models.TextChoices):
    OPEN = "open"
    ACKNOWLEDGED = "acknowledged"
    RESOLVED = "resolved"


class Alert(models.Model):
    """A durable alert (N5). Written by ``raise_alert()`` in its cause's transaction.

    The subject is a typed pair, never a foreign key, so a resolved alert
    never blocks its subject's retention delete (O7, I8). The code set is
    closed in code (``alerts.codes``), not by a DB CHECK, so adding a code
    never needs a constraint migration on a live table.
    """

    code = models.CharField(max_length=64)
    severity = models.CharField(max_length=10, choices=AlertSeverity.choices)
    subject_type = models.CharField(max_length=64)
    subject_id = models.CharField(max_length=128)
    status = models.CharField(max_length=15, choices=AlertStatus.choices, default=AlertStatus.OPEN)
    # Internal identifiers only; never personal data (X13a).
    context = models.JSONField(default=dict, blank=True)
    first_raised_at = models.DateTimeField(default=timezone.now)
    last_raised_at = models.DateTimeField(default=timezone.now)
    raise_count = models.PositiveIntegerField(default=1)
    notified_at = models.DateTimeField(null=True, blank=True)
    acknowledged_at = models.DateTimeField(null=True, blank=True)
    acknowledged_by_type = models.CharField(max_length=20, blank=True)
    acknowledged_by_id = models.CharField(max_length=64, blank=True)
    resolved_at = models.DateTimeField(null=True, blank=True)
    resolved_by_type = models.CharField(max_length=20, blank=True)
    resolved_by_id = models.CharField(max_length=64, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["code", "subject_type", "subject_id"],
                condition=~models.Q(status="resolved"),
                name="alert_one_open_per_subject",
            ),
            models.CheckConstraint(
                condition=models.Q(severity__in=["critical", "warning"]),
                name="alert_severity_valid",
            ),
            models.CheckConstraint(
                condition=models.Q(status__in=["open", "acknowledged", "resolved"]),
                name="alert_status_valid",
            ),
        ]
        indexes = [
            models.Index(
                fields=["notified_at"],
                name="alert_unnotified",
                condition=models.Q(notified_at__isnull=True),
            ),
            models.Index(fields=["status", "severity"], name="alert_status_severity"),
        ]

    def __str__(self):
        return f"{self.code} {self.subject_type}:{self.subject_id}"


class RateLimitCounter(models.Model):
    """One row per (policy, principal, window): the shared rate-limit store (A9).

    Incremented by one ``INSERT … ON CONFLICT DO UPDATE … RETURNING``, so the
    increment and the read of the new count are one atomic statement. The
    principal is stored as a keyed hash, never as an email or IP (X13a).
    """

    policy = models.CharField(max_length=64)
    principal_hash = models.CharField(max_length=64)
    window_start = models.DateTimeField()
    count = models.PositiveIntegerField()
    expires_at = models.DateTimeField()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["policy", "principal_hash", "window_start"], name="ratelimit_window_uniq"
            )
        ]
        indexes = [models.Index(fields=["expires_at"], name="ratelimit_expires")]

    def __str__(self):
        return f"{self.policy} {self.window_start:%Y-%m-%d %H:%M}"
