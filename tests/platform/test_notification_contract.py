"""W2a: core's SMTP adapter passes the notification channel port's contract suite."""

import pytest

from commerce_core.platform.notifications.contract_suite import ChannelContract
from commerce_core.platform.notifications.smtp import (
    InvalidChannelAdapter,
    SmtpEmailChannel,
    email_channel,
)
from tests.smtp_server import free_port


class TestSmtpAdapter(ChannelContract):
    @pytest.fixture(autouse=True)
    def _server(self, smtp_server):
        self.server = smtp_server

    def make_channel(self):
        return SmtpEmailChannel(host="127.0.0.1", port=self.server.port, security="none", timeout=5)

    def make_unreachable_channel(self):
        return SmtpEmailChannel(host="127.0.0.1", port=free_port(), security="none", timeout=2)

    def delivered(self):
        return self.server.inbox.messages


def test_configured_adapter_must_implement_the_port(override_setting):
    override_setting("EMAIL_CHANNEL_ADAPTER", "builtins.object")
    with pytest.raises(InvalidChannelAdapter):
        email_channel()


def test_default_adapter_is_core_smtp():
    assert isinstance(email_channel(), SmtpEmailChannel)
