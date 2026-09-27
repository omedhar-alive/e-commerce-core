"""Test-only API endpoints, served at /test-api/ in test settings."""

from django.db import connection, transaction
from ninja import Schema

from commerce_core.platform.api.core import create_api
from commerce_core.platform.errors.exceptions import NotFound, RateLimited

test_api = create_api(urls_namespace="test_api")


class Line(Schema):
    quantity: int


class Payload(Schema):
    lines: list[Line]


@test_api.post("/validate", response={200: dict})
def validate(request, payload: Payload):
    return {"ok": True}


@test_api.get("/missing", response={200: dict})
def missing(request):
    raise NotFound()


@test_api.get("/limited", response={200: dict})
def limited(request):
    raise RateLimited(retry_after=17)


@test_api.get("/boom", response={200: dict})
def boom(request):
    raise RuntimeError("secret internals /srv/app.py SELECT * FROM users")


@test_api.get("/lock", response={200: dict})
def lock(request):
    with transaction.atomic(), connection.cursor() as cur:
        cur.execute("SELECT id FROM testapp_lockprobe WHERE id = 1 FOR UPDATE")
    return {"ok": True}
