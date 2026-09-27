"""Core's email adapter for the notification channel port (W2a), over SMTP."""

import smtplib
import socket
from email.message import EmailMessage
from email.utils import make_msgid

from commerce_core.platform.conf import get_setting
from commerce_core.platform.http import in_transaction
from commerce_core.platform.notifications.port import (
    DeliveryFailed,
    OutboundMessage,
    SendInsideTransaction,
)

_TRANSIENT = (
    smtplib.SMTPServerDisconnected,
    smtplib.SMTPConnectError,
    socket.timeout,
    ConnectionError,
    OSError,
)


class SmtpEmailChannel:
    name = "email"

    def __init__(
        self,
        *,
        host=None,
        port=None,
        username=None,
        password=None,
        security=None,
        timeout=None,
        sender=None,
    ):
        self.host = host or get_setting("SMTP_HOST")
        self.port = port or get_setting("SMTP_PORT")
        self.username = get_setting("SMTP_USERNAME") if username is None else username
        self.password = get_setting("SMTP_PASSWORD") if password is None else password
        self.security = security or get_setting("SMTP_SECURITY")
        self.timeout = timeout or get_setting("SMTP_TIMEOUT").total_seconds()
        self.sender = sender or get_setting("EMAIL_FROM")

    def _connect(self) -> smtplib.SMTP:
        if self.security == "tls":
            return smtplib.SMTP_SSL(self.host, self.port, timeout=self.timeout)
        server = smtplib.SMTP(self.host, self.port, timeout=self.timeout)
        if self.security == "starttls":
            server.starttls()
        return server

    def send(self, message: OutboundMessage) -> None:
        if in_transaction():
            raise SendInsideTransaction("send outside transaction.atomic() (T1, T2)")
        if not message.recipients:
            raise DeliveryFailed("no recipients", transient=False)
        email = EmailMessage()
        email["From"] = self.sender
        email["To"] = ", ".join(message.recipients)
        email["Subject"] = message.subject
        email["Message-ID"] = make_msgid()
        for key, value in message.headers.items():
            email[key] = value
        email.set_content(message.body_text)
        try:
            with self._connect() as server:
                if self.username:
                    server.login(self.username, self.password)
                server.send_message(email)
        except smtplib.SMTPRecipientsRefused as exc:
            raise DeliveryFailed("recipients refused", transient=False) from exc
        except smtplib.SMTPAuthenticationError as exc:
            raise DeliveryFailed("authentication failed", transient=False) from exc
        except smtplib.SMTPResponseException as exc:
            raise DeliveryFailed(f"smtp {exc.smtp_code}", transient=exc.smtp_code < 500) from exc
        except _TRANSIENT as exc:
            raise DeliveryFailed("connection failed", transient=True) from exc


class InvalidChannelAdapter(TypeError):
    pass


def email_channel():
    """The configured email channel adapter (EMAIL_CHANNEL_ADAPTER)."""
    from django.utils.module_loading import import_string

    from commerce_core.platform.notifications.port import NotificationChannel

    channel = import_string(get_setting("EMAIL_CHANNEL_ADAPTER"))()
    if not isinstance(channel, NotificationChannel):
        raise InvalidChannelAdapter("EMAIL_CHANNEL_ADAPTER does not implement the channel port")
    return channel
