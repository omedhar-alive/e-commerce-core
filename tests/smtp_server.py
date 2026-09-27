"""A local SMTP server for the notification contract suite (aiosmtpd)."""

import email
import email.policy
import socket

from aiosmtpd.controller import Controller


class _Inbox:
    def __init__(self):
        self.messages = []

    async def handle_DATA(self, server, session, envelope):
        parsed = email.message_from_bytes(envelope.content, policy=email.policy.default)
        self.messages.append(
            (tuple(envelope.rcpt_tos), str(parsed["Subject"]), parsed.get_content())
        )
        return "250 OK"


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class LocalSmtp:
    def __init__(self):
        self.inbox = _Inbox()
        self.port = free_port()
        self.controller = Controller(self.inbox, hostname="127.0.0.1", port=self.port)

    def __enter__(self):
        self.controller.start()
        return self

    def __exit__(self, *exc):
        self.controller.stop()
