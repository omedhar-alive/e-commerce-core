"""Q2, Q2a, Q2b, Q3: keyset pages on a public tiebreaker, allowlisted params, constant queries."""

import base64
import json
from datetime import timedelta

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from commerce_core.platform.api.pagination import REGISTRY, encode_cursor
from commerce_core.platform.checks import every_list_sort_and_filter_is_indexed
from tests.testapp.models import PageProbe

pytestmark = pytest.mark.django_db
BASE = timezone.now().replace(microsecond=0)


def _make(n, *, start=0, owner="alice", same_time=False, category="c"):
    return PageProbe.objects.bulk_create(
        PageProbe(
            created_at=BASE if same_time else BASE + timedelta(seconds=start + i),
            name=f"n{start + i:04d}",
            category=category,
            owner=owner,
        )
        for i in range(n)
    )


def _get(client, owner="alice", **params):
    response = client.get("/test-api/probes", params, HTTP_X_TEST_OWNER=owner)
    return response


def _walk(client, between_pages=None, **params):
    seen, cursor = [], None
    while True:
        query = dict(params, **({"cursor": cursor} if cursor else {}))
        body = _get(client, **query).json()
        seen += [item["public_id"] for item in body["items"]]
        cursor = body["next_cursor"]
        if between_pages:
            between_pages()
            between_pages = None
        if not cursor:
            return seen


def test_page_size_defaults_to_20_and_clamps_at_100(client):
    _make(150)
    assert len(_get(client).json()["items"]) == 20
    assert len(_get(client, limit=1000).json()["items"]) == 100
    assert len(_get(client, limit=7).json()["items"]) == 7


def test_no_total_count(client):
    _make(3)
    assert set(_get(client).json()) == {"items", "next_cursor"}


@pytest.mark.parametrize("sort", ["created_at", "-created_at", "name", "-name"])
def test_paging_while_rows_are_inserted_never_repeats_or_skips(client, sort):
    original = {p.public_id for p in _make(45)}
    seen = _walk(client, between_pages=lambda: _make(10, start=1000), sort=sort, limit=10)
    assert len(seen) == len(set(seen))
    assert original <= set(seen)


def test_ties_on_the_sort_key_are_broken_by_public_id(client):
    rows = {p.public_id for p in _make(35, same_time=True)}
    seen = _walk(client, limit=10)
    assert sorted(seen) == sorted(rows) and len(seen) == 35
    assert seen == sorted(seen)


def test_no_cursor_decodes_to_a_primary_key(client):
    rows = _make(30)
    pks = {str(p.pk) for p in PageProbe.objects.all()}
    cursor = _get(client, limit=5).json()["next_cursor"]
    decoded = json.loads(base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4)))
    sort, _, public_id = decoded
    assert sort == "created_at"
    assert public_id in {p.public_id for p in rows}
    assert not any(str(part) in pks for part in decoded)


def test_responses_carry_no_primary_key(client):
    _make(3)
    for item in _get(client).json()["items"]:
        assert set(item) == {"public_id", "name", "created_at"}


@pytest.mark.parametrize("param", [{"colour": "red"}, {"sort": "owner"}, {"sort": "-secret"}])
def test_unknown_filter_or_sort_is_400(client, param):
    response = _get(client, **param)
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "validation_error"


def test_allowlisted_filter_works(client):
    _make(3, category="a")
    _make(2, start=10, category="b")
    assert len(_get(client, category="b").json()["items"]) == 2


def test_tampered_cursor_is_400_or_stays_scoped(client):
    _make(5, owner="alice")
    bob = _make(5, start=100, owner="bob")
    assert _get(client, cursor="not-base64!").status_code == 400
    wrong_sort = encode_cursor("name", "n0000", "x")
    assert _get(client, cursor=wrong_sort).status_code == 400
    # A cursor pointing into bob's rows still returns only alice's.
    forged = encode_cursor(
        "created_at", {"t": (BASE - timedelta(days=1)).isoformat()}, bob[0].public_id
    )
    items = _get(client, owner="alice", cursor=forged).json()["items"]
    assert items and all(i["public_id"] not in {b.public_id for b in bob} for i in items)


@pytest.mark.parametrize("n", [10, 30])
def test_query_count_is_constant_at_two_sizes(client, n):
    _make(n)
    with CaptureQueriesContext(connection) as ctx:
        _get(client, limit=5)
    page_queries = [q for q in ctx.captured_queries if "testapp_pageprobe" in q["sql"]]
    assert len(page_queries) == 1


def test_every_allowlisted_sort_and_filter_is_indexed():
    assert REGISTRY
    assert every_list_sort_and_filter_is_indexed(None) == []


# T1 (Q2a): page boundaries.


@pytest.mark.parametrize("limit", [1, 5, 20])
def test_exactly_limit_rows_has_no_next_cursor(client, limit):
    _make(limit)
    body = _get(client, limit=limit).json()
    assert len(body["items"]) == limit
    assert body["next_cursor"] is None


@pytest.mark.parametrize("limit", [1, 5, 20])
def test_limit_plus_one_rows_has_a_next_cursor_to_the_last_row(client, limit):
    rows = _make(limit + 1)
    first = _get(client, limit=limit).json()
    assert len(first["items"]) == limit and first["next_cursor"]
    second = _get(client, limit=limit, cursor=first["next_cursor"]).json()
    assert [i["public_id"] for i in second["items"]] == [rows[-1].public_id]
    assert second["next_cursor"] is None


def test_limit_of_one_is_valid(client):
    _make(3)
    response = _get(client, limit=1)
    assert response.status_code == 200
    assert len(response.json()["items"]) == 1
