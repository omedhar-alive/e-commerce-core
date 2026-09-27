"""Models governed by D7 or D7a grants, and the write discipline they need (D7b).

A governed model subclasses ``GovernedModel`` and declares ``GOVERNANCE``.
Its migration applies the matching ``ProtectTable`` grant; a test compares
the two for every governed model.

* An update must name its columns. ``save()`` on an existing row without
  ``update_fields`` raises ``BareSaveOnGovernedModel`` before SQL is sent; the
  grants refuse it in the database anyway.
* Inserts are unaffected: the grants restrict ``UPDATE`` and ``DELETE``.
* No ``auto_now`` field unless it is updatable and every write names it.
* The admin shows these models read-only (``GovernedModelAdmin``, enforced by
  a system check).
"""

from dataclasses import dataclass

from django.apps import apps
from django.db import models


class BareSaveOnGovernedModel(Exception):
    """A full-row save on a table whose columns are frozen by grant (D7b)."""


@dataclass(frozen=True)
class Governance:
    rule: str  # "D7" (append-only) or "D7a" (frozen committed columns)
    update_fields: tuple[str, ...] = ()
    allow_delete: bool = False


class GovernedModel(models.Model):
    GOVERNANCE: Governance

    class Meta:
        abstract = True

    def save(self, *args, update_fields=None, force_insert=False, **kwargs):
        if not (self._state.adding or force_insert) and update_fields is None:
            raise BareSaveOnGovernedModel(
                f"{type(self).__name__} is governed by {self.GOVERNANCE.rule}: "
                "name the columns with save(update_fields=[...]) or QuerySet.update()."
            )
        return super().save(*args, update_fields=update_fields, force_insert=force_insert, **kwargs)


def governed_models() -> list[type[GovernedModel]]:
    return [m for m in apps.get_models() if issubclass(m, GovernedModel)]
