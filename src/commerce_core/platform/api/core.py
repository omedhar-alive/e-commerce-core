"""The ninja API factory. Every API instance uses core's error handlers (X7)."""

from ninja import NinjaAPI

from commerce_core.platform.errors import handlers


def create_api(**kwargs) -> NinjaAPI:
    kwargs.setdefault("title", "Commerce API")
    kwargs.setdefault("version", "1")
    api = NinjaAPI(**kwargs)
    handlers.install(api)
    return api


api = create_api(urls_namespace="api")
