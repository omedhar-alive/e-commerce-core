# handoff.md — context for the phase-planning thread

Everything a new thread needs to write the phase plan. Read alongside
`contracts.md`. Contracts state invariants; this states decisions, the domain
model, and what is still open. **Where this file and `contracts.md` describe
the same thing, `contracts.md` is canonical** — a divergence is a conflict to
raise under section 6, not a choice to make.

**State as of 2026-09-20:** the contracts review is complete and its
amendments are applied, including both correctness passes and the fatal-defect
review of the same date (see the 2026-09-20 revision-history entries).
**Assumptions 1–131 are confirmed by the owner**; assumption 98 is superseded by
113. **Open items 9 and 10 are both decided** — item 10 by the new contract rule
**C12b**: logging in claims the guest cart, and carts are never merged. **The
phase shape is decided as well** — vertical slices in journey order, about ten
phases, MockProvider before COD; see section 6, "Phase shape". Nothing in either
file is waiting on the owner. **Writing the phase plan is the only step left
before phase 1.**

---

## 1. What is being built

A **resellable e-commerce backend**. Built once, sold to many clients. Each
client gets their own deployment, their own database, and their own frontend.
The backend is API-only and headless — no server-rendered storefront.

Revenue model: the backend is the product; the per-client work is the frontend
and setup. The admin panel is shared code, shipped inside core (contracts W1b)
and deployed per client, not client-branded.

**Not multi-tenant.** No shared database, no tenant column. One deployment per
client, fully isolated.

**Core is a versioned package** (contracts W1), distributed from a private git
repository by tag (W1a) and licensed for use, not modification (W9). Client
deployments install and pin it; they never hold an editable copy of core
source. This is a phase-1 constraint, not a later refactor — extracting a
package from a working app after clients exist is a rewrite.

Market: **not jurisdiction-specific.** Tax, invoicing, language, timezone and
data residency are configuration, not assumptions.

---

## 2. Locked stack

| Layer | Choice | Reason in one line |
|---|---|---|
| Framework | Django 5.2 LTS | migrations, admin and auth are first-party; LTS support to 2028 |
| API | django-ninja | Pydantic schemas and type hints, no DRF serializer layer |
| ORM | Django ORM | admin generates from the models |
| Migrations | Django migrations | versioned schema change on live client databases, expand/contract only (contracts D2) |
| DB | PostgreSQL | concurrent writes and enforceable constraints |
| DB roles | migration, web, job, retention | least privilege; append-only tables and frozen order, payment and refund columns enforced by grants, status transitions by trigger (contracts D6, D7, D7a) |
| Driver | psycopg 3 | current |
| Admin | Django admin, shipped inside core (W1b) | full back office from the models, reused per client; one package, one version, one changelog |
| API auth | JWT (`django-ninja-jwt`) | frontends are separate origins, possibly mobile; the API is served on the client's registrable domain (contracts A4d, A5a) |
| Admin auth | Django sessions + mandatory TOTP (`django-otp`) | same-origin, instant revocation; one staff password is not enough to issue refunds (contracts A6b) |
| Password hashing | Argon2id | current best practice (contracts A1b) |
| Background jobs | `django.tasks` API via the `django-tasks` backport, DB-backed worker | standard API, no Redis, Celery remains a backend swap |
| Job registry | one declaration per job in core: schedule (UTC), max staleness | monitoring and `/health/jobs` read it (contracts N4a, N3, L1a) |
| Rate-limit store | PostgreSQL table, atomic upsert | shared across workers without Redis; also holds windowed placement caps (contracts A9, S1c); Redis remains a config swap |
| Search | PostgreSQL full-text, GIN index, over translation rows | no extra service per deployment (contracts Q3d, L5) |
| Catalog translations | translation tables, one row per (object, language) | per-language content without per-deployment migrations (contracts L5, D2f) |
| Formatting | Babel, one formatter in core | per-language numbers and dates; amounts use the ISO exponent (contracts L6) |
| Payments | port + adapters, `MockProvider` first | provider-agnostic; a new gateway is one file |
| Tax | pluggable calculator behind a port, core only | per-line categories, no rate in the domain (contracts M10a, W2a) |
| Invoicing | tax-authority port, "no authority" adapter by default | jurisdiction logic in adapters (contracts I5, I5b) |
| Error tracking | Sentry protocol via `ERROR_TRACKING_DSN`; required in production | unhandled errors reach a human (contracts X14) |
| Alerts | `Alert` table + staff email via channel adapter | durable, acknowledgeable, visible to `/health` (contracts N5) |
| Static checks | ruff, import-linter, small AST checks in core CI | rules a test cannot prove: status and stock writes, settings reads, import boundaries, money field types, bare `except`, historical FKs (contracts W8a) |
| Core distribution | private git repo, install by tag, deploy key per client | no extra service in v1 (contracts W1a) |
| Deploy (demo) | Render + Neon | permanent free tiers; demo only — a free tier does not meet contracts D4a for paying clients |
| Deploy (client) | per-client decision | data residency is a compliance choice (contracts I9); must meet the declared RPO/RTO with a verified PITR window (D4a) |

**Rejected, with reasons, so they are not relitigated:**
- *FastAPI* — was the original pick. Django won on first-party admin, auth and migrations for a CRUD- and admin-heavy product.
- *DRF* — more mature than ninja, but serializers/viewsets are extra learning on top of Django itself.
- *Django 6.1* — current, but 5.2 is the LTS and clients run this for years.
- *Celery + Redis now* — two extra paid services per client deployment for one job. Swap in later if volume justifies it.
- *Django `DatabaseCache` for rate limits* — its `incr` is a read then a separate write, so concurrent requests race past the limit.
- *Render Postgres* — free databases are deleted after 30 days and there is no connection pooling at any tier.
- *AWS* — new accounts get credits that expire in 6 months, then the free-plan account closes.
- *Reverse migrations as the rollback plan* — production rolls back code only; expand/contract keeps the previous release compatible (contracts D2h).
- *`django-modeltranslation`* — adds a column per installed language from settings, so each deployment would generate different migrations (contracts D2f, L5).
- *Kill switch tripped automatically by card-testing detection* — a false positive takes the store offline; detection alerts and escalates to 3-DS instead (contracts V3).
- *Backporting fixes to older minors* — cost grows with every client and release; fixes ship on the latest minor only (contracts W5a).
- *Immutability of committed orders and adjustments enforced by code alone* — the database enforces it by grant and trigger (contracts D7, D7a).
- *Trusting an inbound `X-Request-ID`* — kept only as `upstream_request_id`, never as the request's own id (contracts X10a).
- *A separate admin installable* — every client runs the admin, so it buys a second release line and a second W4a public surface for nobody (contracts W1b).
- *Re-asserting tax inside the checkout transaction* — a network-backed tax adapter cannot be called under a lock (contracts T1); the window is stated and accepted instead (M6a).

---

## 3. Domain model

Entities and the fields that carry decisions. Not exhaustive — obvious fields
(timestamps, slugs) are assumed.

### Catalog
- **Product** — slug, `active`, category, tax category. Name and description live in translations; a product cannot be activated without its default-language translation (contracts L5)
- **Variant** — belongs to Product. **Price and stock live here, not on Product.** Products without options get one default variant. `track_inventory` (false = never counted, contracts C1b), `stock` (integer, never negative, C1a), tax category, random public id (Q3a). No backorders in v1
- **Category** — single table, nullable self-referencing `parent`, **capped at two levels** by validation. Products attach only to a child category
- **Translations** — one table per translatable entity, one row per (object, language), unique on the pair: product name and description, variant and option labels, category name, shipping method name. Missing rows fall back to `STORE_DEFAULT_LANGUAGE` (contracts L5)
- **StockMovement** — append-only ledger, enforced by grants (contracts D7). `variant`, `delta`, `reason` (closed enum), typed `actor`, **cause by copy — a cause type and the cause's public identifier, never a foreign key** (contracts C8a: `PROTECT` on a ledger FK plus no `UPDATE` grant would make the retention delete of an order impossible forever, I8, O7), timestamp. Retained with its variant, outside the order aggregate. Authoritative; `variant.stock` is a cache of it; mismatches alert, never auto-correct (contracts C8)

### People
- **User** — custom, **email-based**, set before the first migration and never swapped. Fields: email (normalized, unique case-insensitively, login — contracts A1a), `token_version` (A4b), phone (E.164, single normalization function, indexed — V8), first/last name, country (ISO), `preferred_language`. **No `accepts_marketing` boolean** — consent lives in `Consent` rows (I11). `is_staff` gates admin access; staff hold named permissions via default groups and a TOTP device (A6b). Default groups (A6a): **support** — `approve_cancellation`, `change_address`, `manage_returns`, `collect_cash`, `record_delivery`; **warehouse** — `adjust_stock`, `manage_returns`, `create_shipment`, `record_delivery`, `record_receipt`; **finance** — `request_refund`, `approve_refund`, `approve_cancellation`, `collect_cash`, `resolve_review`, `view_payment_events`. `manage_settings` is in no default group and is granted explicitly (A6a, F1c). Never deleted: erasure anonymises the row in place (I10)
- **Address** — shipping and billing, with a random public id (Q3a). Billing is nullable; `REQUIRE_BILLING_ADDRESS` config controls whether checkout asks

### Cart
- **Cart** — `customer` (nullable) or `session_key` (nullable), exactly one filled. A guest cart's signed token is the guest idempotency identity (contracts C12), and the cart carries a random public id (Q3a). **Logging in claims the guest cart** — `session_key` cleared, `customer` set, in one transaction under the cart lock — and **carts are never merged**: an earlier customer cart is left untouched, a converted cart is never claimed, and a claimed cart is repriced before it is next shown (contracts C12b). The customer's current cart is their most recently updated unconverted one. The idempotency scope moves from the cart (C12) to the principal (C11) with the claim, which C12a makes safe
- **CartItem** — variant, quantity, random public id (Q3a)
- **ConfirmationToken** — cart, the approved quote's hash, issued_at, expires_at, used_at, the idempotency key it was bound to. **Cart-scoped, not order-scoped** — M6 issues it because no order exists yet (contracts M6, C10, D5)
- Cart holds a **server-computed quote** — lines, discount, shipping, tax, total — and `priced_at` (contracts M5). Repriced on every input change, including discount validity (G4); it is the baseline for price-change detection, and `reprice_cart()` never runs inside `atomic()` (M6a). A `price_changed` rejection issues a `confirmation_token` that expires after `CONFIRMATION_TOKEN_TTL` (M6)
- **IdempotencyKey** — key, principal or cart scope, operation, request-body hash, status (`in_progress | completed | failed`), stored response, timestamps (contracts C10, C10a). Unique per (principal/cart, operation, key)

### Order
- **Order** — order number (random, 8 characters), **the public identifier of the cart it was placed from, copied and unique — one order per cart, for every principal (contracts C12a, D5)**, own `email` and `phone` columns for guests, `guest_token_version` (contracts A8a), copied shipping and billing addresses, order language, payment method (registry code, contracts S1a — `zero_total` when the total is 0 at checkout, paid by the system at commit, S1c), payment status, fulfilment status (derived), `cancelled_at`, shipping cost, currency, totals, **the approved checkout quote and its hash** (M6a), dispute evidence (contracts R6). Snapshotted settings: `PRICES_INCLUDE_TAX`, COD refusal settings, return rules (contracts F1b); a snapshot column added later is `NULL` on older orders, never backfilled from current config (D2e). **Only lifecycle columns are updatable by grant** — statuses, `cancelled_at`, `guest_token_version`, customer (set once, by trigger), shipping address (O11), contact and fraud-signal columns (erasure); money, copied and snapshotted columns are frozen (D7a). Abandoned unpaid provider-method orders are cancelled by the system after `UNPAID_ORDER_TTL` (contracts S2b)
- **OrderItem** — **copies** product name, variant name, SKU, option values, unit price, tax category, tax rate, tax amount, allocated discount at purchase time. `quantity`, `shipped_quantity`, `cancelled_quantity`, `returned_quantity` (denormalized, checked — contracts S7). Random public id (Q3a) — `out_of_stock` names short lines by it (C4b) and S2a, R8 and shipments all address lines from outside. Only the three quantity columns are updatable by grant (D7a)
- **OrderStatusLog** — from, to, trigger, actor type + id, timestamp. Append-only by grant (contracts D7)
- **Shipment / ShipmentItem** — tracking number, carrier, shipped_at, delivery status (`shipped | delivered | delivery_failed | refused | received_back`), delivered_at; which OrderItems and how many (contracts S8). Refused shipments feed the COD refusal limit per phone (V8)
- **ReturnRequest** — staff-recorded per item and quantity; `requested → approved | declined → received → inspected → closed`, or `expired`; stock and money move on receipt; eligibility judged against the order's copied return rules (contracts R7, R8, F1b). The refund on closing is authorized by `manage_returns` (A6a)
- **CancellationRequest** — customer-initiated, resolved by staff with `approve_cancellation`; whole order or specific items and quantities. Order does not change until staff act. The cancellation's refund needs no `request_refund` (A6a)
- **OrderAdjustment** — every post-commit change to what the order is worth (address change, item cancellation, refused delivery, **collection adjustment — the difference between COD cash collected and the effective total, contracts P13c**); before and after snapshots are the stored values and **every delta is computed from them, never a signed money column** (M1b, O10); immutable once applied — only `status` updatable by grant, and only `awaiting_payment → applied | cancelled | expired` by trigger (contracts D7); issues a debit or credit note, unless applied before the invoice is issued (O10, I1a). Address-change repricing keeps the order's discount terms (O11). A difference payment's expected amount is copied from the adjustment (P10)
- **ReviewCase** — order, cause (`amount_mismatch | allocation_failed | undeterminable | superseded_capture` — any capture on an attempt that had ended, whether superseded, expired or cancelled — `| dispute`), status (`open | resolved`), resolved_by (typed actor), resolution, `auto_resolution_attempted_at` (nullable — what T2a's sweeper reads and C6a writes). The order leaves `payment_review` only when every case is resolved (contracts S1b). `allocation_failed` may be resolved automatically (C6a)

### Money
- **Payment** — one attempt; an order may have several, at most one active per payable (contracts P13a). **An admin-confirmed method (COD) has one too, created in the order-commit transaction and staying `created` until cash is recorded (P13b)** — without it, S1's aggregates read `paid_total == 0` for every COD order and a refund has nothing to attach to. A `zero_total` order has none (S1c). `paid_amount` — what was actually captured, written by the confirmation that moves the attempt to `succeeded`, and the base of M13's ceilings, M14 and R1a. Own status (`created | requires_action | pending | succeeded | failed | expired | cancelled`). **The payable it pays for — the order's own total, or one `OrderAdjustment` awaiting payment; at most one active attempt per payable, as two partial unique indexes (P13a, D5)**. Expected amount and currency copied from that payable (P10, O11), frozen by grant with the order, the payable and the idempotency key (D7a). `refunded_amount`, `disputed_amount`, `dispute_fee_amount` + `dispute_fee_currency` as separate columns
- **PaymentEvent** — raw body verbatim, provider, provider_event_id (unique with provider), `processed_at` nullable, outcome + reason (contracts P5b). Only `processed_at`, outcome and reason updatable by grant (D7). Adapters declare ignored event types (P7)
- **FraudAssessment** — one per payment attempt (COD's hangs on the `Payment` row P13b creates at placement), or one per `zero_total` order, which has no payment row (S1c): rules fired, signals (identities, card fingerprint, AVS/CVV results, 3-DS outcome), decision. Append-only by grant (contracts V7, D7)
- **Refund** — one row per **payment** it draws on, rows created together sharing a `refund_group` (the event: permission, second approval, document and customer message are per group; the provider call and the R1 lifecycle are per row; a single-payment refund is a group of one). An order-level amount (cancellation, return, C6a, negative adjustment) is split across the order's successful payments, most recent capture first. One document per event, issued by the adjustment where one exists and by the group where none does (contracts R1c, O10). Amount (**net of deductions — what the customer receives**, contracts R2b), per-line and shipping allocation, deductions, reason, status (`pending_approval | requested | sent | refunded | refund_failed | rejected`), requested_by (staff, or system under C6a), approved_by, provider refund id or offline payout reference, stable idempotency key. Payment, amount, allocation, deductions and key frozen by grant (D7a)
- **Dispute** — payment, provider reference, amount, reason, status (`inquiry | needs_response | under_review | won | lost | accepted | closed`), evidence_due_by, opened_at, resolved_at. A reinstatement after the order left review as `charged_back` re-enters review (R5, S1)
- **Reservation** — variant, qty, order, `expires_at`, status (`active | consumed | released | expired`). Belongs to the order and carries across superseding attempts. Created with the payment attempt, before the provider call; `expires_at` = the attempt's session expiry + `RESERVATION_GRACE` (contracts C2, C2b). COD and `zero_total` orders allocate through `allocate_order()` when committed (C2a, S1c, C4b). Ends consumed, released or expired (C4a). A cancellation reduces the line's **consumed** reservation quantity by the cancelled quantity, in the same transaction as its `cancellation_return` movement, so C4b's verified-allocation equality keeps holding (C4b)
- **Invoice / CreditNote / DebitNote** — separate from Order, immutable once issued. Issued on the adapter's trigger, default when payment first reaches `paid`, **in that same transaction**, with the T2a sweeper as the recovery path (contracts I1a); B2C documents only in v1 (I1b). Number assigned at issue under the sequence lock, gapless, never reused, set once by trigger (I3, D7). Closed transitions `draft → issued → submitted → accepted | rejected`, plus `issued | accepted → cancelled`; `rejected` is terminal; enforced by trigger (I7). Submission follows the outbound payment rules (I5a). Only issuance status, number (once) and authority identifiers updatable by grant (D7)

### Selling
- **ShippingMethod** — per-client config drives the rules; the chosen method and cost are copied onto the order
- **Discount** — code, type (percent | fixed | free_shipping), value (percent: basis points 1–10000; fixed: minor units of `STORE_CURRENCY`; free_shipping: null — contracts G1a), `value_currency` (required for a fixed discount, `NULL` otherwise — M2, and what F1d's boot check reads), min_order_total (against the pre-discount line subtotal, G3a), starts_at, ends_at (UTC, entered in store timezone, G4a), max_uses, usage counter, max_uses_per_customer, `stacking_class` (always `EXCLUSIVE` in v1), active. Every line is discountable in v1; free shipping covers any method in full (G3b)
- **DiscountRedemption** — discount, order, customer (nullable), `scope_key` (normalized email, contracts G2), amount_applied + currency, status (`active | released`). Unique on (discount, order). Taken at order commit (G1); released, never deleted, on whole-order cancellation (G7)

### Messaging
- **Notification** — recipient (copied from the order), channel (email in v1), template code, language, rendered body, trigger (the domain row that caused it), status (`queued | sent | failed`), attempts, sent_at. Erasure replaces the recipient and deletes the stored body unless an open matter still needs it (contracts I10b, I10a). Unique on (trigger, template). Written in the same transaction as the change it reports; sent by a job, at-least-once (contracts T2b). Doubles as the customer-communications log for dispute evidence (R6)
- **Templates** — core ships a default per template code and installed language; a deployment may override subject, body and branding by code, never add or remove codes (contracts F3)

### Operations
- **Alert** — code (closed set in core), severity (`critical | warning`), subject reference **as a typed pair (type + identifier), never a foreign key** — alerts name rows in every table, and a FK would block their retention delete (contracts N5, I8) — status (`open | acknowledged | resolved`) with typed actor per change, timestamps. Resolved alerts pruned under `LOG_RETENTION`. Written in the same transaction as its cause; unique on (code, subject) while open; staff notified by email to `ALERT_RECIPIENTS` (contracts N5)
- **RateLimitCounter** — (policy, principal, window) with an atomic upsert (contracts A9). Also holds the zero-total placement cap (S1c). Pruned by a monitored job
- **PlacementGuard** — one row per (identity type, identity value), unique by constraint, created on first use and never deleted. The concurrency boundary for V8's open-COD gauge, which is a count and not a counter: a COD placement locks the rows for its normalized phone, email and IP **before the order** in the global lock order and counts open COD orders under that lock (contracts V8, S5, D5). Holds a normalized identity, so erasure replaces it with the subject's pseudonym (I10b)
- **Job registry** — in core, not a table: every scheduled job with schedule (UTC) and maximum staleness (contracts N4a)
- **Error-code registry** — in core, not a table: every error code with status, exception class and `details` shape (contracts X5a)

### Configuration
- **Settings registry** — in core, not a table: every setting with type, default, range and change class (`deploy | runtime | locked`), validated at boot (contracts F1a). Model definitions never read it (D2f)
- **RuntimeSetting** — the two runtime settings: checkout kill switch and per-provider enable/disable (contracts F1c)
- **SettingChange** — audit row per runtime change: setting, before, after, typed actor, reason, timestamp (contracts F1c). Append-only by grant (D7)

### Data protection
- **Consent** — subject (user, or guest's normalized email), scope, wording version, given or withdrawn, timestamp, source. Append-only by grant; the latest row per subject and scope is current (contracts I11, D7). **`subject` is the single column the retention role may update, and only to write an erasure pseudonym** — without it a guest's email is immortal (I10b)
- **Erasure inventory** — one list of every table that identifies the subject: user, order contact and fraud columns, notification recipient and body, `Consent.subject`, `DiscountRedemption.scope_key`, invoice snapshots (kept), raw payment events (kept). One opaque pseudonym per erasure, stable across them (contracts I10b)
- **Erasure log** — every erasure (contracts I10): internal identifiers of the erased rows and the timestamp, never the erased data. Kept outside the database it describes, and replayed after any restore (D4c). Erasures blocked by an open matter are recorded as deferred and completed by a job (I10a)

### Two order status chains (contracts S1)

The complete transition tables, the balance rule for leaving
`payment_review`, and the cancellation matrix live in **contracts S1 and S2**.
That is the only copy; this is the shape:

```
payment:      unpaid → pending → paid → partially_refunded → refunded
              unpaid → paid                          (admin-confirmed methods: COD)
              unpaid → paid                          (zero_total, by the system at commit)
              unpaid → uncollected                   (COD, all goods received back,
                                                      by admin action)
              pending → failed → pending             (new attempt, same order)
              pending → unpaid                       (checkout abandoned)
              pending | paid | partially_refunded | refunded → payment_review
              payment_review → paid | partially_refunded | refunded
                             | charged_back | failed (set by balances, first
                               match wins, once every review case is resolved)
              charged_back → payment_review          (disputed funds reinstated)

fulfilment:   derived from item quantities
              unfulfilled → partially_fulfilled → fulfilled
              partially_fulfilled | fulfilled → partially_returned → returned

display:      computed display_status for frontends (contracts S9)
```

`cancelled_at` is a timestamp, not a state in either chain. `uncollected` is
terminal; `charged_back` is not.

Cash on delivery ships before payment: fulfilment advances while payment stays
`unpaid` until an admin marks cash collected. Only methods registered as
ship-before-payment may fulfil before `paid` (contracts S1a).

### The checkout path (contracts M6a)

Two transactions, because a tax adapter may be a network call (T1):

```
1.  reprice_cart()            outside atomic()   — catalog, shipping, tax
2.  compare to the quote      outside atomic()   — M6; mismatch → price_changed
3.  hash the approved quote
4.  BEGIN
      lock placement_guard(s), for COD → cart → discount → order → payment
           → reservation → variant (S5)
      count the open-COD gauge under the guard lock, for COD (V8)
      refuse if the cart has already converted, and mark it converted (C12a)
      re-assert line prices, discount validity and value, shipping cost
      take the redemption (G1)
      allocate stock, for COD and zero_total (C2a, S1c, C4b)
      create the order, carrying the cart's public id under its unique
           constraint (C12a)
      for zero_total, pay it and issue the invoice (I1a)
    COMMIT
```

The tax portion of the window between 2 and 4 is accepted and stated.

---

## 4. Decided scope

**In v1:** variants, guest checkout, guest cart claimed on login (contracts
C12b), cash on delivery, zero-total orders
(100% discounts with free shipping, paid by the system at commit), partial
fulfilment, coupon codes (one per order; use returned on whole-order
cancellation), shipping via per-client config rules, tax via
pluggable calculator, admin cancel + customer cancellation request (whole order or per item),
automatic cancellation of abandoned unpaid provider-method orders,
admin shipping-address change with price-difference adjustment, reserve at
payment start (allocate at placement for COD and zero-total orders), automatic resolution of paid
orders whose stock is gone (allocate if available, else refund), guaranteed
transactional customer notifications (email in v1), catalog search (PostgreSQL
full-text), catalog translations, card-fraud controls (attempt limits,
card-testing detection with 3-DS escalation, per-attempt fraud assessment),
COD abuse controls (open-order cap, maximum total, refusal-history block),
zero-total order caps, durable staff alerts, B2C invoicing with a "no authority" default adapter,
consent records, staff-started personal-data export.

**Out of v1, deliberately:** discount stacking (`stacking_class` column exists,
always `EXCLUSIVE`), product- or category-scoped discounts (every line is
discountable), per-method free-shipping restrictions or caps,
multi-currency per order, nested categories beyond two
levels, wishlists, reviews, loyalty, subscriptions, marketplaces/multi-vendor,
B2B pricing tiers, returns portal for customers (returns are staff-recorded in v1),
cart merge on login (the guest cart is claimed instead; lines are never combined
and no cart is deleted, contracts C12b), backorders (contracts C1a), COD cash remittance reconciliation (courier
collected vs remitted; admin-recorded cash is the truth, contracts T7),
return rules per market or country (one policy per deployment, contracts R7),
schema rollback in production (code rollback only, contracts D2h),
B2B invoices and buyer tax registration (contracts I1b), self-service
personal-data export (I12), phone OTP for COD (V8), automatic kill switch on
fraud detection (V3), fixes on older minor versions (W5a), a separate admin
installable (W1b).

**Config surface** (per client, no code changes; declared in the core settings
registry, contracts F1a — runtime-changeable: kill switch and provider
enable/disable only, F1c; store currency locked once any order or discount
exists, F1d): store currency, shipping rules, tax categories and rates, tax rounding (declared by the tax adapter), tax-inclusive pricing, COD availability and limits,
refund policy, required billing address, store timezone, installed languages and
direction, store default language, invoice legal language (from the tax adapter), data residency and retention, payment methods and providers enabled, checkout
session TTL (30 min), reservation grace (10 min), cart quote TTL (30 min), confirmation token TTL (15 min), order adjustment payment TTL (48 hours),
unpaid order TTL (24 hours), COD partial acceptance (off),
COD refusal shipping fee (on), return rules and legal return window (one per deployment), return ship-back window (14 days),
refund second approval (off) and threshold, dispute deadline warning (3 days), 3-DS threshold, rate-limit store backend,
automatic resolution of unallocatable paid orders (on), allocation review alert threshold (24 hours),
idempotency key retention (24 hours; at least the confirmation token TTL), idempotency in-progress TTL (5 minutes — contracts C10a),
database timeouts (lock 5 s; statement 30 s web, 10 min jobs; idle-in-transaction 60 s), settlement match window (7 days),
refund reconciliation threshold (1 hour), intent sweep delay (5 min), notification retry limit (8), email provider,
maximum quantity per cart line (99),
CORS origins, trusted proxy hops, JWT issuer and audience, signing-key rotation window (24 hours), webhook secret rotation window (24 hours), guest token lifetime (60 days),
admin session idle timeout (30 min), rate-limit policies (defaults in contracts A9a), message template overrides (contracts F3),
migration lock retries (5), backup RPO (1 hour), backup RTO (4 hours), backup retention (capped by the data-retention settings),
deployment environment, error-tracking DSN (required in production), error-tracking retention and region, log retention (90 days),
failed-attempt limits (defaults in contracts V1a), payment-initiation limits (V1b), card-testing detection thresholds (set by the phase that builds V3),
card-testing escalation period (24 hours), open COD orders per phone/email/IP (3 each — the IP default is a parked item, section 5), COD maximum order total (required when COD is enabled),
COD refusal limit and window (2 in 180 days), zero-total orders per email/phone/IP per 24 hours (3), alert recipients,
`/health/detail` monitoring token and its rotation window,
retention per data class (tax records 10 years, consent records 10 years, payment events 2 years, fraud signals 1 year, resolved alerts and logs 90 days — contracts I8a),
invoice series, seller legal identity and tax registration, tax-authority adapter.

---

## 5. Still open — decide during phase planning

1. ~~Phase ordering for fraud and reconciliation.~~ **Decided 2026-09-20:**
   section 14 lands in the phase immediately after payments. The first phase
   that can take a real card is the phase that ships V1, V1b and
   `FraudAssessment`; V2 and V3 follow once there is event data to detect on.
   This also satisfies the trap about `FraudAssessment` existing in the phase
   that creates payment attempts.
2. **Client deployment hosting.** Data residency is a compliance decision per
   client (contracts I9), and the tier must meet the declared RPO/RTO with
   point-in-time recovery (D4, D4a). The demo runs Render + Neon; a paying
   client may not be able to. **Gate:** before the first paying client, the
   chosen provider's PITR window is verified against its current plan and
   recorded against `BACKUP_RPO` (D4a).
3. **Invoice adapter for the first real jurisdiction.** The model is
   jurisdiction-neutral; core ships only the "no authority" adapter (I5b).
4. ~~Whether the admin ships as part of core or as a separate installable.~~
   **Decided 2026-09-20:** inside core (contracts W1b). W8's clean-install
   test checks the admin login page responds.
5. **Test data strategy** — factories, fixtures, and how the payment adapter is
   tested against a sandbox. This decides what "Tests that prove it is done"
   means in every phase file, so settle it against the drafted phase
   boundaries rather than before them.
6. **Where the erasure log lives** (contracts D4c) — outside the database it
   describes; the storage choice is per deployment and follows residency (I9).
7. **License text** (contracts W9) — use, not modification. A legal
   deliverable before the first sale, not a phase.
8. **Retention values per jurisdiction** (contracts I8a) — the defaults are
   engineering defaults. Before the first paying client, the values for its
   jurisdiction are confirmed by legal or accounting advice, alongside item 3.
9. ~~V8's open-COD cap has no concurrency boundary.~~ **Decided 2026-09-20
   (fatal-defect review):** the guard row, as recommended. A `PlacementGuard`
   row per normalized identity (phone, email, IP), unique by constraint (D5),
   is locked before the order in the global lock order (contracts S5, V8), and
   the gauge is counted under it. S1c's windowed cap stays in the A9 store. The
   guard row holds a normalized identity, so erasure replaces it with the
   subject's pseudonym (I10b). Assumption 131.
10. ~~Cart merge on login is unspecified.~~ **Decided 2026-09-20:** merge is out
    of v1, as recommended, and the behaviour that replaces it is now a contract
    rule — **C12b**. Logging in **claims** the guest cart: `session_key`
    cleared, `customer` set, in one transaction under the cart lock (S5).
    Nothing is merged — an earlier customer cart is left untouched, and the
    customer's current cart is their most recently updated unconverted one. A
    converted cart is never claimed (C12a), and a claimed cart is repriced
    before it is next shown (M5), because the customer's address, language and
    per-customer discount limits (G2) can each change the quote. The
    idempotency scope moves from the cart (C12) to the authenticated principal
    (C11) with the claim; C12a is what makes that safe, since the cart still
    converts to at most one order whichever scope a request arrives under. No
    new uniqueness constraint, so D5 is unchanged. Assumption 132.

### Contracts review — status

- **Done:** sections 1–18, the Definition of Done and the Enforcement
  principle. See the revision history at the end of `contracts.md`.
- **Done:** the assumptions pass — all 95 confirmed by the owner on
  2026-09-18; the changes it made are marked below.
- **Done:** assumptions 96–125 confirmed by the owner on 2026-09-20. Every
  assumption in this file now stands as a decision, not a proposal.
- **Done:** the pre-phase-plan review, 2026-09-20 — four decisions and
  fourteen fixes applied, two items raised as open items 9 and 10 above.
- **Done:** the correctness pass, 2026-09-20 — a re-read of the finished file
  for contradictions and unbuildable rules. Sixteen defects fixed, including
  one load-bearing gap (COD had no `Payment` row, so every rule about money out
  was blind to it) and three rules that could not be implemented as written
  (M5's lock, the cursor's tiebreaker, V1a's per-order limit). Eleven judgment
  calls are listed as assumptions 100–110 for confirmation.
- **Done:** the second correctness pass, 2026-09-20 — six defects fixed and two
  smaller inconsistencies with them. Two were money paths that ended nowhere (a
  late capture had no legal entry into `payment_review`; an order whose refunds
  plus disputes exceed what it paid had no legal exit from it), three were rules
  two other rules made impossible (the ledger's nullable cause under `PROTECT`
  with no `UPDATE` grant, erasure against `Consent`'s append-only grant, column
  grants against Django's `save()`), and one was a missing rule where
  order-level refunds meet per-payment balances (R1c). Twenty-two defects in all, fourteen of them found
  only by re-reading the *amended* file; the readings ran until one found
  nothing, at 8, 4, 4, 3, 1, 1, 0. Fifteen judgment calls are listed as assumptions
  111–125.
- **Done:** the fatal-defect review, 2026-09-20 — a re-read looking only for
  defects that cost money or take the service down, anything fixable after the
  build being out of scope. Ten found and fixed over four readings, at 3, 5, 2,
  0; four of the second reading's five were created by the first reading's own
  fixes. The three from the first reading were: no rule made a cart convert to
  at most one order, so C10a's `failed`-key retry (and two concurrent keys)
  placed a second order, a second redemption and a second COD shipment; the
  one-active-attempt constraint was scoped to the order while O11's difference
  payment is a second attempt on it, so the two payment pages cancelled each
  other and neither could be paid; and a COD collection that did not match the
  effective total exactly had no exit at all, leaving the order `unpaid` for
  ever with real cash off the books and no invoice. Six judgment calls are
  listed as assumptions 126–131, and open item 9 is closed.
- **Done:** assumptions 126–131 confirmed by the owner on 2026-09-20, with no
  change to any rule text.
- **Done:** the phase-plan decisions, 2026-09-20 — open item 10 closed by the
  new rule C12b (logging in claims the guest cart; carts are never merged), and
  the phase shape settled (section 6, "Phase shape"). Two judgment calls are
  listed as assumptions 132–133. **Every assumption and every scoping item in
  this file now stands as a decision. Nothing is waiting on the owner.**
- **Next:** write the phase plan, in the shape section 6 sets out.

**Method used for the review** (and for any later contract change):
1. Read the section against everything already decided.
2. Present findings in two groups: *fixes* (gaps with one clear answer) and
   *decisions* (business choices, each with a recommendation). Short, one
   finding per item.
3. The owner approves, changes or discusses. Nothing is applied before that.
4. Before applying, check whether the change breaks any other rule; if it
   does, go back to the owner first.
5. Apply: new rules take letter suffixes (`P13a`) so existing ids never move;
   add Definition-of-Done tests; add a revision-history entry; update this
   handoff (model, scope, config surface).
6. Anything decided without the owner's explicit say goes on an assumptions
   list for confirmation.

### Assumptions — confirmed by the owner, 2026-09-18

All confirmed. Where the confirmation changed the rule, the item says so.
Items 37 and 45 were amended on 2026-09-20 and show their current form.

1. Only admins change a shipping address; customers ask through support (O11)
2. No shipment while an address-change adjustment awaits payment (O11)
3. COD cash must equal the effective total exactly (S1)
4. `display_status` codes as listed in S9 — public API, review before phase 1
5. Warehouse staff record `received_back`, not the courier (S8)
6. `ORDER_ADJUSTMENT_TTL` default 48 hours (O11)
7. Webhook secret rotation window default 24 hours (P2a)
8. `CART_SNAPSHOT_TTL` default 30 minutes (M5)
9. Fixed discounts allocated by line value (M8)
10. Document-level tax allocated by line tax base (M8)
11. Shipping and tax `null` until an address exists (M5)
12. **Changed:** order numbers are exactly 8 characters, a code constant; uniqueness and regeneration were already in O6/X11a (O6)
13. Attempt reuse requires same amount and method (P13a)
14. Unknown-payment events answered 200, recovered by replay (P5c)
15. Courier-reported refusal entered by an admin in v1 (S8)
16. **Amended 2026-09-20 (correctness pass):** creating or applying an adjustment never writes payment status itself — but a negative delta's refund moves the order `paid → partially_refunded` through R1 and S1, like any other confirmed refund (O11, S1)
17. `DISPUTE_DEADLINE_WARNING` default 3 days before `evidence_due_by` (R4)
18. `RETURN_SHIP_BACK_WINDOW` default 14 days after approval (R8)
19. Refund second approval needs a *different* staff user with the approval permission (R1b)
20. `ALLOCATION_REVIEW_ALERT_AFTER` default 24 hours (C6b)
21. **Changed:** `IDEMPOTENCY_KEY_RETENTION` default 24 hours; boot fails if it is shorter than the new `CONFIRMATION_TOKEN_TTL` (default 15 minutes). Provider keys are unaffected — they live on Payment and Refund rows permanently (C10, M6, P14)
22. A consumption short of stock after a manual decrease counts as `allocation_failed`, so C6a may resolve it automatically (C9a)
23. C6a refunds the whole order when no line can be allocated in full; a line only partly available counts as unavailable (C6a)
24. A failed system refund leaves the case open for staff (C6a)
25. A dispute opened during review opens its own case rather than only being logged (S1b)
26. C6a runs in a job enqueued on commit, not inside the webhook transaction (C6a)
27. Guaranteed means at-least-once: a crash between sending and marking `sent` may repeat a message (T2b)
28. **Amended 2026-09-20 (correctness pass):** guaranteed messages, matching contracts T2b exactly — order confirmation, payment failed, O11 payment link, order or items cancelled, shipment sent, refund completed, C6a outcome, return decision, **email verification, password reset (A1c) and guest order link (A8a)**. The last three have no order, so they carry their own recipient and resolve language by L3a (T2b)
29. Email is the only channel in v1; others (SMS, WhatsApp) are adapters later (T2b)
30. Message body rendered and stored at creation, not at send (T2b)
31. `NOTIFICATION_MAX_ATTEMPTS` default 8, exponential backoff capped at 24 hours — to be validated operationally (T2b)
32. `INTENT_SWEEP_AFTER` default 5 minutes (T2a)
33. `REFUND_RECONCILE_AFTER` default 1 hour, re-polled every cycle after that (T6)
34. A refund `not_found` while `requested` is re-sent under its key; while `sent` it alerts (P15)
35. Web and job workers use separate database roles to get separate timeouts (T4a)
36. `ReviewCase` records whether C6a has attempted it, so the sweeper can find unattempted cases (T2a) — the column is `auto_resolution_attempted_at` (S1b)
37. **Amended 2026-09-20:** entities without an order number or slug — variants, carts, **cart lines, order items**, addresses — get a random public id (UUID v4) for the API. X5a's `out_of_stock` names the short lines by it, and S2a, R8 and shipment contents all address lines from outside (Q3a, C4b)
38. **Amended 2026-09-20 (correctness pass):** the pagination cursor is opaque but not signed, so it may not contain an internal primary key — the keyset tiebreaker is the row's public identifier (public id, order number or slug), indexed as (sort key, public identifier). A6 re-scopes every query, so tampering yields only rows the caller may already see — both now tested (Q2a, Q2b, Q3a, O6, A6)
39. Full-text search uses the `simple` text-search configuration per installed language — no stemming, since PostgreSQL has no Arabic stemmer (Q3d)
40. The 1 MB body cap and 100-line cart limit are fixed, not configuration (Q3c)
41. Email normalization is trim + lowercase of the whole address; no provider-specific rules such as dropping Gmail dots or `+tags` (A1a)
42. Token lifetimes: verification 24 hours, password reset 1 hour, refresh 14 days, in-memory guest token 15 minutes (A1c, A4, A8b)
43. `ADMIN_SESSION_IDLE_TIMEOUT` default 30 minutes (A6b)
44. Signing-key rotation window default 24 hours, matching P2a (A4c)
45. **Amended 2026-09-20:** default groups — support: `approve_cancellation`, `change_address`, `manage_returns`, **`collect_cash`**; warehouse: `adjust_stock`, `manage_returns`; finance: `request_refund`, `approve_refund`, `approve_cancellation`, `collect_cash`, `resolve_review`, `view_payment_events`. `request_refund` is finance-only; `approve_cancellation` is shared; refunds computed by a cancellation or return are authorized by that action's permission. `collect_cash` is in support as well as finance because recording COD cash is a daily, high-volume action in a COD-heavy market and finance is not the team doing it. **Amended again 2026-09-20 (correctness pass):** fulfilment had no permission at all — `create_shipment`, `record_delivery` and `record_receipt` added, split as S8's "Recorded by" column splits them, and `collect_cash` also covers recording an offline refund payout (A6a, S8, R1)
46. Staff TOTP via `django-otp` (A6b)
47. A fresh guest link is requested with email plus order number (A8a)
48. Abandoned-order cancellation is placed in section 3 as S2b, not in section 10 (S2b)
49. S2b's TTL counts from the later of order creation and the last attempt ending; COD and orders with an active attempt on their own total are excluded (S2b, P13a)
50. S2b sends the guaranteed cancellation message, like any cancellation (S2b, T2b)
51. **Changed:** a 100% percentage discount is allowed, and the resulting zero-total order now has a defined path — `zero_total` method, paid by the system at commit, capped at 3 per email, phone and IP per 24 hours (G1a, S1c)
52. G6 reasons are evaluated in the listed order, first match wins (G6)
53. A released redemption is kept as a row with status `released`, and releasing decrements the global usage counter (G7)
54. Applying a code before checkout checks everything except the per-customer limit, which needs the order email (G4)
55. The buyer-facing config reference is generated from the settings registry, not written by hand (F1)
56. No code reads a setting except through the registry — now a static check (F1a, W8a)
57. The `STORE_CURRENCY` lock is enforced as a boot check against existing orders and fixed discounts (F1d)
58. A template override may change subject, body and branding (F3)
59. A fourth database role, `retention`, deletes retention-governed rows (D6, D7, I8)
60. `MIGRATION_LOCK_RETRIES` default 5, exponential backoff; each attempt is bounded by the 3 s `lock_timeout` already in D2a (D2a)
61. Column-level `UPDATE` exceptions on append-only tables: `PaymentEvent` (`processed_at`, outcome, reason), invoices and notes (issuance status, number once, authority identifiers), `OrderAdjustment` (status); `StockMovement`, `OrderStatusLog`, `SettingChange`, `Consent`, `FraudAssessment` none (D7)
62. **Changed:** `OrderAdjustment` status transitions, invoice and note transitions, and the set-once document number are enforced by database trigger, not code (D7, I7). Extended by the same review: `Order`, `OrderItem`, `Payment` and `Refund` freeze their money and copied columns by grant (D7a)
63. `RunPython` in a migration is allowed only on empty or bounded-by-design tables; every other data rewrite is a job (D2c)
64. "Verified backup" means a restore point recorded with the deploy, from a system whose last restore test passed; the release step now refuses a flagged destructive migration without it (D3)
65. Unique constraints on populated tables are built as a concurrent unique index, then attached (D2b)
66. The erasure log holds internal row identifiers and timestamps only (D4c)
67. `BACKUP_RETENTION` has no fixed default; it is capped by the I9 retention settings (D4b)
68. **Changed:** the provider's PITR window must be verified against `BACKUP_RPO` before the first paying client; the demo is exempt (D4a; open item 2)
69. The error codes and statuses listed in X5a; `checkout_disabled` answers 503 (X5a)
70. 404-for-inaccessible applies to the customer API; the admin keeps Django's own behaviour (X9)
71. **Changed:** `request_id` is always generated server-side; a valid inbound `X-Request-ID` (≤64 chars, `[A-Za-z0-9._-]`) is logged as `upstream_request_id`, an invalid one dropped (X10a)
72. "Production" for X14 is a `DEPLOYMENT_ENV` setting; the demo may run without error tracking (X14)
73. `payment_verification_failed` is used only on webhook responses (X5a, X12)
74. V1b defaults 5 / 10 min per order, 20 / hour per IP — starting values, tuned against real traffic (V1b)
75. V1a counts failures in the A9 rate-limit store rather than a separate table (V1a)
76. **Changed:** V3 thresholds have no defaults yet, and V3 does not ship until the phase that builds it sets them (V3)
77. `CARD_TESTING_ESCALATION_PERIOD` default 24 hours (V3)
78. V2 lacking a provider capability is a boot *warning*, not a failure — V1 and V3 still apply, and failing would exclude providers without velocity rules (V2)
79. An "open" COD order for V8 means not cancelled with payment still `unpaid` (V8)
80. V8 defaults — 3 open COD orders per phone, email and IP; refusal limit 2 within 180 days; `COD_MAX_ORDER_TOTAL` has no default and is required when COD is enabled (V8)
81. Lifting a phone's COD block uses the existing `resolve_review` permission rather than a new one (V8, A6a)
82. A COD order gets one `FraudAssessment` at placement (V7, V8)
83. **Changed:** `/health/detail` accepts a staff session or a monitoring token; the token is a secret, grants `/health/detail` only, and rotates with a two-token window (N3)
84. Alert codes are a closed set in core; staff alert emails render in `STORE_DEFAULT_LANGUAGE` (N5)
85. Default invoice issuance trigger: payment status first reaching `paid` — for COD, cash collected; for `zero_total`, commit (I1a)
86. O10 amended: an adjustment applied before the invoice is issued issues no note, and the invoice reflects the effective totals (O10, I1a)
87. Credit and debit notes number in their own series (I3)
88. **Changed:** retention defaults — tax records 10 years, payment events 2 years, fraud signals 1 year, logs 90 days, notifications follow their order — stay as defaults; each jurisdiction's values are confirmed before its first paying client (I8a; open item 8)
89. Erasure keeps the invoice snapshot's buyer details and anonymises email, phone, IP and device on retained orders (I10)
90. Deferred erasure is completed by a new scheduled job (I10a, N4)
91. `accepts_marketing` is dropped from User rather than kept as a derived column (I11)
92. Translated fields: product name and description, variant and option labels, category name, shipping method name (L5)
93. A product cannot be activated without its `STORE_DEFAULT_LANGUAGE` translation (L5)
94. Deployment-adapter ports: payment, courier, notification channel; tax calculation and tax authority are core only (W2a)
95. One read-only deploy key per client for the core repository (W1a)

### Assumptions — 2026-09-20 pass, confirmed by the owner

96. A declined second approval ends a refund `rejected`, terminal; a refund
    that should still happen is requested afresh rather than revived (R1)
97. `IDEMPOTENCY_IN_PROGRESS_TTL` default 5 minutes, swept by a monitored job;
    the sweeper marks an abandoned `in_progress` row `failed` (C10a, N4)
98. ~~`StockMovement` references its cause nullably, so retention can delete an
    order on the tax-record clock while movements run on the fraud-signal
    clock.~~ **Superseded 2026-09-20 (second correctness pass) by 113:** a
    nullable FK is still a FK, `PROTECT` refuses the delete and no role may
    null it, so the cause is copied, not referenced (C8a, I8, O7)
99. A headless-only deployment, if one is ever sold, unregisters the admin
    URLs rather than installing a different package (W1b)

### Assumptions — 2026-09-20 correctness pass, confirmed by the owner

These are the judgment calls the correctness pass made. Each had an
alternative; the one taken is stated.

100. COD gets a real `Payment` row (P13b) rather than making S1's aggregates
     method-aware. The alternative — cash recorded on the order and refunds
     pointing at the order — would have touched M13, M15, R1, R1a, R2b and D7a
     and left two shapes of money in the codebase.
101. S9's `partially_refunded` row is placed **last**, so a goodwill refund on
     a delivered order still reads `delivered`. Placed beside `refunded`
     instead, it would mask every fulfilment state. This is a public-API
     addition, which X8 says is not breaking.
102. `min_order_total` follows the store's price basis (G3a) — tax-inclusive
     where prices are. The alternative is always-ex-tax, which would mean the
     merchant's "orders over 500" does not match the price the customer sees.
103. Fulfilment permissions split three ways (`create_shipment`,
     `record_delivery`, `record_receipt`) matching S8's "Recorded by" column,
     rather than one `manage_fulfilment`. `collect_cash` covers recording an
     offline refund payout: the same cash desk, no new permission.
104. The keyset tiebreaker is the row's public identifier, with an index on
     (sort key, public identifier), rather than signing the cursor — a signed
     cursor still carries the id and breaks on key rotation.
105. V1a's per-order failed-attempt limit is a count of the order's `failed`
     `Payment` rows, not a row in the rate-limit store. The alternative is to
     give it a window, which changes the control.
106. Job staleness moves out of `/health` to a new public `/health/jobs`,
     polled as a second external check (N3, N6). The alternative — leaving it —
     lets a late cron job de-pool the web tier.
107. `reprice_cart()`'s concurrency boundary is an input-hash compare-and-set
     under the cart lock (M5), not a lock held across the computation, which
     T1 forbids.
108. A cancellation reduces the line's consumed reservation quantity (C4b),
     rather than loosening the verified-allocation equality to `>=`, which
     would hide a real mismatch.
109. `Discount.value_currency` is a stored column rather than an implicit read
     of `STORE_CURRENCY` — F1d's boot check has to compare against something.
110. `ConfirmationToken` is its own cart-scoped row (C10, D5) rather than a
     column on the cart, so D5's uniqueness and single-use both have a home.

### Assumptions — 2026-09-20 second correctness pass, confirmed by the owner

The judgment calls of that pass. Each had an alternative; the one taken is
stated.

111. A capture on an attempt that had already ended enters `payment_review`
     from `unpaid` and `failed` under the existing `superseded_capture` cause,
     broadened to cover any ended attempt — rather than a new cause value,
     which would be an enum addition on live orders later (S1, S1b).
112. The `payment_review` exit test is `>=`, so refunds plus disputes exceeding
     `paid_total` exit `charged_back` (or `refunded` with nothing disputed).
     The alternative is a new status for over-return, which every consumer of
     the status would have to learn (S1, M13).
113. The stock ledger records its cause by copied type and public identifier,
     and is retained with its variant rather than on a clock of its own. The
     alternatives were a retention-role `UPDATE` grant on the ledger (a write
     path into an append-only table) or weakening O7's `PROTECT` (which every
     other history rule depends on). **Supersedes 98** (C8a, I8, O7).
114. An order-level refund splits most-recent-capture-first, one `Refund` per
     contributing payment, one credit note per event. The alternative — one
     refund row against the largest payment — cannot express a cancellation on
     an order carrying an O11 top-up (R1c).
115. C6a's system-refund uniqueness becomes (review case, payment), since the
     amount may now split. Keeping it per case would refuse the second row of a
     legitimate split (C6a, D5, R1c).
116. `Consent.subject` is replaceable by the retention role for erasure, and
     nothing else on the row is. The alternative — storing guest consent
     against a pseudonym from the start — loses the ability to show a regulator
     who consented (I10b, D7, I11).
117. Writes to D7 and D7a tables name their columns and those models are
     admin-read-only, rather than dropping the column grants or listing every
     column in them. The grants are the enforcement layer; the ORM bends
     (D7b, W8a).
118. COD cash on a refused shipment is recorded after `received_back`, with the
     delay to the invoice stated. The alternative is a holding account for
     uncredited cash, which is a second money model for one config option
     (S8, S1, I1a).
119. `out_of_stock` names lines by the identifier the request used — cart line
     at checkout, order item afterwards — rather than always by order item,
     which at checkout names rows the rollback erased (C4b, X7, Q3a).
120. The refund event is a `refund_group` identifier on the rows, not a new
     entity. A single-payment refund is a group of one, so there is one shape
     (R1c).
121. Where an adjustment exists it issues the only document, and its refund
     issues none. The alternative — a note per refund — credits the same money
     twice in the tax records (R1c, O10, R2b, I2).
122. A disputed payment contributes nothing to a split and the event answers
     `dispute_open` rather than `RefundExceedsPaid`, because the two mean
     different things to the staff member reading them (R1c, R2c).
123. Consent records get their own retention class, defaulting to 10 years
     alongside tax records: the consent row is the proof of the processing it
     authorised. The alternative — no clock — leaves a guest's email in the
     table forever (I8a, I11, I10b).
124. `Alert` names its subject by typed pair and resolved alerts are pruned
     under `LOG_RETENTION`, rather than carrying a foreign key that would block
     an order's retention delete (N5, I8, I8a).
125. Erasure deletes the customer's saved `Address` rows outright rather than
     anonymising them: O3 already copied everything an order needs, so nothing
     historical reads them. The order's own copied address is anonymised with
     its contact columns, and only the invoice snapshot keeps a copy (I10b, O3,
     I4).

### Assumptions — 2026-09-20 fatal-defect review, confirmed by the owner

The judgment calls of that review. Each had an alternative; the one taken is
stated.

126. A cart converts to at most one order, for every principal, enforced by a
     unique **copied** cart public identifier on the order (C12a) — not a
     foreign key, which would put `PROTECT` between a ten-year order and a
     prunable cart table, and not a service check, which races. The
     alternative — relying on the idempotency key — cannot work, because C10a
     exists to let a `failed` key be retried.
127. The one-active-attempt constraint is scoped per **payable**, as two
     partial unique indexes, with at most one `OrderAdjustment` in
     `awaiting_payment` per order (P13a). The alternative — forbidding an
     address change while the order's own attempt is live — refuses a normal
     support action and still leaves two adjustments colliding.
128. A cash difference at a COD collection is recorded as a
     `collection_adjustment` on the order (P13c), keeping S1's exact-cash rule
     (assumption 3) true. The alternatives were relaxing exact cash, which
     makes `paid_amount` untrustworthy on the one method with no provider to
     check it, or a holding account for uncredited cash, which is a second
     money model.
129. The collection difference is a term of the effective total, outside every
     line and every tax base, and appears as its own line on a refund and its
     credit note (M11, P13c, R2b). Allocating it across lines by M8 would move
     a tax base over a rounding error.
130. `OrderAdjustment` deltas are **computed from the before and after
     snapshots**, not stored as signed columns (O10), so M1b's
     `CHECK (amount >= 0)` holds on every money column. The alternative is a
     signed money column, which M1b forbids and which is a migration on money
     later.
131. V8's open-COD gauge is serialized by a `PlacementGuard` row per normalized
     identity, locked before the order in S5 — the recommended option from open
     item 9, now closed. The alternative was accepting the cap as approximate,
     which a scripted attacker parallelizes past for free.

### Assumptions — 2026-09-20 phase-plan decisions, confirmed by the owner

132. Logging in **claims** the guest cart (C12b) rather than leaving it a
     session cart while the principal is authenticated. Leaving it would
     contradict C11's "keys are scoped by authenticated principal" and would
     stop the cart following the customer to another device. Claiming is a
     two-column write and every rule that names a cart keeps pointing at the
     same row. Merging lines was the third option and is out of v1: it is four
     rules — collision handling, a stock recheck, re-evaluating the guest's code
     against the account's per-customer limit (G2), and the idempotency scope —
     for a case that is rare. Closes open item 10.
133. The phase plan is built as **vertical slices in journey order**, about ten
     phases, with MockProvider before COD (section 6, "Phase shape"). The
     alternatives were horizontal layers, which cannot satisfy the
     deploy-and-verify step every phase file ends with and leaves the invariant
     table unfillable in early phases; a risk-first core, which the dependency
     graph forbids since orders need carts need a catalog; and one phase per
     contracts section, which are cross-cutting rather than buildable units.

### Parked

1. Whether an order going `on_hold` is added to the guaranteed messages
   (contracts T2b). Not covered by the assumptions pass; decide before the
   phase that builds T2b.
2. **V8's per-IP open-COD cap will refuse legitimate buyers in a mobile
   market.** Raised by the 2026-09-20 fatal-defect review and deliberately not
   treated as fatal: the cap is a setting, so it is tunable without a migration
   and is out of that review's scope. The concern is real all the same —
   Egyptian mobile carriers put thousands of subscribers behind one
   carrier-grade NAT address, so the fourth unrelated customer on that address
   with an open COD order is refused COD (`cod_unavailable`, V6), and COD is the
   method most of them would have used. The phone and email caps are not
   affected; only the IP one is. Options for the phase that builds V8: raise the
   IP default well above the phone and email defaults, disable the IP identity
   by default and keep it as an incident lever, or keep 3 and let the client
   tune it after watching real `cod_unavailable` rates. **Recommendation:** a
   much higher IP default, with the `PlacementGuard` row (assumption 131) and
   the phone and email caps carrying the actual control. Decide before the phase
   that builds V8; the guard row and the lock order do not change either way.

---

## 6. How the work will be done

- Code is written by **Claude Code**, driven by phase files.
- The owner reviews and must be able to debug everything shipped. Nothing
  ships that he cannot reason about — this is a hard constraint on how code is
  structured and how much magic is acceptable.
- **`contracts.md` is read on every task.** A phase file may narrow scope but
  never override a contract.
- Each phase is independently testable and deployable.

### Phase shape

**Decided 2026-09-20 (assumption 133).** The plan is built as **vertical slices
in journey order** — each phase a working path, deployed and verified — not as
horizontal layers, not risk-first against stubs, and not one phase per contracts
section.

*Why this shape and not the others:* every phase file ends deployed and verified
by the smoke script against two green external monitors, and only a working path
can satisfy that. The invariant table cannot be filled for a model whose
mutation path is scheduled for a later phase, so under horizontal layers every
phase-1 row is a stop-and-ask. The stated failure mode of AI-written code is
building more than was asked, and a slice has a natural boundary — the path
works — where "all the models" has none. The owner has to be able to debug what
ships, and one working path is reviewable where forty behaviourless models are
not. Risk-first fails on the dependency graph: orders need carts need a catalog,
so a stub catalog is built twice and the second build is a migration on live
order data. Contracts sections are cross-cutting — section 1 alone touches cart,
order, payment, refund, adjustment and invoice — so they are the "Contracts that
apply" field, never the slicing rule. The one good instinct in risk-first,
front-loading what is expensive to reverse, is already carried by "Known traps"
below, which constrains this shape rather than replacing it.

**Sizing rule.** A phase is the **smallest set that keeps one invariant's source
of truth, mutation path, concurrency boundary and enforcement layer inside it**
(contracts, Enforcement principle). Splitting an invariant across two phases is
what produces the retrofit migrations the trap list is a catalogue of. This
makes checkout a large phase — M6a, S5, C12a, C2a, G1 and the idempotency
lifecycle are one cluster — and the catalog a small one. That asymmetry is
correct; do not flatten it for tidiness. About ten phases; a plan that needs
eighteen is splitting invariants, and one that needs six is bundling them.

**Payment-method order: MockProvider before COD.** The provider path is the
general case — reservations (C2), the two-transaction webhook (P5), P11 and P12,
`payment_review` and `ReviewCase` — and `MockProvider` is in-process and
deterministic, so the whole money machine is exercised with no gateway. COD is
then a coherent phase of its own: the P1 path-3 admin confirmation, P13b's
payment row, `PlacementGuard` and V8, S8's refusal and `received_back` leg,
P13c's collection adjustment, and `uncollected`. The pull the other way is real
— the market is COD-heavy and a COD demo sells better — and it loses anyway,
because COD is the one method with no provider to check the amount, and the
general machine should be proven before the special case that has no external
verifier leans on it. `zero_total` is not a third ordering question: S1c's
commit path ships with checkout, as the traps say.

**Indicative slices**, in order — the plan confirms or adjusts each boundary as
it drafts that phase's invariant table:

1. **Foundation** — core as a package with the admin inside it, CI gates, the
   user model, the four database roles and their timeouts, the settings, error
   and job registries, `Alert`, the rate-limit store, the shared HTTP client,
   the money field type, the public API shapes, `/health` and `/health/jobs`,
   the permission set and default groups, and the release pipeline.
2. **Catalog** — products, variants, categories, translation tables, the stock
   ledger and stock service, search, and the first list endpoints with their
   query-count, page-cap and keyset indexes.
3. **Accounts, access and messaging** — registration and verification, password
   reset, JWT with rotation and `token_version`, CSRF and CORS boot checks,
   staff TOTP, the rate-limit policies, and `Notification` with core's default
   templates, which the account messages need.
4. **Cart, pricing and the quote** — cart and lines, the claim (C12b), the tax
   port and shipping rules, the money arithmetic and allocation, discounts as a
   pricing input, `reprice_cart()` with its hash compare-and-set, the
   idempotency key table and lifecycle, and the confirmation token.
5. **Checkout, orders and provider payments** — the two-transaction checkout,
   the S5 lock order, the cart-uniqueness constraint, the order and its copies,
   `transition_to()` with the full S1 set and `ReviewCase`, the method registry,
   reservations, `MockProvider` with webhooks and reconciliation, the discount
   redemption at commit, the zero-total path, and `display_status`.
6. **Fraud controls** — V1, V1b and `FraudAssessment` land with the phase that
   can take a real card (open item 1); V2 and V3 follow once there is event data
   to detect on, and V3 not without its threshold defaults.
7. **Fulfilment, shipments and cancellations** — shipments and their delivery
   statuses, derived fulfilment, `CancellationRequest`, item cancellation,
   abandoned-order cancellation, and `OrderAdjustment` with the address-change
   path.
8. **Refunds, returns and disputes** — the refund lifecycle, the R1c splitter
   and `refund_group`, second approval, returns, disputes, and the automatic
   resolution in C6a.
9. **COD** — the admin-confirmed path and its payment row, allocation at
   placement, `PlacementGuard` and the V8 controls, the refusal and
   `received_back` leg, the collection adjustment, and `uncollected`.
10. **Invoicing, data protection and retention** — issuance and gapless
    numbering against both triggers (provider `paid` and COD cash collected),
    the tax-authority port with the "no authority" adapter, consent, erasure
    against I10b's inventory, the retention job and I8's deletion order, and the
    final hardening pass. The `Invoice` model and the order's per-line tax
    snapshot columns land in phase 5 with the order, per the traps; only
    issuance and the authority port wait for this phase.

Open item 5 — the test data strategy — is settled against these boundaries while
the plan is drafted, not before, because it decides what "Tests that prove it is
done" means in every phase file.

### What a phase file must contain

- **Goal** — one sentence
- **In scope** — the models, endpoints and jobs this phase touches
- **Explicitly out of scope** — the main failure mode of AI-written code is
  building more than was asked, which breaks independent testability
- **Contracts that apply** — by rule id
- **Invariant table** — one row per invariant the phase introduces or
  touches: source of truth, mutation path, concurrency boundary, recovery
  path, enforcement layer (contracts, Enforcement principle). A row that
  cannot be filled is a stop-and-ask
- **Tests that prove it is done** — the "Every phase" items plus every rule
  test tagged with a rule in "Contracts that apply" (contracts, Definition of
  done)
- **Deployment step** — every phase ends deployed and verified by the smoke
  script and a green external monitor

### Known traps to design phases around

- `AUTH_USER_MODEL` must be set before the first migration. Phase 1. Its
  case-insensitive email constraint and `token_version` go in the same first
  migration (contracts A1a, A4b). No `accepts_marketing` column (I11).
- Core-as-package must be the structure from phase 1 (W1), with the admin
  inside it (W1b), the W8 CI gates — including the W8a static checks and the
  clean-install test that boots the admin — and the W1a distribution in place.
  W8's upgrade-path test and the previous-minor migration gate do not apply to
  the first release.
- `Invoice` and per-line tax categories must be in the model from the start;
  retrofitting either is a migration on live orders.
- Money is integer minor units everywhere from the first line of code —
  discount percentages included, as basis points (contracts G1a). Core's one
  money field type exists before the first money column (W8a).
- Every list endpoint needs its query-count and page-cap test in the same
  phase that creates it, not later.
- The full S1 transition set goes into `transition_to()` in the phase that
  creates it, including dispute, `charged_back` and the reinstatement path
  back into review, and the `zero_total` rows. Adding a status to a live enum
  is a migration on historical orders. The same holds for `ReviewCase`, its
  causes and its `auto_resolution_attempted_at` column (contracts S1, S1b).
- `Refund`'s status enum includes `pending_approval` and `rejected` from its
  first migration, even though R1b is off by default (contracts R1, R1b).
- The payment-method registry includes `zero_total` (confirmation `system`)
  from the phase that creates orders; S1c's commit path goes in with checkout
  (contracts S1a, S1c).
- COD's `Payment` row (P13b) goes in with the phase that builds the COD path,
  in the same transaction as the order. Adding it later means backfilling
  payment rows for live COD orders and recomputing their aggregates — and
  `paid_amount` is the base of every ceiling in M13.
- The keyset tiebreaker is a public identifier, not `id`, so the
  (sort key, public identifier) index goes in with the first list endpoint. The
  cursor shape is public API (contracts Q2a, Q2b, X8).
- `/health` and `/health/jobs` are two separate endpoints from phase 1, and the
  setup guide asks for two external checks (contracts N3, N6). Only `/health`
  may be wired to a platform health check.
- The full permission set exists from phase 1, fulfilment's three included, so
  the default groups are built once (contracts A6a).
- The checkout path's two-transaction shape (M6a) is fixed in the phase that
  builds checkout: reprice outside `atomic()`, hash, then re-assert the
  database-backed inputs under the S5 locks. Retrofitting it means rewriting
  the order-commit transaction.
- The idempotency key's `in_progress | completed | failed` lifecycle (C10a)
  goes in with the first endpoint that takes an `Idempotency-Key`; a key table
  without a failure state locks honest clients out.
- Database timeouts are set at role level, not per session — the pooler drops
  session `SET` (contracts T4a). Phase 1, with the database setup.
- The four database roles, their grants and the append-only `UPDATE`/`DELETE`
  revocations are created in phase 1 and extended by each phase that adds an
  append-only table (contracts D6, D7). The D7a frozen-column grants and the
  D7/I7 transition triggers are created in the same migration as the table
  they protect. Retrofitting grants after code has come to rely on updates is
  a hunt through every write path.
- Retention's deletion order (I8) is written with the phase that builds the
  retention job, but every phase that adds a table referencing an order places
  it in one of I8's three groups — the aggregate, the ledger exception or the
  alert exception — otherwise `PROTECT` refuses the delete years later. The
  first pass through this missed `Reservation` entirely and left `Alert`
  unstated; both were found by re-reading, not by building.
- Migrations run in a single release step as the migration role, with
  `lock_timeout` 3 s and retry, from the first deploy; the release step
  refuses a flagged destructive migration without a restore-point id
  (contracts D2a, D2g, D3).
- Core CI runs `makemigrations --check` and the blocking-migration check from
  phase 1; no model field reads a setting (contracts D2b, D2f).
- `Notification` rows are written in the same transaction as the change they
  report, from the first phase that sends any message (contracts T2b).
- The pagination shape, the money object, the error shape and public
  identifiers are public API: fixed before the first endpoint ships
  (contracts Q2a, Q3a, Q3b, X7). Public ids exist on variants, carts, cart
  lines, order items and addresses from their first migrations.
- The error-code registry, `request_id` (with `upstream_request_id`) and the
  X11a savepoint helper exist before the first endpoint; every later code is
  added to the registry (contracts X5a, X10a, X11a).
- The shared HTTP client, which refuses to run inside `atomic()`, exists
  before the first adapter (contracts T1, T4).
- The `Alert` table and the job registry exist from phase 1. Every rule that
  "alerts" writes an `Alert` row, and every job is registered when it is
  written (contracts N4a, N5).
- The rate-limit store exists before the first rate-limited endpoint and
  before the first placement cap; V1a, V1b and S1c all read it (contracts A9).
- Catalog translation tables go in the catalog's first migration. Moving names
  off `Product` after launch is a migration on every catalog table
  (contracts L5).
- One phone normalization function (E.164) and one email normalization
  function from the first model that stores either (contracts A1a, V8).
- `FraudAssessment` exists in the phase that creates payment attempts, COD
  placement or zero-total placement; the fraud controls cannot be added to
  orders already placed without one (contracts V7).
- `DiscountRedemption` carries `scope_key` and `status` from its first
  migration; per-customer limits cannot be backfilled correctly from orders
  that attached to accounts later (contracts G2, G7).
- The settings registry exists from phase 1, and every setting is added
  through it; the order's snapshotted settings columns (contracts F1b) and its
  checkout quote hash (M6a, R6) go in the Order's first migration — a snapshot
  column added later is `NULL` on every earlier order (D2e).
- V3 does not ship without its threshold defaults, set in the phase that
  builds it (contracts V3).
- **Every write to a D7 or D7a table names its columns** (`update_fields` or
  `QuerySet.update()`), and those models are read-only in the admin, from the
  phase that creates the first one. Django's `save()` writes every field, and a
  column grant refuses that — found after the admin is built, it is a rewrite of
  every write path (contracts D7b, W8a).
- The stock ledger's cause is a copied identifier, not a foreign key, from its
  first migration. A FK there is refused by `PROTECT` at the first retention
  run, years later (contracts C8a, O7, I8).
- `Refund` rows are created per payment by one splitter, and carry their
  `refund_group` from their first migration, from the phase that creates the
  first refund. An order-level amount against a single payment row is the bug
  that keeps an O11 top-up, and a group added later cannot be reconstructed for
  refunds already issued (contracts R1c).
- Erasure is built against I10b's inventory, not against the user row alone, and
  `Consent.subject` is writable only by the retention role from the migration
  that creates the table (contracts I10b, D7).
- The order's unique cart identifier goes in the Order's first migration
  (contracts C12a, D5). It is the only thing that stops C10a's `failed`-key
  retry, and two concurrent keys, from placing a second order; added later it
  cannot be backfilled for orders whose cart is already gone.
- `Payment` carries the payable it pays for, and its two partial unique indexes,
  from its first migration; `OrderAdjustment` carries its `awaiting_payment`
  partial unique constraint from its own (contracts P13a, O11, D5).
- The `OrderAdjustment` type enum includes `collection_adjustment` from its
  first migration, and the model stores before and after snapshots with no
  signed money column (contracts P13c, O10, M1b). Adding an adjustment type to
  a live enum is a migration on historical orders, exactly as S1's statuses are.
- `PlacementGuard` and its position in the global lock order go in with the
  phase that builds V8; without it the open-COD cap has no concurrency boundary
  at all (contracts V8, S5, D5).
- The cart claim (C12b) goes in with the cart phase, not with accounts. It is a
  two-column write, but which principal a cart belongs to decides the
  idempotency scope every checkout retry is looked up under (C11, C12), and
  "the customer's current cart" is a public API answer. Built later, it is a
  change to a resolution rule every cart endpoint already depends on.

### When to stop and ask

Ambiguity is normal and gets resolved by asking, not by picking. **Stop and
ask the owner** — do not proceed on an assumption — when any of these is true:

1. **Two sources conflict.** A contract rule contradicts another contract rule,
   or contradicts this handoff. Quote both and ask which wins. Do not pick the
   stricter one and move on; the conflict itself is information the owner
   needs. (Two rules that merely *overlap* — both apply and both can be
   satisfied — are not a conflict; satisfy both, per the contracts header.)
2. **Something required is missing.** A field, a rule, or a decision the phase
   depends on that exists nowhere in either file.
3. **The answer would be expensive to reverse.** Anything touching the user
   model, the money representation, the package structure, an entity that
   historical orders reference, or a public API shape. These are migrations on
   live data later, not edits.
4. **A contract rule cannot be satisfied as written.** Say so rather than
   implementing a near approximation. The rule may be wrong — every review
   round so far has found rules that were. This includes an invariant-table
   row that cannot be filled.
5. **The phase seems to require work the contracts do not cover at all.** A
   whole missing area is a scoping decision, not a gap to fill quietly.

**For everything else, do not stop — declare.** Ordinary judgment calls
(naming, field ordering, which of two equivalent implementations) proceed, but
every output ends with an **Assumptions** list stating what was decided without
being told. One line each.

*Why both halves are needed:* "ask when unsure" fails silently, because the
failure mode is not refusing to ask — it is not noticing that a gap was filled.
A forced assumptions list surfaces the ones that were never felt as
uncertainty, which is where the expensive mistakes live.

**Never resolve a conflict by choosing.** Never invent a business rule. Never
widen scope to make something work.

---

## 7. After the phases

Three artifacts, in this order:

1. **`CLAUDE.md`** — how to work in this repo. Points at `contracts.md` and
   the current phase file. States the stack, the conventions, what never to do
   (swallow exceptions, write raw stock updates, put HTTP inside a
   transaction, write domain data from a migration, raise an error code that
   is not in the registry, log personal data), and the rule that scope
   outside the phase file is not touched.
   It also carries the **stop-and-ask rule from section 6 above**, restated for
   code rather than planning: stop for conflicts, missing requirements and
   irreversible choices; declare everything else in an Assumptions list at the
   end of the output. Written after the phases because it references them.

2. **`docs/adr/`** — one page per decision: context, choice, cost. The ones
   worth writing are the arguments: Django over FastAPI, ninja over DRF, JWT
   for API and sessions for admin, reserve-at-payment over decrement-on-payment,
   integer minor units, fork-per-client narrowed to core-as-package, admin
   inside core, PostgreSQL rate-limit store over Redis, code-only rollback with
   expand/contract, append-only tables and frozen columns enforced by grants
   and triggers, translation tables over per-language columns, zero-total
   orders paid by the system, the two-transaction checkout and the accepted
   tax window (M6a), and **fraud** — including the current card-network
   thresholds (Visa VAMP, Mastercard ECM) moved out of contracts section 14,
   re-checked at each release. Contracts say *what*; ADRs say *why this and
   not that*, which is what a buyer's developer reads to judge whether the
   codebase was thought about.

3. **Buyer-facing docs** — API reference (ninja generates OpenAPI), an error
   reference (generated from the error-code registry, contracts X5a), a setup
   guide (including the two mandatory external checks — `/health` and
   `/health/jobs`, alerting separately, contracts N3 and N6 — the
   verified PITR window, D4a, the no-custom-card-form rule, P18, and the
   requirement that the API is served on the client's registrable domain so
   the refresh cookie works, A4d/A5a), a runbook (what to do when a job stops,
   a webhook fails, a payment is stuck in review, an alert fires, card testing
   is detected, a migration times out on a lock, a restore is needed — and
   that a 503 spike on a heavily-used coupon is the expected shape of S5's
   discount lock under `lock_timeout` 5 s, not an incident, since the commit
   transaction also carries M6a's re-assert and, for zero-total orders,
   invoice issuance), the config reference (generated from the settings
   registry, contracts F1), and the license and support-window terms
   (W5a, W9). This is what makes the backend sellable rather than merely
   working, and it is the part most solo builds skip.

Then build phase 1.
