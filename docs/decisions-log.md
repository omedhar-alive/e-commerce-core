# decisions-log.md

Every owner decision made after `handoff.md` (state 2026-09-20). It overrides
the handoff where the two differ. `contracts.md` still wins over both.
Newest entries go at the bottom. Each entry gives the date, the decision, and
where it's recorded.

## 2026-09-24 — phase plan (recorded in `phase-plan.md`, section 1)

1. **Invoice issuance moves to phase 5 (checkout).** Issuance, gapless
   numbering, the I5 port, the I5b no-authority adapter and the `Invoice`
   model all land there. Only I5a and I6 (real authority submission) stay in
   the last phase. This resolves a conflict between handoff slice 10 and I1a,
   S1c and the sizing rule.
2. **`FraudAssessment` and V7 move to phase 5.** Phase 6 writes an "allow, no
   rules" assessment on every attempt, and the fraud phase adds V1–V5. This
   resolves a conflict between handoff slice 6 and the trap list.
3. **Refunds come before cancellations.** Refunds and disputes are phase 8.
   Fulfilment, cancellations, adjustments and returns are phase 9.
4. **The idempotency key and confirmation token move to checkout (phase 5).**
   The C12b cart claim stays in phase 4.
5. **Slice 5 splits in two:** phase 5 is checkout and orders, phase 6 is
   provider payments. That makes 11 phases.
6. **Staff TOTP (A6b) moves to phase 1.**
7. **The rate-limit mechanism and A9b move to phase 1.** Each phase declares
   its own endpoints' policies.
8. **The upgrade-path gate is on from phase 2.** Every phase is a `0.N.0`
   release, and the demo database is upgraded in place with `seed_demo` data.
9. **Columns that exist before their writer** get the invariant row: *"No
   writer in this phase. Enforcement: a test asserts the value stays at its
   initial value, and the W8a check finds no write path. Writer lands in
   phase N."*
10. **The `OrderAdjustment` table lands in phase 6** with `Payment`, because
    of the payable FK and its partial indexes. Its writers arrive in phases 9
    and 10.
11. **v1 core ships MockProvider only.** A real gateway is a deployment
    adapter (W2a). Deployment rule: no real provider is enabled on any
    deployment before phase 7 (fraud) has shipped.
12. **Test data strategy (handoff open item 5 closed):** see `phase-plan.md`
    section 4.
13. **The notification channel port and core's SMTP adapter move to phase 1**,
    because N5's staff alert email needs them.

## 2026-09-24 — phase 1 (recorded in `phase-01-foundation.md`, section 0)

14. **Scheduling:** core ships its own scheduler. A `run_scheduler` process
    uses one `JobSchedule` row per registered job (name unique, `next_run_at`,
    `last_enqueued_at`, `last_started_at`, `last_succeeded_at`), claimed with
    `FOR UPDATE SKIP LOCKED`. Platform cron is rejected because it breaks
    N4a. This is a new table.
15. **The demo stays on Render's free tier and Neon's free tier (option B).**
    - Render free covers web services only: no workers, no cron, and no
      pre-deploy command. Free services spin down after 15 minutes idle.
      Checked on 2026-09-24.
    - The release step therefore runs in the build command, and the worker
      and scheduler run in-process with the web service.
    - The N6 monitors keep the instance awake.
    - A paying client's deployment uses a real release step (D2g).
16. **Package:** distribution `commerce-core`, import package
    `commerce_core`.
    - Apps: `platform` and `accounts` in phase 1. Each later phase adds one:
      `catalog`, `cart`, `orders`, `payments`, `fraud`, `refunds`,
      `fulfilment`, `invoicing`, `privacy`.
    - The deployment skeleton lives in a separate
      `commerce-deployment-template` repo.
17. **Rules with no test as written.**
    - New gates:
      - **D1:** CI posts the `sqlmigrate` output of each changed migration as
        a PR comment, and fails the PR unless the "migrations and SQL read"
        box is ticked.
      - **D2h:** `manage.py release` migrates forwards only, and refuses to
        unapply anything in production.
      - **X2:** a static check refuses an `Optional` or `| None` return in
        domain services unless the function is on an allowlist with a reason.
    - Waived by name from the DoD's "at least one test or CI gate" item:
      - **T3** (backstopped by the T4a timeouts and the T1 guard)
      - **X3** (backstopped by X1's static check)
      - **W5a** (a commercial term that belongs in the license)
18. **Dependency note:** `django.tasks`' database backend is now the separate
    package `django-tasks-db` (0.13.0, supports Django 5.2), checked
    2026-09-24. The stack decision is unchanged.

## 2026-09-27 — phase 1 Assumptions review (recorded in `phase-01-foundation.md`, Assumptions)

19. **Phase 1 Assumptions approved, with two changes.** The phase file is
    final and handed to Claude Code.
    - **D3 restore point in every environment.** The release step refuses a
      flagged destructive migration without `--restore-point` in production,
      demo and local alike. Outside production the identifier is recorded but
      not verified, because there is no D4 restore test there. This is
      stricter than D3, so no contract change.
    - **Local and CI roles.** `bootstrap_db` runs against local Postgres and
      CI's Postgres service exactly as on Neon, creating all four roles. Tests
      run as `web`/`job`.
20. **Kept as written.**
    - Default groups are seeded only if missing and are deployment-owned
      after creation. A future core change to groups ships as an explicit
      migration, never by overwriting.
    - The error registry is the single source of truth. It starts with the 8
      phase-1 codes, and each phase adds its own. No future codes are
      predefined.
21. **Python 3.12; CI on GitHub Actions.** Declared in the phase 1
    Assumptions. The handoff doesn't lock either.
