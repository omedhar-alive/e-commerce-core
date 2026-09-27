"""The client IP, from trusted proxy hops only (A9b).

With ``TRUSTED_PROXY_HOPS = n``, the client is the address ``n`` hops before
``REMOTE_ADDR`` in ``X-Forwarded-For + [REMOTE_ADDR]``: each trusted proxy
appended the address it received from. Entries further left were written by
the client and are ignored. Every IP limit and every recorded IP (A9, V1, R6)
reads through this function; nothing else reads ``X-Forwarded-For``.
"""

import ipaddress

from commerce_core.platform.conf import get_setting


def _valid(address: str) -> str | None:
    try:
        return str(ipaddress.ip_address(address.strip()))
    except ValueError:
        return None


def client_ip(request) -> str:
    remote = _valid(request.META.get("REMOTE_ADDR", "")) or "0.0.0.0"
    hops = get_setting("TRUSTED_PROXY_HOPS")
    if hops == 0:
        return remote
    forwarded = [a for a in request.META.get("HTTP_X_FORWARDED_FOR", "").split(",") if a.strip()]
    chain = forwarded + [remote]
    if len(chain) <= hops:
        return remote
    return _valid(chain[-(hops + 1)]) or remote
