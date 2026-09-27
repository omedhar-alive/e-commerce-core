"""Q3a: every route has an explicit response schema that exposes no primary key."""

from ninja import Schema

from commerce_core.platform.api.core import APIS, create_api
from commerce_core.platform.api.guard import check_api
from commerce_core.platform.checks import every_route_has_an_explicit_schema


def _throwaway(name):
    api = create_api(urls_namespace=name)
    APIS.remove(api)
    return api


def test_all_registered_routes_pass():
    assert every_route_has_an_explicit_schema(None) == []


def test_route_without_schema_fails():
    api = _throwaway("guard_a")

    @api.get("/x")
    def x(request):
        return {}

    assert any("no explicit response schema" in p for p in check_api(api))


def test_route_returning_bare_dict_fails():
    api = _throwaway("guard_b")

    @api.get("/x", response={200: dict})
    def x(request):
        return {}

    assert any("not a schema" in p for p in check_api(api))


def test_schema_exposing_id_fails_even_nested():
    api = _throwaway("guard_c")

    class Inner(Schema):
        id: int

    class Outer(Schema):
        public_id: str
        inner: list[Inner]

    @api.get("/x", response={200: Outer})
    def x(request):
        return {}

    assert any("exposes ['id']" in p for p in check_api(api))
