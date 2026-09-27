"""A9b: the client IP comes only from trusted proxy hops."""

import pytest
from django.test import RequestFactory

from commerce_core.platform.ratelimit.client_ip import client_ip


def _request(remote="10.0.0.9", xff=None):
    meta = {"REMOTE_ADDR": remote}
    if xff is not None:
        meta["HTTP_X_FORWARDED_FOR"] = xff
    return RequestFactory().get("/", **meta)


def test_no_trusted_hops_uses_remote_addr_and_ignores_xff(override_setting):
    override_setting("TRUSTED_PROXY_HOPS", 0)
    assert client_ip(_request(xff="1.2.3.4")) == "10.0.0.9"


def test_one_trusted_hop_uses_the_address_the_proxy_saw(override_setting):
    override_setting("TRUSTED_PROXY_HOPS", 1)
    assert client_ip(_request(xff="203.0.113.7")) == "203.0.113.7"


def test_spoofed_xff_does_not_change_the_ip(override_setting):
    override_setting("TRUSTED_PROXY_HOPS", 1)
    honest = client_ip(_request(xff="203.0.113.7"))
    spoofed = client_ip(_request(xff="6.6.6.6, 1.1.1.1, 203.0.113.7"))
    assert honest == spoofed == "203.0.113.7"


def test_two_hops(override_setting):
    override_setting("TRUSTED_PROXY_HOPS", 2)
    assert client_ip(_request(xff="6.6.6.6, 203.0.113.7, 10.0.0.2")) == "203.0.113.7"


@pytest.mark.parametrize("xff", ["", "not-an-ip"])
def test_missing_or_garbage_falls_back_to_remote_addr(override_setting, xff):
    override_setting("TRUSTED_PROXY_HOPS", 1)
    assert client_ip(_request(xff=xff)) == "10.0.0.9"


def test_ipv6_is_normalized(override_setting):
    override_setting("TRUSTED_PROXY_HOPS", 1)
    assert client_ip(_request(xff="2001:DB8::1")) == "2001:db8::1"
