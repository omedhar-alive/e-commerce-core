"""X10a: request_id is server-generated; an inbound id is kept only as upstream_request_id."""

import re

import pytest
from django.test import RequestFactory

from commerce_core.platform.api.middleware import RequestIdMiddleware

pytestmark = pytest.mark.django_db


def _run(header=None):
    seen = {}

    def view(request):
        from django.http import HttpResponse

        seen["rid"] = request.request_id
        seen["upstream"] = request.upstream_request_id
        return HttpResponse()

    headers = {"HTTP_X_REQUEST_ID": header} if header is not None else {}
    response = RequestIdMiddleware(view)(RequestFactory().get("/", **headers))
    return response, seen


def test_request_id_is_random_and_returned():
    first, a = _run()
    second, b = _run()
    assert re.fullmatch(r"[0-9a-f]{32}", a["rid"])
    assert a["rid"] != b["rid"]
    assert first["X-Request-ID"] == a["rid"]


def test_inbound_id_never_replaces_request_id():
    response, seen = _run("client-chosen-id")
    assert seen["rid"] != "client-chosen-id"
    assert response["X-Request-ID"] == seen["rid"]


def test_valid_upstream_id_is_kept():
    _, seen = _run("abc.DEF_123-x")
    assert seen["upstream"] == "abc.DEF_123-x"


@pytest.mark.parametrize("bad", ["x" * 65, "has space", "semi;colon", "new\nline", ""])
def test_invalid_upstream_id_is_dropped(bad):
    _, seen = _run(bad)
    assert seen["upstream"] is None
