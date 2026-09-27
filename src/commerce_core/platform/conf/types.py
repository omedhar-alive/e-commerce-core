"""Value parsers for the settings registry. Each returns the typed value or raises ``ValueError``."""

import re
import zoneinfo
from datetime import datetime, timedelta
from urllib.parse import unquote, urlsplit

_DURATION = re.compile(r"^(\d+)(s|m|h|d)$")
_UNITS = {"s": "seconds", "m": "minutes", "h": "hours", "d": "days"}


def parse_str(raw: str) -> str:
    return raw


def parse_int(raw: str) -> int:
    return int(raw.strip())


def parse_bool(raw: str) -> bool:
    value = raw.strip().lower()
    if value in {"1", "true", "yes", "on"}:
        return True
    if value in {"0", "false", "no", "off"}:
        return False
    raise ValueError("expected true or false")


def parse_duration(raw: str) -> timedelta:
    """``<n><unit>`` with unit s, m, h or d, e.g. ``30m`` or ``90d``."""
    match = _DURATION.match(raw.strip())
    if not match:
        raise ValueError("expected a duration such as 30m, 4h or 90d")
    number, unit = match.groups()
    return timedelta(**{_UNITS[unit]: int(number)})


def parse_list(raw: str) -> tuple[str, ...]:
    return tuple(item.strip() for item in raw.split(",") if item.strip())


def parse_timezone(raw: str) -> str:
    name = raw.strip()
    zoneinfo.ZoneInfo(name)  # raises ZoneInfoNotFoundError (a KeyError)
    return name


def parse_datetime(raw: str) -> datetime:
    value = datetime.fromisoformat(raw.strip())
    if value.tzinfo is None:
        raise ValueError("expected an ISO 8601 timestamp with a UTC offset")
    return value


def parse_database_url(raw: str) -> dict:
    """``postgresql://user:password@host:port/dbname?sslmode=require`` → Django DATABASES entry."""
    parts = urlsplit(raw.strip())
    if parts.scheme not in {"postgres", "postgresql"}:
        raise ValueError("expected a postgresql:// URL")
    name = parts.path.lstrip("/")
    if not name:
        raise ValueError("the URL names no database")
    options = {}
    for pair in filter(None, parts.query.split("&")):
        key, _, value = pair.partition("=")
        options[key] = unquote(value)
    return {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": unquote(name),
        "USER": unquote(parts.username or ""),
        "PASSWORD": unquote(parts.password or ""),
        "HOST": parts.hostname or "",
        "PORT": str(parts.port or ""),
        "OPTIONS": options,
    }
