"""Typed actors (S4): who did something, never as free text.

The id is the user id for ``staff`` and ``customer``, the job name for
``system``, and the ``PaymentEvent`` id for ``provider_event``.
"""

from dataclasses import dataclass
from enum import StrEnum

from django.db import models


class ActorType(StrEnum):
    STAFF = "staff"
    CUSTOMER = "customer"
    SYSTEM = "system"
    PROVIDER_EVENT = "provider_event"


@dataclass(frozen=True)
class Actor:
    type: ActorType
    id: str

    @classmethod
    def staff(cls, user) -> "Actor":
        return cls(ActorType.STAFF, str(user.pk))

    @classmethod
    def system(cls, job_name: str) -> "Actor":
        return cls(ActorType.SYSTEM, job_name)


def actor_type_check(prefix: str, field: str = "actor_type") -> models.CheckConstraint:
    return models.CheckConstraint(
        condition=models.Q(**{f"{field}__in": [t.value for t in ActorType]}),
        name=f"{prefix}_{field}_valid",
    )
