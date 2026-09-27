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


MAX_BODY_BYTES = 1024 * 1024  # Q3c: 1 MB. Webhooks get their own cap (A10).


class BodyCapMiddleware:
    """Refuse a body over the cap before anything parses it (Q3c).

    The declared ``Content-Length`` is checked before the body is read. A
    body without one is empty to Django's WSGI handler, and Django's own
    ``DATA_UPLOAD_MAX_MEMORY_SIZE`` (set to the same cap) backs this up.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        try:
            declared = int(request.META.get("CONTENT_LENGTH") or 0)
        except ValueError:
            declared = MAX_BODY_BYTES + 1
        if declared > MAX_BODY_BYTES:
            from commerce_core.platform.errors.exceptions import PayloadTooLarge
            from commerce_core.platform.errors.handlers import response_for

            return response_for(PayloadTooLarge(), request)
        return self.get_response(request)
