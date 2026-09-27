"""The four database roles (D6) and their role-level timeouts (T4a, D2a).

Role names are constants, never configuration: migrations name them in their
grants (D7, D7a), and a migration may not depend on settings (D2f).
"""

from dataclasses import dataclass

MIGRATION = "commerce_migration"
WEB = "commerce_web"
JOB = "commerce_job"
RETENTION = "commerce_retention"

ALL_ROLES = (MIGRATION, WEB, JOB, RETENTION)

# Roles that run application DML. D7 and D7a grants restrict these two.
DML_ROLES = (WEB, JOB)


@dataclass(frozen=True)
class RoleTimeouts:
    lock_timeout: str
    statement_timeout: str
    idle_in_transaction_session_timeout: str

    def as_settings(self) -> dict[str, str]:
        return {
            "lock_timeout": self.lock_timeout,
            "statement_timeout": self.statement_timeout,
            "idle_in_transaction_session_timeout": self.idle_in_transaction_session_timeout,
        }


# T4a for web and job; D2a and D6 for migration ("lock_timeout 3 s; no
# statement timeout"); D6 gives retention the job values.
TIMEOUTS: dict[str, RoleTimeouts] = {
    MIGRATION: RoleTimeouts("3s", "0", "60s"),
    WEB: RoleTimeouts("5s", "30s", "60s"),
    JOB: RoleTimeouts("5s", "10min", "60s"),
    RETENTION: RoleTimeouts("5s", "10min", "60s"),
}
