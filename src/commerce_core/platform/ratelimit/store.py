"""The PostgreSQL rate-limit store (A9).

``hit()`` is one atomic statement per request, shared by every worker and
instance. Call it outside the request's own transaction, so a rolled-back
request still counts. ``DatabaseCache`` is not used: its ``incr`` is a read
then a separate write, which races.
"""

import hashlib
import hmac
import math
from dataclasses import dataclass
from datetime import UTC, datetime

from django.db import connection
from django.utils import timezone

from commerce_core.platform.conf import get_setting
from commerce_core.platform.errors.exceptions import RateLimited
from commerce_core.platform.ratelimit.policies import RateLimitPolicy

_HIT = """
INSERT INTO platform_ratelimitcounter (policy, principal_hash, window_start, count, expires_at)
VALUES (%s, %s, %s, 1, %s)
ON CONFLICT (policy, principal_hash, window_start)
DO UPDATE SET count = platform_ratelimitcounter.count + 1
RETURNING count
"""


@dataclass(frozen=True)
class Hit:
    count: int
    allowed: bool
    retry_after: int


def principal_hash(policy: RateLimitPolicy, principal: str) -> str:
    key = hashlib.sha256(("ratelimit:" + get_setting("SECRET_KEY")).encode()).digest()
    return hmac.new(key, f"{policy.name}\0{principal}".encode(), hashlib.sha256).hexdigest()


def window_start(policy: RateLimitPolicy, now: datetime) -> datetime:
    size = policy.window.total_seconds()
    return datetime.fromtimestamp(math.floor(now.timestamp() / size) * size, tz=UTC)


def hit(policy: RateLimitPolicy, principal: str, now: datetime | None = None) -> Hit:
    now = now or timezone.now()
    start = window_start(policy, now)
    end = start + policy.window
    with connection.cursor() as cur:
        cur.execute(_HIT, [policy.name, principal_hash(policy, principal), start, end])
        count = cur.fetchone()[0]
    return Hit(
        count=count,
        allowed=count <= policy.maximum,
        retry_after=max(1, math.ceil((end - now).total_seconds())),
    )


def enforce(policy: RateLimitPolicy, principal: str, now: datetime | None = None) -> None:
    """Count this request; raise ``rate_limited`` if it is over the policy's maximum."""
    result = hit(policy, principal, now)
    if not result.allowed:
        raise RateLimited(retry_after=result.retry_after)
