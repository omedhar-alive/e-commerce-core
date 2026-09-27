"""Request-level middleware: request id (X10a) and the body cap (Q3c)."""

import re
import secrets

from commerce_core.platform import context

_UPSTREAM_ID = re.compile(r"^[A-Za-z0-9._-]{1,64}$")


class RequestIdMiddleware:
    """Every request gets a random, server-generated ``request_id`` (X10a).

    An inbound ``X-Request-ID`` never replaces it. A valid one (at most 64
    characters of ``[A-Za-z0-9._-]``) is kept as ``upstream_request_id`` for
    the logs; anything else is dropped.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        rid = secrets.token_hex(16)
        inbound = request.headers.get("X-Request-ID", "")
        upstream = inbound if _UPSTREAM_ID.fullmatch(inbound) else None
        request.request_id = rid
        request.upstream_request_id = upstream
        tokens = (context.request_id.set(rid), context.upstream_request_id.set(upstream))
        try:
            response = self.get_response(request)
        finally:
            context.request_id.reset(tokens[0])
            context.upstream_request_id.reset(tokens[1])
        response["X-Request-ID"] = rid
        return response
