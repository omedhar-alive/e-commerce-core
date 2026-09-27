"""Test-only models. Installed only in test settings; never shipped."""

from django.db import models

from commerce_core.platform.db.governed import Governance, GovernedModel
from commerce_core.platform.ids import new_public_id
from commerce_core.platform.money import CurrencyField, MoneyAmountField


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


class MoneyProbe(models.Model):
    """A money column on a test-only model (M1b)."""

    amount = MoneyAmountField()
    currency = CurrencyField()


class PageProbe(models.Model):
    """Rows behind the test-only list endpoint (Q2, Q2a, Q2b, Q3)."""

    public_id = models.CharField(max_length=16, unique=True, default=new_public_id)
    created_at = models.DateTimeField()
    name = models.CharField(max_length=50)
    category = models.CharField(max_length=20)
    owner = models.CharField(max_length=20, default="alice")

    class Meta:
        indexes = [
            models.Index(fields=["created_at", "public_id"], name="pageprobe_created_pub"),
            models.Index(fields=["name", "public_id"], name="pageprobe_name_pub"),
            models.Index(fields=["category"], name="pageprobe_category"),
        ]
