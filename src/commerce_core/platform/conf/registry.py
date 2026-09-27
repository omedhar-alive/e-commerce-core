"""The settings registry: every setting, declared once (F1, F1a).

Each entry has its type, default, allowed range, change class, and whether it
is a secret (A11, A12) or snapshotted onto orders (F1b). A setting with no
default is required and names the manual step that supplies it (F1e).

Nothing reads configuration except through this registry: not
``os.environ``, not ``django.conf.settings`` (checked statically, W8a).
The buyer-facing config reference is generated from ``SETTINGS``
(``tools/checks/config_reference.py``).
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import timedelta
from enum import StrEnum
from typing import Any

from commerce_core.platform.conf import types
from commerce_core.platform.money import ISO_4217


class ChangeClass(StrEnum):
    DEPLOY = "deploy"
    RUNTIME = "runtime"
    LOCKED = "locked"


class Role(StrEnum):
    """The database role a process connects as (D6; decision 23)."""

    WEB = "web"
    JOB = "job"
    MIGRATION = "migration"


class DeploymentEnv(StrEnum):
    PRODUCTION = "production"
    STAGING = "staging"
    DEMO = "demo"
    LOCAL = "local"
    TEST = "test"


# Languages core ships translations for, with their text direction (L3).
# A deployment installs a subset.
SUPPORTED_LANGUAGES: dict[str, str] = {"en": "ltr", "ar": "rtl"}


class _Required:
    def __repr__(self):
        return "REQUIRED"


REQUIRED = _Required()


@dataclass(frozen=True)
class Setting:
    name: str
    parse: Callable[[str], Any]
    type_label: str
    description: str
    default: Any = REQUIRED
    change_class: ChangeClass = ChangeClass.DEPLOY
    secret: bool = False
    snapshot: bool = False
    # F1e: for a required setting, the step that supplies it.
    manual_step: str | None = None
    minimum: Any = None
    maximum: Any = None
    choices: tuple[str, ...] | None = None
    # Read only by processes connecting as one of these roles (decision 23).
    roles: frozenset[Role] | None = None
    # Validates the parsed value beyond range and choices; raises ValueError.
    check: Callable[[Any], None] | None = field(default=None, compare=False)

    @property
    def required(self) -> bool:
        return self.default is REQUIRED


def _currency(value: str) -> None:
    if value not in ISO_4217:
        raise ValueError(f"{value!r} is not an ISO-4217 code in core's table")


def _languages(value: tuple[str, ...]) -> None:
    if not value:
        raise ValueError("at least one language must be installed")
    unknown = [code for code in value if code not in SUPPORTED_LANGUAGES]
    if unknown:
        raise ValueError(f"core ships no translations for {unknown}")


def _language(value: str) -> None:
    if value not in SUPPORTED_LANGUAGES:
        raise ValueError(f"core ships no translations for {value!r}")


def _min_length(length: int) -> Callable[[str], None]:
    def check(value: str) -> None:
        if value and len(value) < length:
            raise ValueError(f"must be at least {length} characters")

    return check


def _emails(value: tuple[str, ...]) -> None:
    for address in value:
        if "@" not in address:
            raise ValueError(f"{address!r} is not an email address")


_DB_URL = "postgresql://user:password@host:port/dbname"

SETTINGS: tuple[Setting, ...] = (
    # --- Deployment identity -------------------------------------------------
    Setting(
        "DEPLOYMENT_ENV",
        types.parse_str,
        "choice",
        "Which kind of deployment this is. Production enables the production-only boot checks (X10, X14).",
        choices=tuple(DeploymentEnv),
        manual_step="Set per deployment in the hosting environment.",
    ),
    Setting(
        "SECRET_KEY",
        types.parse_str,
        "string",
        "Django's signing key.",
        secret=True,
        manual_step="Generate 50+ random characters and store as a secret.",
        check=_min_length(50),
    ),
    Setting(
        "DEBUG",
        types.parse_bool,
        "boolean",
        "Django debug mode. Refused in production (X10).",
        default=False,
    ),
    Setting(
        "ALLOWED_HOSTS",
        types.parse_list,
        "list",
        "Host names this deployment serves, comma-separated.",
        roles=frozenset({Role.WEB}),
        manual_step="Set to the API and admin host names.",
    ),
    Setting(
        "TRUSTED_PROXY_HOPS",
        types.parse_int,
        "integer",
        "Number of reverse proxies in front of the app whose X-Forwarded-For entries are trusted (A9b).",
        default=0,
        minimum=0,
        maximum=5,
    ),
    # --- Databases: one URL per role; each process reads only its own --------
    Setting(
        "WEB_DATABASE_URL",
        types.parse_database_url,
        "url",
        f"Connection URL for the web role ({_DB_URL}).",
        secret=True,
        roles=frozenset({Role.WEB}),
        manual_step="Printed once by bootstrap_db for commerce_web.",
    ),
    Setting(
        "JOB_DATABASE_URL",
        types.parse_database_url,
        "url",
        f"Connection URL for the job role ({_DB_URL}).",
        secret=True,
        roles=frozenset({Role.JOB}),
        manual_step="Printed once by bootstrap_db for commerce_job.",
    ),
    Setting(
        "MIGRATION_DATABASE_URL",
        types.parse_database_url,
        "url",
        f"Connection URL for the migration role, read only by the release step ({_DB_URL}).",
        secret=True,
        roles=frozenset({Role.MIGRATION}),
        manual_step="Printed once by bootstrap_db for commerce_migration.",
    ),
    Setting(
        "MIGRATION_LOCK_RETRIES",
        types.parse_int,
        "integer",
        "Times the release step retries a migration that hit its 3 s lock timeout, with exponential backoff (D2a).",
        default=5,
        minimum=0,
        maximum=20,
    ),
    # --- Store ---------------------------------------------------------------
    Setting(
        "STORE_CURRENCY",
        types.parse_str,
        "currency",
        "The store's one currency, an ISO-4217 code (M3a). Locked once any order or discount exists (F1d).",
        change_class=ChangeClass.LOCKED,
        manual_step="Choose the store currency before launch.",
        check=_currency,
    ),
    Setting(
        "STORE_TIMEZONE",
        types.parse_timezone,
        "timezone",
        "IANA timezone for business-day boundaries (L1).",
        manual_step="Set to the store's IANA timezone, e.g. Africa/Cairo.",
    ),
    Setting(
        "INSTALLED_LANGUAGES",
        types.parse_list,
        "list",
        f"Languages the deployment offers, comma-separated. Supported: {', '.join(SUPPORTED_LANGUAGES)} (L3).",
        default=("en",),
        check=_languages,
    ),
    Setting(
        "STORE_DEFAULT_LANGUAGE",
        types.parse_str,
        "language",
        "Fallback language (L3a step 4). Must be installed.",
        default="en",
        check=_language,
    ),
    # --- Staff access --------------------------------------------------------
    Setting(
        "ADMIN_SESSION_IDLE_TIMEOUT",
        types.parse_duration,
        "duration",
        "Admin session ends after this long without activity (A6b).",
        default=timedelta(minutes=30),
        minimum=timedelta(minutes=5),
        maximum=timedelta(hours=8),
    ),
    # --- Monitoring (N3) -----------------------------------------------------
    Setting(
        "MONITORING_TOKEN",
        types.parse_str,
        "string",
        "Bearer token that opens /health/detail and nothing else. Empty: staff session only.",
        default="",
        secret=True,
        check=_min_length(32),
    ),
    Setting(
        "MONITORING_TOKEN_PREVIOUS",
        types.parse_str,
        "string",
        "The token being rotated out; accepted until the rotation window closes.",
        default="",
        secret=True,
    ),
    Setting(
        "MONITORING_TOKEN_ROTATED_AT",
        types.parse_datetime,
        "timestamp",
        "When MONITORING_TOKEN replaced MONITORING_TOKEN_PREVIOUS (ISO 8601 with offset).",
        default=None,
    ),
    Setting(
        "MONITORING_TOKEN_ROTATION_WINDOW",
        types.parse_duration,
        "duration",
        "How long the previous monitoring token stays valid after rotation.",
        default=timedelta(hours=24),
        minimum=timedelta(minutes=5),
        maximum=timedelta(days=7),
    ),
    # --- Alerts and email (N5, W2a) ------------------------------------------
    Setting(
        "ALERT_RECIPIENTS",
        types.parse_list,
        "list",
        "Staff email addresses that receive alert notifications (N5), comma-separated.",
        manual_step="Set to the staff addresses that must hear about alerts.",
        check=_emails,
    ),
    Setting(
        "EMAIL_FROM",
        types.parse_str,
        "string",
        "From address for outgoing email.",
        manual_step="Set to a sending address the SMTP server accepts.",
    ),
    Setting(
        "SMTP_HOST",
        types.parse_str,
        "string",
        "SMTP server host.",
        manual_step="Set to the email provider's SMTP host.",
    ),
    Setting(
        "SMTP_PORT",
        types.parse_int,
        "integer",
        "SMTP server port.",
        default=587,
        minimum=1,
        maximum=65535,
    ),
    Setting("SMTP_USERNAME", types.parse_str, "string", "SMTP username.", default=""),
    Setting("SMTP_PASSWORD", types.parse_str, "string", "SMTP password.", default="", secret=True),
    Setting(
        "SMTP_SECURITY",
        types.parse_str,
        "choice",
        "SMTP transport security.",
        default="starttls",
        choices=("starttls", "tls", "none"),
    ),
    Setting(
        "EMAIL_CHANNEL_ADAPTER",
        types.parse_str,
        "import path",
        "Adapter class for the email notification channel port (W2a). Core ships SMTP.",
        default="commerce_core.platform.notifications.smtp.SmtpEmailChannel",
    ),
    Setting(
        "SMTP_TIMEOUT",
        types.parse_duration,
        "duration",
        "Connect and send timeout for SMTP (T4).",
        default=timedelta(seconds=10),
        minimum=timedelta(seconds=1),
        maximum=timedelta(seconds=60),
    ),
    # --- Error tracking and logs (X13a, X14, I8a) ----------------------------
    Setting(
        "ERROR_TRACKING_DSN",
        types.parse_str,
        "string",
        "Sentry-protocol DSN. Required in production (X14).",
        default="",
        secret=True,
    ),
    Setting(
        "ERROR_TRACKING_REGION",
        types.parse_str,
        "string",
        "Region the error tracker stores data in (X13a, I9).",
        default="",
    ),
    Setting(
        "ERROR_TRACKING_RETENTION",
        types.parse_duration,
        "duration",
        "Retention configured at the error tracker; at most LOG_RETENTION (X13a).",
        default=timedelta(days=90),
        minimum=timedelta(days=1),
        maximum=timedelta(days=3650),
    ),
    Setting(
        "LOG_RETENTION",
        types.parse_duration,
        "duration",
        "Retention for application logs and resolved alerts (I8a). Enforced by the retention job from phase 11.",
        default=timedelta(days=90),
        minimum=timedelta(days=1),
        maximum=timedelta(days=3650),
    ),
    # --- Backups (D4a) -------------------------------------------------------
    Setting(
        "BACKUP_RPO",
        types.parse_duration,
        "duration",
        "Declared recovery point objective (D4a).",
        default=timedelta(hours=1),
        minimum=timedelta(minutes=1),
        maximum=timedelta(days=7),
    ),
    Setting(
        "BACKUP_RTO",
        types.parse_duration,
        "duration",
        "Declared recovery time objective (D4a).",
        default=timedelta(hours=4),
        minimum=timedelta(minutes=5),
        maximum=timedelta(days=7),
    ),
    # --- Jobs ----------------------------------------------------------------
    Setting(
        "TASK_RESULT_RETENTION",
        types.parse_duration,
        "duration",
        "How long finished background-task results are kept (decision 26).",
        default=timedelta(days=7),
        minimum=timedelta(days=1),
        maximum=timedelta(days=365),
    ),
    # --- Runtime (F1c): live in RuntimeSetting rows, never in the environment --
    Setting(
        "CHECKOUT_KILL_SWITCH",
        types.parse_bool,
        "boolean",
        "Stops new checkouts while the site stays readable (N1). Changed in the admin with manage_settings.",
        default=False,
        change_class=ChangeClass.RUNTIME,
    ),
)

BY_NAME: dict[str, Setting] = {s.name: s for s in SETTINGS}
if len(BY_NAME) != len(SETTINGS):
    raise ImportError("a setting is declared twice")
