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
