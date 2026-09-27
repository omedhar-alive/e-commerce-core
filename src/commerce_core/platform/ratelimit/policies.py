"""Rate-limit policy declarations (A9).

Every sensitive endpoint names its policy: principal, window, maximum. The
store is always ``RateLimitCounter``; an exceeded limit answers 429
``rate_limited`` with ``Retry-After`` (X9). Each phase declares its own
endpoints' policies (decision 7); phase 1 declares none.
"""

from dataclasses import dataclass
from datetime import timedelta


@dataclass(frozen=True)
class RateLimitPolicy:
    name: str
    principal: str  # what the key identifies: "account", "ip", "email", "token family", ...
    window: timedelta
    maximum: int


POLICIES: dict[str, RateLimitPolicy] = {}


def declare(name: str, *, principal: str, window: timedelta, maximum: int) -> RateLimitPolicy:
    if name in POLICIES:
        raise ValueError(f"rate-limit policy {name!r} declared twice")
    if maximum < 1 or window <= timedelta(0):
        raise ValueError("a policy needs a positive window and maximum")
    policy = RateLimitPolicy(name, principal, window, maximum)
    POLICIES[name] = policy
    return policy
