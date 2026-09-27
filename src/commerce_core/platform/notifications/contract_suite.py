"""The notification channel port's contract suite (W2a, phase plan section 4 item 10).

Every adapter, core's or a deployment's, must pass it. Use it from a test
module::

    from commerce_core.platform.notifications.contract_suite import ChannelContract

    class TestMyAdapter(ChannelContract):
        def make_channel(self): ...
        def delivered(self): ...          # list of (recipients, subject, body) seen by the fake server
        def make_unreachable_channel(self): ...

Tests using it need a database (they open and close transactions).
"""

import pytest
from django.db import transaction

from commerce_core.platform.notifications.port import (
    DeliveryFailed,
    NotificationChannel,
    OutboundMessage,
    SendInsideTransaction,
)


class ChannelContract:
    def make_channel(self) -> NotificationChannel:
        raise NotImplementedError

    def make_unreachable_channel(self) -> NotificationChannel:
        raise NotImplementedError

    def delivered(self) -> list[tuple[tuple[str, ...], str, str]]:
        raise NotImplementedError

    def test_implements_the_port(self):
        assert isinstance(self.make_channel(), NotificationChannel)

    @pytest.mark.django_db(transaction=True)
    def test_delivers_to_every_recipient_with_body_intact(self):
        message = OutboundMessage(
            ("a@example.test", "b@example.test"), "Subject ✓", "مرحبا — body\nline 2"
        )
        self.make_channel().send(message)
        recipients, subject, body = self.delivered()[-1]
        assert set(recipients) == {"a@example.test", "b@example.test"}
        assert subject == "Subject ✓"
        assert "مرحبا — body" in body and "line 2" in body

    @pytest.mark.django_db
    def test_refuses_to_send_inside_a_transaction(self):
        before = len(self.delivered())
        with transaction.atomic(), pytest.raises(SendInsideTransaction):
            self.make_channel().send(OutboundMessage(("a@example.test",), "s", "b"))
        assert len(self.delivered()) == before

    @pytest.mark.django_db(transaction=True)
    def test_unreachable_server_is_a_transient_failure(self):
        with pytest.raises(DeliveryFailed) as info:
            self.make_unreachable_channel().send(OutboundMessage(("a@example.test",), "s", "b"))
        assert info.value.transient

    @pytest.mark.django_db(transaction=True)
    def test_no_recipients_is_a_permanent_failure(self):
        with pytest.raises(DeliveryFailed) as info:
            self.make_channel().send(OutboundMessage((), "s", "b"))
        assert not info.value.transient
