"""Keyset pagination and per-endpoint filter/sort allowlists (Q2, Q2a, Q2b).

* Default page size 20, maximum 100; a larger request is clamped.
* No total count.
* Every page orders by its sort key and then a unique **public** identifier;
  the cursor encodes those two values, never a primary key (O6).
* Filters and sorts are allowlisted per endpoint; an unknown query parameter
  is a 400 ``validation_error``, never ignored. Each allowed sort is backed by
  an index on (sort key, public identifier), and each filter by an index led
  by its column; a startup check verifies both (``checks.py``).
* The Django admin keeps its own offset pagination.
"""

import base64
import binascii
import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from django.db.models import Model, Q, QuerySet

from commerce_core.platform.errors.exceptions import ValidationFailed

DEFAULT_PAGE_SIZE = 20
MAX_PAGE_SIZE = 100
RESERVED_PARAMS = frozenset({"cursor", "limit", "sort"})


@dataclass(frozen=True)
class ListSpec:
    model: type[Model]
    public_field: str
    sorts: dict[str, str]  # public sort name -> model field
    default_sort: str
    filters: dict[str, str] = field(default_factory=dict)  # query param -> model field


REGISTRY: list[ListSpec] = []


def list_spec(**kwargs) -> ListSpec:
    spec = ListSpec(**kwargs)
    if spec.default_sort.lstrip("-") not in spec.sorts:
        raise ValueError("default_sort must be an allowed sort")
    REGISTRY.append(spec)
    return spec


def _encode(value: Any) -> Any:
    if isinstance(value, datetime):
        return {"t": value.isoformat()}
    return value


def _decode(value: Any) -> Any:
    if isinstance(value, dict) and set(value) == {"t"}:
        return datetime.fromisoformat(value["t"])
    return value


def encode_cursor(sort: str, sort_value: Any, public_id: str) -> str:
    raw = json.dumps([sort, _encode(sort_value), public_id], separators=(",", ":"))
    return base64.urlsafe_b64encode(raw.encode()).decode().rstrip("=")


def decode_cursor(cursor: str, sort: str) -> tuple[Any, str]:
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        cursor_sort, value, public_id = json.loads(base64.urlsafe_b64decode(padded))
        if cursor_sort != sort or not isinstance(public_id, str):
            raise ValueError
        return _decode(value), public_id
    except (ValueError, TypeError, binascii.Error, json.JSONDecodeError):
        raise ValidationFailed(field="cursor") from None


@dataclass
class Page:
    items: list
    next_cursor: str | None


def paginate(spec: ListSpec, queryset: QuerySet, params: dict[str, str]) -> Page:
    """Filter, sort and page ``queryset``, which the caller has already scoped (A6)."""
    unknown = set(params) - RESERVED_PARAMS - set(spec.filters)
    if unknown:
        raise ValidationFailed(field=sorted(unknown)[0])

    sort = params.get("sort", spec.default_sort)
    if sort.lstrip("-") not in spec.sorts:
        raise ValidationFailed(field="sort")
    descending = sort.startswith("-")
    sort_field = spec.sorts[sort.lstrip("-")]

    try:
        limit = int(params.get("limit", DEFAULT_PAGE_SIZE))
    except ValueError:
        raise ValidationFailed(field="limit") from None
    if limit < 1:
        raise ValidationFailed(field="limit")
    limit = min(limit, MAX_PAGE_SIZE)

    for name, model_field in spec.filters.items():
        if name in params:
            queryset = queryset.filter(**{model_field: params[name]})

    prefix = "-" if descending else ""
    queryset = queryset.order_by(f"{prefix}{sort_field}", f"{prefix}{spec.public_field}")

    if "cursor" in params:
        value, public_id = decode_cursor(params["cursor"], sort)
        op = "lt" if descending else "gt"
        queryset = queryset.filter(
            Q(**{f"{sort_field}__{op}": value})
            | Q(**{sort_field: value, f"{spec.public_field}__{op}": public_id})
        )

    rows = list(queryset[: limit + 1])
    items, more = rows[:limit], len(rows) > limit
    next_cursor = None
    if more:
        last = items[-1]
        next_cursor = encode_cursor(
            sort, getattr(last, sort_field), getattr(last, spec.public_field)
        )
    return Page(items=items, next_cursor=next_cursor)
