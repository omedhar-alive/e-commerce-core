"""Rate-limit window pruning (A9, N4)."""

from datetime import timedelta

from django.utils import timezone

from commerce_core.platform.jobs.registry import Every, register

BATCH = 5000


@register(
    "rate_limit_window_pruning",
    schedule=Every(timedelta(minutes=10)),
    max_staleness=timedelta(hours=1),
)
def prune_expired_windows() -> None:
    """Delete rate-limit rows whose window has ended."""
    from commerce_core.platform.models import RateLimitCounter

    now = timezone.now()
    while True:
        batch = list(
            RateLimitCounter.objects.filter(expires_at__lt=now).values_list("pk", flat=True)[:BATCH]
        )
        if not batch:
            return
        RateLimitCounter.objects.filter(pk__in=batch).delete()
