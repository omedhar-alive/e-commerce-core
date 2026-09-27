# Phase 1 — Foundation

Read `contracts.md` first; it is canonical. This file narrows scope and never
overrides a contract. Phase boundaries come from `phase-plan.md`.

**State, 2026-09-27:** approved. The owner decided all four section 0 items on
2026-09-24 and reviewed the Assumptions list on 2026-09-27, with two changes:
the D3 restore point is required in every environment, and `bootstrap_db`
runs locally and in CI as it does on Neon. Ready for Claude Code.

---

## 0. Stop-and-ask — decide before the build

**0.1 Nothing schedules the scheduled jobs.** *(missing requirement)* —
**Decided: the recommendation (in-core scheduler, `JobSchedule`).**
The stack says "`django.tasks` API, DB-backed worker" and "job registry: one
declaration per job, schedule (UTC)". But neither `django.tasks` nor its
database backend has periodic scheduling: the backend runs tasks someone
enqueued, and nothing enqueues a job at 03:00. N4a says "no job is scheduled
outside" the registry, so platform cron (a schedule held in the hosting
config) breaks that rule.
- **Recommendation:** core ships its own small scheduler.
  - A `run_scheduler` process reads the job registry. Each due job is enqueued
    through `django.tasks`.
  - There is one `JobSchedule` row per registered job, holding `name` (unique),
    `next_run_at`, `last_enqueued_at`, `last_started_at` and
    `last_succeeded_at`.
  - The scheduler claims due rows with `SELECT … FOR UPDATE SKIP LOCKED`, so a
    second scheduler can never enqueue the same run twice.
  - `/health/jobs` and N4 staleness read `last_succeeded_at` against each
    job's maximum staleness.
  - This is a new table the handoff doesn't name.
- **Alternative:** platform cron calling `manage.py run_job <name>`. The
  schedule then lives in each deployment's hosting config rather than the
  registry, which breaks N4a. On Render it is also paid.

**0.2 The demo can't run this phase on Render's free tier.** *(conflict:
handoff §2 "Deploy (demo): Render + Neon, permanent free tiers" against D2g and
N4)* — **Decided: option B, stay free.** The release step runs in the build
command. The worker and scheduler run in-process with the web service.
Render's free instances cover web services only. Background workers and cron
jobs have no free option. The pre-deploy command is available only on paid web
services, private services and workers, which means D2g's named release step
isn't available. A free web service also spins down after 15 minutes without
traffic.
- **Option A — Starter web instance, $7/month (recommended).**
  - `preDeployCommand` runs the release step, exactly as D2g names it.
  - The worker and scheduler run as two extra processes in the same instance
    under a process manager.
  - One bill, and the demo matches how a paying client will deploy.
- **Option B — stay free.**
  - The release step runs in the build command instead. That still runs once
    per deploy and before new code starts, so D2g's "or its equivalent" holds.
    Expand/contract (D2) covers a build that migrates and then fails to
    deploy.
  - The worker and scheduler run in-process as in A.
  - The N6 monitors' polling keeps the instance awake, and one instance fits
    750 hours a month.
  - Cost: a Render restart without notice makes `/health/jobs` flap, and the
    demo diverges from the client setup guide.
- Neon stays on its free tier either way. D4 doesn't apply to the demo (no
  paying customers).

**0.3 Package name and app layout.** *(package structure — expensive to
reverse)* — **Decided: `commerce_core`, as proposed.**
- **Proposal:**
  - Distribution name `commerce-core`, import package `commerce_core`.
  - Django apps: `commerce_core.platform` (registries, errors, jobs, alerts,
    rate limits, HTTP client, money, health, API shapes) and
    `commerce_core.accounts` (user, staff auth, permissions).
  - Each later phase adds one app per domain: `catalog`, `cart`, `orders`,
    `payments`, `fraud`, `refunds`, `fulfilment`, `invoicing`, `privacy`.
  - A separate template repository, `commerce-deployment-template`, is the
    blank deployment skeleton that W8's clean-install test boots.
- If you want a product name instead of `commerce`, now is the only cheap time
  to choose it.

**0.4 Rules with no test as written.** *(the DoD requires "at least one
passing test or CI gate" for every rule in "Contracts that apply")* —
**Decided 2026-09-24:** three rules get new gates, and three are waived by
name.

*New gates:*
- **D1** (a human reads every migration):
  - For every PR that changes a migration, CI posts the `sqlmigrate` output of
    each changed migration as a PR comment.
  - CI fails the PR unless the PR template's "migrations and SQL read" box is
    ticked.
- **D2h** (rollback is code-only): `manage.py release` migrates forwards only.
  With `DEPLOYMENT_ENV = production`, it refuses any target that would
  unapply a migration. A test proves the refusal.
- **X2** (no `None` to signal failure): a static check fails on any function in
  a domain-service module whose return annotation is `Optional[…]` or
  `… | None`, unless it is on an allowlist with a one-line reason. Lookups
  that may legitimately find nothing go on the allowlist.

*Waived:* the DoD's "at least one test or CI gate" item doesn't apply to these
three. Every phase still lists them under "Contracts that apply".
- **T3** (small `atomic()` blocks): proven by review. The backstops are the
  T4a timeouts and the T1 guard.
- **X3** (an `except` recovers or re-raises): proven by review. X1's static
  check covers the worst forms.
- **W5a** (fixes on the latest minor only): a commercial term for the license
  and support terms (W9), with no code path.

---

## 1. Goal

A blank deployment installs core by tag, migrates through the release step as
the migration role, boots with validated settings, and serves `/health`,
`/health/jobs`, `/health/detail` and a TOTP-protected admin, with both external
monitors green.

## 2. In scope

**Package and release**
- The `commerce_core` package, installable by tag from the private repository
  (W1a), with the admin inside it (W1b). The deployment template repository.
- CI, with every W8 gate:
  - the test suite
  - `makemigrations --check`
  - the blocking-migration check
  - the W8a static checks
  - the clean-install test
  - `pip-audit`
  - a hash-pinned lockfile

  The upgrade-path gate is off for this first release.
- `manage.py release`, the release step:
  - runs `migrate` as the migration role
  - retries a `lock_timeout` with backoff up to `MIGRATION_LOCK_RETRIES`
  - refuses a flagged destructive migration without `--restore-point`, in
    every environment (owner decision 2026-09-27; see Assumptions)

**Database**
- `bootstrap_db`: a one-time command, run by the database owner, that creates
  the four roles, sets their T4a timeouts at role level, and sets default
  privileges. It runs the same way against local Postgres, CI's Postgres
  service and Neon.
- Grant helpers that later phases' migrations call to protect a table (D7,
  D7a).

**Accounts and staff access**
- The custom `User` model in `accounts`' first migration:
  - normalized, case-insensitively unique email
  - `token_version`
  - E.164 phone with one normalization function
  - first and last name, country, `preferred_language`, `is_staff`
  - no `accepts_marketing`
- Argon2id hashing. A `bump_token_version()` service, called on deactivation
  and password change.
- Staff admin through `django-otp`: TOTP is required for every staff login, and
  an idle-timeout middleware applies. A `create_staff` command creates a staff
  user and prints their TOTP provisioning URI once.
- The full A6a permission set and the three default groups.

**Settings**
- The settings registry: type, default, range, change class, secret flag,
  snapshot flag. Validation runs at boot from the WSGI entry point, the worker
  and the scheduler, not only on `manage.py check`.
- `RuntimeSetting`, seeded with the kill-switch row. Provider rows arrive in
  phase 6.
- `SettingChange`, append-only.
- The `change_runtime_setting()` service, behind an admin action that needs
  `manage_settings`.

**Errors and requests**
- The error-code registry, the `DomainError` base (a subclass with an
  unregistered code fails at import), the X7 error shape, and the ninja
  exception handlers.
- `request_id` middleware with `upstream_request_id`.
- The X11a savepoint helper.

**Jobs and alerts**
- The job registry, with `run_scheduler` and `JobSchedule` (0.1) and the
  `django-tasks-db` worker.
- `Alert`, with the `raise_alert()` service and the alert-notification job.
- The notification channel port with core's SMTP email adapter, used here for
  staff alert emails. Phase 3 reuses it for customers.

**Rate limits and outbound calls**
- `RateLimitCounter`: atomic upsert, a policy declaration API, and the pruning
  job.
- The A9b client-IP function.
- The shared HTTP client (httpx, with connect and read timeouts), which raises
  inside `atomic()`.

**API shapes**
- `MoneyAmountField` (bigint, `CHECK >= 0`), the ISO-4217 exponent table, and
  the `Money` output schema.
- Cursor pagination (Q2a) and the filter/sort allowlist mechanism (Q2b).
- The 1 MB body cap, applied before parsing.
- A route guard that refuses any route without an explicit response schema.

**Health**
- `/health`, `/health/jobs` and `/health/detail`, with the two-token
  monitoring secret. The core version is read from package metadata (W3).

**Logging and error tracking**
- Structured logging with `request_id`, and a filter that strips secrets,
  tokens and PII.
- Sentry via `ERROR_TRACKING_DSN`, with `before_send` scrubbing.

**Locale and time**
- `USE_TZ`, UTC storage, `STORE_TIMEZONE`, and a store-local business-day job
  helper (L1a).
- Installed languages with text direction, `STORE_DEFAULT_LANGUAGE`, and the
  L3a resolver.

**Deploy tooling**
- The smoke script. The `seed_demo` command skeleton, which creates one staff
  user per default group.

**Jobs registered this phase:** rate-limit window pruning, alert notification,
job staleness check.

## 3. Explicitly out of scope

- Every customer endpoint except the three health endpoints. JWT, registration,
  login, CORS (phase 3).
- Customer `Notification`, templates, the Babel formatter (phase 3).
- Any catalog, cart, order or money-bearing domain model. `MoneyAmountField`
  exists but no domain column uses it yet.
- The retention job. Resolved alerts accumulate until phase 11, and the
  retention role holds no `DELETE` grants yet.
- D4's restore test, backups (D4b), the erasure log (D4c).
- Provider rows in `RuntimeSetting` (phase 6). The kill switch row exists but
  nothing reads it until phase 5.
- Error codes whose raisers don't exist yet. Each phase adds its own (X8 makes
  additions non-breaking).
- Anything not listed in section 2. If the build seems to need it, stop and
  ask.

## 4. Contracts that apply

**Owned — introduced here:**
- W1, W1a, W1b, W2, W2a (notification channel), W3, W4, W4a, W5, W5a, W6, W8, W8a
- F1, F1a, F1c, F1e, F2
- D1, D2, D2a–D2h, D3, D4a (declared only), D5, D6, D7, D7b
- T1, T3, T4, T4a
- X1–X11a, X13, X13a, X14, X15
- Q2, Q2a, Q2b, Q3, Q3a, Q3b, Q3c (body cap)
- A1, A1a, A1b, A2 (admin sessions), A4b (column and bump only), A5 (admin), A6a, A6b, A9, A9b, A11, A12
- N3, N4, N4a, N5, N6
- M1, M1a, M1b, M2, M3a
- L1, L1a, L2, L3, L3a, L4
- S4 (typed actor, for `SettingChange` and `Alert` only)

**Apply but are owned elsewhere:** O7 (the static check for `CASCADE` and
`SET_NULL` is built here and has no targets yet); I8a (`LOG_RETENTION` is
declared here and enforced in phase 11).

## 5. Invariant table

One row per invariant. A cell that can't be filled is a stop-and-ask.

| Invariant | Source of truth | Mutation path | Concurrency boundary | Recovery path | Enforcement layer |
|---|---|---|---|---|---|
| One account per email, case-insensitively (A1a) | `User.email`, stored normalized | `NormalizedEmailField.get_prep_value()` → `normalize_email()`, on every ORM write including `update()` | unique constraint on `Lower(email)` | DB refuses the duplicate; the registration path (phase 3) catches that one named constraint under X11a | DB constraint |
| One phone format (E.164) | `User.phone` | `PhoneField.get_prep_value()` → `normalize_phone()` | none needed (per-row value) | an invalid phone raises `validation_error` on write | single code path in the field type; no DB check, because E.164 validity isn't expressible as a constraint |
| Password hashed with Argon2id (A1b) | `PASSWORD_HASHERS`, Argon2 first | `set_password()` with validators | n/a | a legacy hash is upgraded on the next login (Django default) | settings plus a test that asserts the stored hash prefix |
| Credentials die with deactivation or password change (A4b) | `User.token_version` | `bump_token_version()`: `UPDATE … SET token_version = token_version + 1` | atomic single-statement increment | JWT checks arrive in phase 3; here, a test asserts the bump | single code path plus test. Nothing stronger: a trigger can't know a deactivation is "security-relevant" |
| Staff reach the admin only with TOTP (A6b) | `django-otp` device and the session's verified flag | the OTP admin site login | n/a | an idle session is ended by the middleware | framework (OTP admin site) plus test; a staff user without a confirmed device can't log in |
| Privileged actions check a named permission (A6a) | the core permission constants, attached to a permission-holder model | permission checks in each admin action and service | n/a | refused with `permission_denied` | single code path per action plus a test per permission; groups are seeded once and never re-asserted |
| Every setting is valid at boot (F1a, A11) | the settings registry | environment, at deploy | n/a | the process refuses to start | boot validation in every process entry point, plus a W8a check that no code reads `settings.`/`os.environ` outside the registry |
| Runtime settings are exactly the kill switch and provider toggles, and every change is audited (F1c) | `RuntimeSetting` rows | `change_runtime_setting()`, from an admin action that needs `manage_settings` | `select_for_update` on the setting row; the audit row is written in the same transaction | a failed change rolls back both rows | DB `CHECK` on `RuntimeSetting.name` (a closed constant list), D7 grant on `SettingChange`, `RuntimeSetting` read-only in the admin |
| `SettingChange` is append-only (D7) | `SettingChange` | insert only | n/a | DB refuses `UPDATE` and `DELETE` | DB grant (revoked `UPDATE` and `DELETE` for web and job) |
| Governed writes name their columns (D7b) | model registry of D7 and D7a models | `update_fields` or `QuerySet.update()` | n/a | DB refuses a full-row save | DB grant plus a W8a AST check; admin read-only for governed models (checked at startup) |
| Web and job roles run no DDL, and every role has its timeouts (D6, T4a) | role definitions in `bootstrap_db` | `bootstrap_db` only | n/a | a timeout rolls back and answers 503 `service_unavailable` | DB (`ALTER ROLE … SET`, ownership); a test connects as each role and checks the settings and refused DDL |
| Migrations never wait long for a lock (D2a) | migration role `lock_timeout` 3 s | `manage.py release` | PostgreSQL lock queue | retry with backoff, then fail the deploy | DB timeout plus the release command |
| Destructive migrations need a restore point, in every environment (D3; owner decision 2026-09-27) | the D2b check's destructive flag | `manage.py release --restore-point` | n/a | the release refuses and the deploy stops | the release command plus a CI test |
| Blocking index or constraint forms are rejected on existing tables (D2b) | migrations included in the previous release tag | CI | n/a | CI fails | CI check (W8) |
| No model reads a setting; core's migration history never forks (D2f) | model definitions | CI | n/a | CI fails | `makemigrations --check` plus a W8a check |
| Every error code is registered with its status (X5a) | the error-code registry | `DomainError.__init_subclass__` validates its code | n/a | an unregistered code fails at import | import-time check (fails boot) plus a test that every handler output is registered |
| One error shape, with `request_id` (X7, X10a) | the exception handlers and the request-ID middleware | single handler per error class | n/a | an unhandled error becomes `internal_error` and reaches Sentry | single code path plus tests. Nothing stronger exists for response shape |
| A named unique violation is the only caught integrity error (X11a) | `on_unique_violation(constraint_name)` savepoint helper | callers wrap one insert | the savepoint | any other constraint re-raises | single helper plus a W8a check (no `except IntegrityError` outside the helper) |
| No outbound HTTP inside `atomic()`, and every call has timeouts (T1, T4) | the shared client | `commerce_core.platform.http` only | n/a | raises `HttpInsideTransaction` | runtime guard plus an import-linter rule (no `requests`, `httpx` or `urllib3` imports outside the client) |
| Every job is registered, scheduled once per run, and monitored (N4, N4a) | the job registry and `JobSchedule` rows (0.1) | `run_scheduler` enqueues; the worker records start and success | `FOR UPDATE SKIP LOCKED` on the schedule row | the staleness check job raises `job_stale`; if the scheduler itself is dead, `/health/jobs` goes 503 and the external monitor (N6) sees it | DB unique on `JobSchedule.name`, plus a startup check that every registered job has a row and a test that no periodic task is enqueued outside the scheduler |
| One open alert per (code, subject), written with its cause (N5) | `Alert` | `raise_alert()` inside the caller's transaction | partial unique index on (code, subject_type, subject_id) where status ≠ resolved; `INSERT … ON CONFLICT DO UPDATE` | the notification job re-sends any open alert with `notified_at` null (at-least-once) | DB partial unique index. The closed code set is enforced in code, because a DB `CHECK` would force a constraint migration on a live table for every new code |
| Rate limits hold across workers (A9) | `RateLimitCounter` (policy, principal, window) | `hit(policy, principal)`: one `INSERT … ON CONFLICT DO UPDATE … RETURNING` | the single atomic statement | the pruning job removes expired windows | DB unique constraint plus the atomic statement; concurrency test with two connections |
| Client IP only from trusted hops (A9b) | `REMOTE_ADDR` plus `TRUSTED_PROXY_HOPS` | `client_ip(request)` | n/a | n/a (pure function) | single function plus a W8a check (no reads of `HTTP_X_FORWARDED_FOR` elsewhere) |
| Money is non-negative integer minor units, paired with a currency (M1, M1b, M2) | `MoneyAmountField` | the field type | n/a | DB refuses a negative value | DB `CHECK` from the field's `db_check`; W8a (no `FloatField`, allowlisted `DecimalField`, every model with a money field has a currency field) |
| Exponents come from one ISO-4217 table (M1a, Q3b) | `platform.money.ISO_4217` | code constant | n/a | an unknown currency fails boot (`STORE_CURRENCY`) | single table, plus a test that the `Money` schema always carries the exponent |
| Lists are keyset-paginated on a public tiebreaker (Q2, Q2a, Q2b) | the pagination class | cursor encode/decode | n/a | a tampered cursor decodes to an allowed sort and returns only scoped rows | single class plus a test that the cursor never contains `pk`; the allowlist rejects unknown params with 400 |
| Every route has an explicit schema, and bodies are capped (Q3a, Q3c) | the route guard and body-cap middleware | at router registration and request start | n/a | startup fails (schema) or 413 before parsing | startup check plus middleware plus test |
| Health reveals only what N3 allows (N3, W3) | the three views | n/a | n/a | n/a | tests on body content; monitoring token compared in constant time, previous token valid only inside its window |
| No secrets or PII in logs or error reports (A12, X13a, X15) | the logging filter and Sentry `before_send` | every log record and event | n/a | n/a | single filter plus tests that feed tokens, emails and phones and assert them absent. Nothing stronger exists |
| Timestamps are UTC, and business days are store-local (L1, L1a, L2) | `USE_TZ=True`, `TIME_ZONE="UTC"`, `STORE_TIMEZONE` | the business-day helper keys a job on the store-local date | a unique (job, local_date) run marker | a re-run for the same date is a no-op | DB unique on the run marker plus a DST test |
| Language resolves in L3a order (L3, L3a) | installed languages setting | `resolve_language(request, user, order=None)` | n/a | falls back to `STORE_DEFAULT_LANGUAGE` | single function plus test |

## 6. Tests that prove it is done

**Every phase** (contracts, Definition of done): all items. The M11 item has no
order to touch in this phase, and the upgrade-path item is not applicable to
the first release.

**Rule tests** tagged with an owned rule:
- **M1a, Q3b:** zero- and three-decimal currencies round-trip through the `Money` schema; every amount carries its exponent.
- **M1b:** a money column rejects a negative value (on a test-only model).
- **A1a:** two emails differing only in case cannot create two accounts.
- **A1b:** Argon2id hash stored; a password failing the validators is refused.
- **A6a:** changing a runtime setting is refused without `manage_settings`.
- **A6b:** staff cannot reach the admin without a second factor; an idle session expires.
- **A9, A9a:** a limit holds at its boundary under concurrent requests on two connections.
- **A9b:** a spoofed `X-Forwarded-For` does not change the recorded IP.
- **A11:** a missing required secret fails boot.
- **A12, X15, X13a:** logs and error reports contain no secrets, tokens, email, phone, name or address.
- **D2a:** a migration that can't get its lock fails at 3 s and retries.
- **D2b, D3:** the CI check rejects a blocking migration on an existing table and flags a destructive one; the release step refuses it without a restore point, with `DEPLOYMENT_ENV` set to production and to a non-production value.
- **D2f:** `makemigrations --check` passes; no model reads a setting.
- **D6:** web and job roles cannot run DDL; each role reports its T4a timeouts.
- **D7:** web and job cannot update or delete `SettingChange`.
- **D7b:** a bare `save()` on a governed test model is refused by the DB and by the static check; no admin change form can save one.
- **D5:** the uniqueness rows here (email, alert, rate-limit window, job schedule) each have a concurrency test.
- **X5a, X7, X10a:** every returned code is registered with its status; every error body has `request_id`; an inbound `X-Request-ID` is logged as `upstream_request_id` or dropped.
- **X7, L3a:** an error message renders in the request language and its code doesn't change.
- **X11a:** a named unique violation inside the savepoint is retried; any other constraint re-raises.
- **X14:** production refuses to boot without `ERROR_TRACKING_DSN`.
- **F1a:** a missing, mistyped or out-of-range setting fails boot.
- **F1c:** only runtime settings change at runtime; each change writes an audit row.
- **N3:** `/health` and `/health/jobs` reveal only their status code; `/health/detail` refuses unauthenticated requests; the monitoring token opens nothing else; the previous token works only inside its window.
- **N4, N4a, N6:** a stopped job alerts and `/health/jobs` returns 503 while `/health` stays 200.
- **N5:** an alert is written in its cause's transaction; a retry never opens a second open alert.
- **Q2a, Q2b, Q3, Q3a, Q3c** (on a test-only list endpoint):
  - paging while rows are inserted never repeats or skips a row
  - page size defaults to 20 and clamps at 100
  - no cursor decodes to a primary key
  - an unknown filter or sort returns 400
  - query count is constant at two sizes
  - a body over 1 MB is refused
- **T1:** the shared client raises inside `atomic()`.
- **T4a:** a transaction blocked on a lock fails at `lock_timeout` with a retryable 503.
- **L1, L1a:** day boundaries and a business-day job are correct across a DST transition.
- **W1b, W8, W3:** the clean-install test boots the template with the admin login page responding; `/health/detail` reports the core version.

**Rules proven by a CI gate rather than a rule test:**
- **W8a static checks:**
  - X1: no bare `except`
  - X6: domain imports no API layer
  - T4, P17: no HTTP or provider imports outside their layers
  - M1: money field type
  - O7: no `CASCADE` or `SET_NULL` to history-referenced models (no targets yet)
  - D7b, F1a
  - the S3, S6 and C9 assignment checks (wired now, with no target fields yet)
- **Clean-install test:**
  - W1, W1a: CI installs by tag from the private repo with a deploy key
  - W1b
  - W2: the template contains no models, migrations or domain code
- **W2a:** the notification channel port's contract suite, run against the
  SMTP adapter with a local test SMTP server.
- **W4:** CI fails a tag with no changelog entry. **X8:** CI fails when a
  registry code is removed or its status changed against the previous tag.
- **W5, W6:** the release step refuses to migrate a deployment whose recorded
  core version (W3) is more than one minor behind.
- **D2d:** an import-linter rule forbids migrations from importing domain
  code. **D2g:** a test asserts that no process entry point runs `migrate`.
- **D4a, M3a, F1e:** registry tests.
  - `BACKUP_RPO` and `BACKUP_RTO` are declared with their defaults.
  - `STORE_CURRENCY` is validated against the ISO table.
  - Every setting has a default, or is marked as needing a manual step.
- **A2, A5:** an admin POST without a CSRF token is refused.
- **X9, X10:** the handler maps each registry class to its status; production
  boot refuses `DEBUG=True`.
- **L4:** a static check forbids message literals in `DomainError` raises,
  because messages come from the registry's translations.
- **A1:** a test asserts `AUTH_USER_MODEL` is set and that `accounts.0001` is
  the root of the migration graph.
- **F1, F2:** CI regenerates the config reference from the registry and fails
  if the committed copy is stale. F2 is covered by the W2 template check.
- **S4:** a `SettingChange` row records a typed actor.
- **X5:** covered by X5a's import-time check.
- **X13:** a test asserts that error logs carry `request_id`.
- **X4, X11:** a W8a check forbids `except` clauses whose body is inside an
  `atomic()` block, except the X11a helper.
- **D2c:** a W8a check allows `RunPython` only in migrations on an allowlist of
  seed migrations.
- **D2, W4a:** gated by the upgrade-path test and a port-signature diff
  against the previous tag, both from the second release. Not applicable
  here.
- **D2e:** no snapshot column exists yet. Not applicable here.
- **D1, D2h, X2:** the new gates in 0.4.
- **T3, X3, W5a:** waived, see 0.4.

## 7. Deployment step

1. Tag `v0.1.0`. CI passes every W8 gate.
2. The database owner runs `bootstrap_db` once on Neon. **Verify** that Neon
   allows `CREATE ROLE`, `ALTER ROLE … SET` and column-level grants for the
   roles created. If any is refused, stop and ask: D6 and T4a depend on it.
3. The deploy runs `manage.py release` as the migration role (per 0.2), then
   starts web, worker and scheduler as their own roles.
4. `create_staff` makes the owner's staff account, and the owner enrolls TOTP.
5. The smoke script passes:
   - `/health` 200
   - `/health/jobs` 200
   - `/health/detail` (monitoring token) reports `0.1.0`
   - the admin login page responds and refuses a login without a second factor
6. Two external monitors are configured, one on `/health` and one on
   `/health/jobs`, alerting separately. Both are green.

## Assumptions

Reviewed and approved by the owner on 2026-09-27.

- The DB backend for `django.tasks` is `django-tasks-db` (0.13.0, supports Django 5.2), which has moved out of the `django-tasks` backport into its own package. The stack decision is unchanged.
- The shared HTTP client wraps `httpx`, used synchronously.
- Permissions hang on one unmanaged permission-holder model in `accounts`.
- Default groups are created by a seed migration only if they don't already exist, and are deployment-owned after creation. A later core change to groups ships as an explicit migration that never overwrites a deployment's regrouping.
- `country` and `preferred_language` are plain code fields validated against the registry, not DB choices (D2f).
- Money fields share one currency column per row. A static check requires the column wherever a money field exists.
- The release step refuses a flagged destructive migration without `--restore-point` in every environment (owner decision 2026-09-27; stricter than D3, which requires it only on a deployment holding real orders). In production the identifier must come from a backup system whose last D4 restore test passed. Elsewhere it is recorded with the deploy but not verified: a Neon branch or restore timestamp for the demo, a `pg_dump` file for local.
- For D2b, an "existing table" is any table created by a migration included in the previous release tag.
- The error registry is the single source of error codes and starts with only the codes this phase raises: `validation_error`, `unauthenticated`, `permission_denied`, `not_found`, `payload_too_large`, `rate_limited`, `service_unavailable`, `internal_error`. Each later phase adds its own codes; none are predefined, and no error string lives outside the registry.
- The first staff user enrolls TOTP from a provisioning URI printed once by `create_staff`, because the OTP admin can't be reached without a device.
- Resolved alerts aren't pruned until phase 11.
- Tests use pytest with pytest-django against PostgreSQL. `bootstrap_db` runs against local Postgres and CI's Postgres service exactly as on Neon, creating all four roles. The test database is created by the migration role, and tests connect as `web` (or `job`), per the phase plan's test data strategy.
- The external monitors are a free uptime service of the owner's choice. The setup guide names none.
- Python 3.12 (the handoff doesn't lock a version; Django 5.2 supports 3.10–3.13).
- CI runs on GitHub Actions, with a PostgreSQL service container.
