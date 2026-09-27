"""The notification channel port (W2a). A deployment may supply its own adapter.

This interface is public API (W4a): changing it is a breaking change.

An adapter sends one message outside any transaction (T1, T2) and either
returns normally or raises ``DeliveryFailed``. Delivery is at-least-once:
callers record success only after ``send`` returns, so a crash in between
can repeat a message and never loses one.
"""

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable


@dataclass(frozen=True)
class OutboundMessage:
    recipients: tuple[str, ...]
    subject: str
    body_text: str
    headers: dict[str, str] = field(default_factory=dict)


class DeliveryFailed(Exception):
    """The channel could not deliver. ``transient`` failures are retried."""

    def __init__(self, reason: str, *, transient: bool):
        super().__init__(reason)
        self.transient = transient


class SendInsideTransaction(RuntimeError):
    pass


@runtime_checkable
class NotificationChannel(Protocol):
    name: str

    def send(self, message: OutboundMessage) -> None: ...
