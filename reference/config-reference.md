# Configuration reference

Generated from `commerce_core.platform.conf.registry` by
`python -m tools.checks.config_reference`. Do not edit by hand (F1).

| Setting | Type | Default | Range | Class | Secret | Read by | Description |
|---|---|---|---|---|---|---|---|
| `DEPLOYMENT_ENV` | choice | **required** | `production` \| `staging` \| `demo` \| `local` \| `test` | deploy |  | all | Which kind of deployment this is. Production enables the production-only boot checks (X10, X14). *Manual step:* Set per deployment in the hosting environment. |
| `SECRET_KEY` | string | **required** |  | deploy | yes | all | Django's signing key. *Manual step:* Generate 50+ random characters and store as a secret. |
| `DEBUG` | boolean | `false` |  | deploy |  | all | Django debug mode. Refused in production (X10). |
| `ALLOWED_HOSTS` | list | **required** |  | deploy |  | web | Host names this deployment serves, comma-separated. *Manual step:* Set to the API and admin host names. |
| `TRUSTED_PROXY_HOPS` | integer | `0` | 0 – 5 | deploy |  | all | Number of reverse proxies in front of the app whose X-Forwarded-For entries are trusted (A9b). |
| `WEB_DATABASE_URL` | url | **required** |  | deploy | yes | web | Connection URL for the web role (postgresql://user:password@host:port/dbname). *Manual step:* Printed once by bootstrap_db for commerce_web. |
| `JOB_DATABASE_URL` | url | **required** |  | deploy | yes | job | Connection URL for the job role (postgresql://user:password@host:port/dbname). *Manual step:* Printed once by bootstrap_db for commerce_job. |
| `MIGRATION_DATABASE_URL` | url | **required** |  | deploy | yes | migration | Connection URL for the migration role, read only by the release step (postgresql://user:password@host:port/dbname). *Manual step:* Printed once by bootstrap_db for commerce_migration. |
| `MIGRATION_LOCK_RETRIES` | integer | `5` | 0 – 20 | deploy |  | all | Times the release step retries a migration that hit its 3 s lock timeout, with exponential backoff (D2a). |
| `STORE_CURRENCY` | currency | **required** |  | locked |  | all | The store's one currency, an ISO-4217 code (M3a). Locked once any order or discount exists (F1d). *Manual step:* Choose the store currency before launch. |
| `STORE_TIMEZONE` | timezone | **required** |  | deploy |  | all | IANA timezone for business-day boundaries (L1). *Manual step:* Set to the store's IANA timezone, e.g. Africa/Cairo. |
| `INSTALLED_LANGUAGES` | list | `en` |  | deploy |  | all | Languages the deployment offers, comma-separated. Supported: en, ar (L3). |
| `STORE_DEFAULT_LANGUAGE` | language | `en` |  | deploy |  | all | Fallback language (L3a step 4). Must be installed. |
| `ADMIN_SESSION_IDLE_TIMEOUT` | duration | `30m` | 5m – 8h | deploy |  | all | Admin session ends after this long without activity (A6b). |
| `MONITORING_TOKEN` | string | `(unset)` |  | deploy | yes | all | Bearer token that opens /health/detail and nothing else. Empty: staff session only. |
| `MONITORING_TOKEN_PREVIOUS` | string | `(unset)` |  | deploy | yes | all | The token being rotated out; accepted until the rotation window closes. |
| `MONITORING_TOKEN_ROTATED_AT` | timestamp | `(unset)` |  | deploy |  | all | When MONITORING_TOKEN replaced MONITORING_TOKEN_PREVIOUS (ISO 8601 with offset). |
| `MONITORING_TOKEN_ROTATION_WINDOW` | duration | `1d` | 5m – 7d | deploy |  | all | How long the previous monitoring token stays valid after rotation. |
| `ALERT_RECIPIENTS` | list | **required** |  | deploy |  | all | Staff email addresses that receive alert notifications (N5), comma-separated. *Manual step:* Set to the staff addresses that must hear about alerts. |
| `EMAIL_FROM` | string | **required** |  | deploy |  | all | From address for outgoing email. *Manual step:* Set to a sending address the SMTP server accepts. |
| `SMTP_HOST` | string | **required** |  | deploy |  | all | SMTP server host. *Manual step:* Set to the email provider's SMTP host. |
| `SMTP_PORT` | integer | `587` | 1 – 65535 | deploy |  | all | SMTP server port. |
| `SMTP_USERNAME` | string | `(unset)` |  | deploy |  | all | SMTP username. |
| `SMTP_PASSWORD` | string | `(unset)` |  | deploy | yes | all | SMTP password. |
| `SMTP_SECURITY` | choice | `starttls` | `starttls` \| `tls` \| `none` | deploy |  | all | SMTP transport security. |
| `SMTP_TIMEOUT` | duration | `10s` | 1s – 1m | deploy |  | all | Connect and send timeout for SMTP (T4). |
| `ERROR_TRACKING_DSN` | string | `(unset)` |  | deploy | yes | all | Sentry-protocol DSN. Required in production (X14). |
| `ERROR_TRACKING_REGION` | string | `(unset)` |  | deploy |  | all | Region the error tracker stores data in (X13a, I9). |
| `ERROR_TRACKING_RETENTION` | duration | `90d` | 1d – 3650d | deploy |  | all | Retention configured at the error tracker; at most LOG_RETENTION (X13a). |
| `LOG_RETENTION` | duration | `90d` | 1d – 3650d | deploy |  | all | Retention for application logs and resolved alerts (I8a). Enforced by the retention job from phase 11. |
| `BACKUP_RPO` | duration | `1h` | 1m – 7d | deploy |  | all | Declared recovery point objective (D4a). |
| `BACKUP_RTO` | duration | `4h` | 5m – 7d | deploy |  | all | Declared recovery time objective (D4a). |
| `TASK_RESULT_RETENTION` | duration | `7d` | 1d – 365d | deploy |  | all | How long finished background-task results are kept (decision 26). |
| `CHECKOUT_KILL_SWITCH` | boolean | `false` |  | runtime |  | all | Stops new checkouts while the site stays readable (N1). Changed in the admin with manage_settings. |
