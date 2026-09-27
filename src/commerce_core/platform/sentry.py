"""Error tracking over the Sentry protocol (X14, X15, X13a).

Initialised at boot when ``ERROR_TRACKING_DSN`` is set (production refuses
to boot without it). ``before_send`` removes request bodies, cookies and
auth headers, reduces the user to an internal id, and scrubs everything
else with the same policy as the logs.
"""

import sentry_sdk
from sentry_sdk.integrations.django import DjangoIntegration

from commerce_core.platform import context
from commerce_core.platform.redaction import REDACTED, scrub

_DROP_HEADERS = {"authorization", "cookie", "x-csrftoken", "proxy-authorization"}


def before_send(event: dict, hint: dict | None = None) -> dict:
    request = event.get("request")
    if isinstance(request, dict):
        request.pop("data", None)  # raw payloads never leave (X15)
        request.pop("cookies", None)
        request.pop("query_string", None)
        headers = request.get("headers") or {}
        request["headers"] = {
            k: (REDACTED if k.lower() in _DROP_HEADERS else v) for k, v in headers.items()
        }
    user = event.get("user")
    if isinstance(user, dict):
        event["user"] = {"id": user["id"]} if "id" in user else {}
    rid = context.request_id.get()
    if rid:
        event.setdefault("tags", {})["request_id"] = rid
    return scrub(event)


def before_breadcrumb(crumb: dict, hint: dict | None = None) -> dict:
    return scrub(crumb)


def init(values: dict, version: str) -> bool:
    dsn = values.get("ERROR_TRACKING_DSN")
    if not dsn:
        return False
    sentry_sdk.init(
        dsn=dsn,
        environment=values["DEPLOYMENT_ENV"],
        release=f"commerce-core@{version}",
        send_default_pii=False,
        include_local_variables=False,
        max_request_body_size="never",
        before_send=before_send,
        before_breadcrumb=before_breadcrumb,
        integrations=[DjangoIntegration()],
    )
    return True
