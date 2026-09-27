"""Test-only API endpoints, served at /test-api/ in test settings."""

from datetime import datetime

from django.db import connection, transaction
from ninja import Schema

from commerce_core.platform.api.core import create_api
from commerce_core.platform.api.pagination import list_spec, paginate
from commerce_core.platform.api.schemas import Money
from commerce_core.platform.errors.exceptions import NotFound, RateLimited
from tests.testapp.models import PageProbe

test_api = create_api(urls_namespace="test_api")


class Ok(Schema):
    ok: bool


class Line(Schema):
    quantity: int


class Payload(Schema):
    lines: list[Line]


@test_api.post("/validate", response={200: Ok})
def validate(request, payload: Payload):
    return {"ok": True}


@test_api.get("/missing", response={200: Ok})
def missing(request):
    raise NotFound()


@test_api.get("/limited", response={200: Ok})
def limited(request):
    raise RateLimited(retry_after=17)


@test_api.get("/boom", response={200: Ok})
def boom(request):
    raise RuntimeError("secret internals /srv/app.py SELECT * FROM users")


@test_api.get("/lock", response={200: Ok})
def lock(request):
    with transaction.atomic(), connection.cursor() as cur:
        cur.execute("SELECT id FROM testapp_lockprobe WHERE id = 1 FOR UPDATE")
    return {"ok": True}


class Priced(Schema):
    price: Money


@test_api.get("/money/{currency}/{amount}", response={200: Priced})
def money(request, currency: str, amount: int):
    return {"price": Money.of(amount, currency)}


PROBES = list_spec(
    model=PageProbe,
    public_field="public_id",
    sorts={"created_at": "created_at", "name": "name"},
    default_sort="created_at",
    filters={"category": "category"},
)


class ProbeOut(Schema):
    public_id: str
    name: str
    created_at: datetime


class ProbePage(Schema):
    items: list[ProbeOut]
    next_cursor: str | None


@test_api.get("/probes", response={200: ProbePage})
def probes(request):
    # Scoped to the requesting principal before paging (A6): here, a header.
    owner = request.headers.get("X-Test-Owner", "alice")
    page = paginate(PROBES, PageProbe.objects.filter(owner=owner), request.GET.dict())
    return {"items": page.items, "next_cursor": page.next_cursor}
