"""The ninja API factory. Every API uses core's error handlers (X7) and is route-guarded (Q3a)."""

from ninja import NinjaAPI

from commerce_core.platform.errors import handlers

APIS: list[NinjaAPI] = []


def create_api(**kwargs) -> NinjaAPI:
    kwargs.setdefault("title", "Commerce API")
    kwargs.setdefault("version", "1")
    # The OpenAPI document is generated for the buyer docs; it is not served.
    kwargs.setdefault("docs_url", None)
    kwargs.setdefault("openapi_url", None)
    api = NinjaAPI(**kwargs)
    handlers.install(api)
    APIS.append(api)
    return api


api = create_api(urls_namespace="api")
