"""The closed set of alert codes (N5). Each phase adds the codes it raises."""

from dataclasses import dataclass


@dataclass(frozen=True)
class AlertCode:
    code: str
    severity: str
    description: str


ALERT_CODES: dict[str, AlertCode] = {
    c.code: c
    for c in (
        AlertCode(
            "job_stale",
            "critical",
            "A scheduled job has not succeeded within its maximum staleness (N4).",
        ),
    )
}
