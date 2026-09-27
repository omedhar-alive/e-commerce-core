"""Test-only models. Installed only in test settings; never shipped."""

from django.db import models

from commerce_core.platform.db.governed import Governance, GovernedModel


class AppendOnlyProbe(GovernedModel):
    """Stands in for an append-only table such as SettingChange (D7)."""

    GOVERNANCE = Governance(rule="D7")

    note = models.CharField(max_length=50)


class GovernedProbe(GovernedModel):
    """Stands in for a D7a table: only ``status`` is updatable."""

    GOVERNANCE = Governance(rule="D7a", update_fields=("status",))

    amount = models.BigIntegerField()
    status = models.CharField(max_length=20)


class UniqueProbe(models.Model):
    """Two named unique constraints, for the X11a helper."""

    code = models.CharField(max_length=20)
    other = models.CharField(max_length=20)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["code"], name="testapp_uniqueprobe_code_uniq"),
            models.UniqueConstraint(fields=["other"], name="testapp_uniqueprobe_other_uniq"),
        ]


class LockProbe(models.Model):
    """A row test code locks from another connection (T4a, D2a)."""

    name = models.CharField(max_length=20)
