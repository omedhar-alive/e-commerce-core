# phase-plan.md — overview

Read alongside `contracts.md` (canonical) and `handoff.md`. This file sets the
phase boundaries, which rules each phase owns, and the test data strategy
(handoff open item 5). The per-phase files are written from it once the owner
has ruled on section 1.

**State, 2026-09-24:** the owner accepted every recommendation in section 1
on 2026-09-24, including the MockProvider-only v1 and the deployment rule that
follows from it. Sections 2–5 stand as the plan. Phase files:
`phase-01-foundation.md` is drafted, and its section 0 items are decided (see `decisions-log.md` 14–17).
Drafting it moved the notification channel port and core's SMTP adapter into
phase 1, because N5's staff alert email needs them. Phase 3 reuses them.

---

## 1. Decisions needed before the phase files

Items 1–3 are **conflicts inside the handoff**: the indicative slices (handoff
§6) say one thing, and a trap, the checkout path (§3) or a contract rule says
another. Under the handoff's own rule I'm raising them, not picking. Items 4–7
change boundaries, which the handoff allows ("the plan confirms or adjusts each
boundary"). Items 8–10 are questions nothing in either file answers.

### Conflicts

**1. Invoice issuance moves from phase 10 to checkout.**
- Slice 10: "issuance and gapless numbering against both triggers … only
  issuance and the authority port wait for this phase."
- Against it: I1a ("issuance happens in the transaction that moves payment
  status to `paid`"); the checkout path in handoff §3 ("for zero_total, pay it
  and issue the invoice"); the S1c rule test; and the sizing rule, since I3's
  source of truth (the sequence lock) and its mutation path (the `paid`
  transition) would sit in different phases. Refunds (R1c, I2) and adjustments
  (O10) also issue credit and debit notes against an invoice, and both come
  before slice 10.
- **Recommendation:** issuance, gapless numbering, the I5 port and the I5b "no
  authority" adapter go into checkout, together with the `Invoice` model. Only
  submission to a real authority (I5a, I6) stays in the last phase.

**2. `FraudAssessment` moves from slice 6 to checkout.**
- Slice 6: "V1, V1b and `FraudAssessment` land with the phase that can take a
  real card."
- Against it: the trap "`FraudAssessment` exists in the phase that creates
  payment attempts, COD placement or zero-total placement", and the S1c test
  ("exactly one `FraudAssessment`" on a zero-total order). Zero-total orders
  are placed in checkout.
- **Recommendation:** the model and V7 go into checkout (zero-total's
  assessment). The provider-payments phase writes one on every attempt, with
  the decision "allow, no rules". The fraud phase adds the rules (V1–V5) and
  does not change the table's shape.

**3. Refunds come before cancellations. Swap slices 7 and 8.**
- Slice 7 (cancellations, adjustments) comes before slice 8 (refunds). But S2's
  approved cancellation refunds, S2a refunds the stored per-unit amounts, S2b's
  late capture is "refunded from there (R1c)", and O11's negative delta
  refunds. Each of those needs the R1c splitter, and none of them works without
  it.
- Returns (R8) need shipments (`received`), so they can't join refunds first.
- **Recommendation:** refunds and disputes (with C6a) go first. Fulfilment,
  cancellations, adjustments **and returns** follow.

### Boundary changes

**4. The idempotency key and the confirmation token move from the cart phase to
checkout.** C10 names checkout as the only endpoint that takes an
`Idempotency-Key`, and M6's token is issued by a checkout rejection. In the cart
phase both would have no endpoint and no mutation path, so their invariant rows
couldn't be filled. The C12b claim stays in the cart phase, as the trap requires.

**5. Split slice 5 into "checkout and orders" and "provider payments".** After
items 1, 2 and 4, slice 5 would hold M6a, S5, C10–C12a, the full S1 table,
`ReviewCase`, invoicing, the method registry, reservations, MockProvider,
webhooks and reconciliation. That's too much for one review if the owner has to
be able to debug all of it. P10 ("no payment attempt is ever committed before
its order") gives a real seam:
- *Checkout and orders* ends with the zero-total path fully working (placed,
  allocated, paid and invoiced at commit). A provider-method order is placed
  `unpaid` with no reservation, which is correct because C2 reserves at payment
  start.
- *Provider payments* owns everything from the first attempt onwards.
- No invariant straddles the seam: every rule is owned by one side (section 2).
  I3 gets a second caller (provider `paid`) through the same issuance service.
- **Cost:** 11 phases instead of 10. On the demo, provider-method orders placed
  between the two phases can't be paid.

**6. Staff TOTP (A6b) moves from phase 3 to phase 1.** Phase 1 ships the admin
(W1b) and `/health/detail` with staff-session access (N3). Phase 2 has staff
editing the catalog. With TOTP in phase 3, two deployed phases would run a
password-only admin, which breaks A6b on live code.

**7. The rate-limit policy mechanism and A9b move to phase 1. Each phase then
declares the policies for its own endpoints.** Search is in A9a's defaults (60
per minute per IP) and ships in phase 2, so "the rate-limit policies" can't
wait for phase 3.

### Questions

**8. When does the upgrade-path gate start?** The DoD's previous-minor
migration gate and W8's upgrade test are "enabled from the second release". If
every phase is a core minor release (0.1.0, 0.2.0, …), that means from phase 2.
- **Recommendation:** yes, from phase 2. The demo database is upgraded in place
  every phase, with realistic data from the seed command (section 4). The first
  expand/contract rehearsal then happens on the demo, not on a paying client.
- **Alternative:** treat phases as pre-release, reset the demo database each
  phase, and start the gate at 1.0.0. This is cheaper per phase, but the first
  upgrade from a populated database happens in front of a client.

**9. A convention for columns that exist before their writer.** Several traps
put a column or table in a phase that has no code writing to it yet:
- `Payment.disputed_amount` and `refunded_amount` (provider payments; writers
  arrive with refunds)
- the S7 quantity columns (checkout; fulfilment)
- the return-rules snapshot (checkout; returns)
- `OrderAdjustment` (item 10)

As written, each of these is an empty cell and so a stop-and-ask.
- **Recommendation:** a row may say *"No writer in this phase. Enforcement: a
  test asserts the value stays at its initial value, and the W8a check finds no
  write path. Writer lands in phase N."* That phase then rewrites the row.

**10. `OrderAdjustment`'s table lands with provider payments, not with
adjustments.** The trap says `Payment` has "the payable it pays for, and its two
partial unique indexes, from its first migration". One payable is an
`OrderAdjustment`, so its table (with the `collection_adjustment` type, the
`awaiting_payment` partial unique constraint and its D7 trigger) must exist when
`Payment` is created. Its writers arrive in the fulfilment and COD phases.
Confirm, together with item 9.

**Also, not blocking:** no phase builds a real payment gateway adapter. v1 core
ships only MockProvider, and a real gateway is a deployment adapter (W2a). That
turns open item 1 into a deployment rule: **no real provider is enabled on any
deployment before the fraud phase has shipped.** Confirm that this is intended.

---

## 2. Phases

This table assumes section 1 is accepted. "Owns" lists the rules a phase
**introduces**. It's where the invariant row is first filled. Later phases that
touch the same rule list it again under "Contracts that apply" and extend the
row. Rules in section 3 apply to every phase and aren't repeated here.

| # | Phase | Ends with this path working |
|---|---|---|
| 1 | Foundation | a blank deployment boots, deploys through the release step, and passes both monitors |
| 2 | Catalog | staff create a product in two languages and adjust its stock; the API lists and searches it |
| 3 | Accounts, access and messaging | a customer registers, verifies by email, logs in, rotates a token and resets a password |
| 4 | Cart, pricing and the quote | a guest builds a cart, applies a code, gets a taxed and shipped quote, then logs in and keeps the cart |
| 5 | Checkout and orders | a 100%-discount order is placed, allocated, paid and invoiced at commit; a provider-method order is placed `unpaid` |
| 6 | Provider payments | a MockProvider order is paid by webhook, reconciled, and invoiced |
| 7 | Fraud controls | failed attempts and card testing are blocked or escalated on MockProvider |
| 8 | Refunds and disputes | staff refund a paid order, split across payments; a dispute runs to won and lost |
| 9 | Fulfilment, cancellations, adjustments, returns | an order ships in parts, has an item cancelled and its address changed, and a return is received |
| 10 | Cash on delivery | a COD order is placed, shipped, collected (exact, short, over) or refused and received back |
| 11 | Tax authority, data protection, retention | erasure, export, consent, the retention job and restore replay all work; authority submission runs through the port |

### 1 — Foundation
- **Scope:**
  - core as a package with the admin inside it; W1a distribution; CI gates (W8, W8a static checks, `makemigrations --check`, the blocking-migration check, the clean-install test)
  - the release step; the four roles with role-level timeouts; the grants mechanism
  - the user model in the first migration (case-insensitive email, `token_version`, E.164 phone function)
  - staff sessions with TOTP and an idle timeout
  - the settings registry with `RuntimeSetting` and `SettingChange`
  - the error-code registry, `request_id`, the X11a helper and the error shape
  - the job registry and DB-backed worker; `Alert` and the staff alert email, through the notification channel port and core's SMTP adapter
  - the rate-limit store with policy declaration and the A9b IP function
  - the shared HTTP client; the money field type with the ISO-4217 table
  - pagination, money and error API shapes
  - `/health`, `/health/jobs` and `/health/detail` with the monitoring token
  - the full permission set and default groups; the language resolver
- **Owns:**
  - W1, W1a, W1b, W2, W3, W4, W4a, W5, W5a, W6, W8, W8a
  - F1, F1a, F1c, F1e, F2
  - D1, D2–D2h, D3, D4a (declared only), D6, D7 (`SettingChange`), D7b
  - T1, T3, T4, T4a
  - X1–X11a, X13–X15
  - Q2, Q2a, Q2b, Q3a, Q3b, Q3c (body cap)
  - A1, A1a, A1b, A2 (admin), A5 (admin), A6a, A6b, A9, A9b, A11, A12
  - N3, N4, N4a, N5, N6
  - M1, M1a, M1b, M2, M3a
  - L1, L1a, L2, L3, L3a, L4
  - W2a (notification channel)
- **Out:** every customer endpoint except health; JWT.
- **New protected tables:** `SettingChange` (D7).

### 2 — Catalog
- **Scope:**
  - Product, Variant (with public id), Category (two levels), translation tables
  - the stock service, `StockMovement` (cause by copy), the ledger mismatch check
  - catalog admin with stock read-only
  - list, detail and search endpoints with keyset indexes and the search rate-limit policy
- **Owns:** L5, Q1, Q1a, Q3, Q3d, C1, C1a, C1b, C3 (no reservations yet), C7, C8, C8a, C9, C9a (no reserved stock yet), O7 (catalog side), A6, A7, A9a (search).
- **Out:** reservations, prices in carts, shipping-method translations (phase 4).
- **New protected tables:** `StockMovement` (D7; I8 ledger exception).

### 3 — Accounts, access and messaging
- **Scope:**
  - registration, verification, reset, login, refresh with rotation and families, `kid` rotation
  - the CORS and CSRF boot checks; auth rate-limit policies
  - `Notification` (over phase 1's channel port and email adapter), default templates and overrides, the Babel formatter
  - the `on_commit` sweeper framework, re-driving queued notifications first
- **Owns:** A1c, A2 (API), A3, A3a, A4, A4a, A4b, A4c, A4d, A5, A5a, A9a (auth), A9c, T2, T2a (framework), T2b, F3, L6.
- **Out:** consent capture (phase 11, added to the API later as a new field); guest order links (phase 5).
- **Order-referencing tables:** `Notification`. It has no order yet, but it will reference one, so it gets its I8 placement now.

### 4 — Cart, pricing and the quote
- **Scope:**
  - Cart and CartItem (public ids, signed guest token), the claim on login
  - `ShippingMethod` with its translations and rules
  - the tax port with core's calculator; `reprice_cart()` with the input-hash compare-and-set
  - Discount (without redemption); coupon apply with G6 reasons; coupon-validation rate limit
- **Owns:** C12b, M3, M4, M5, M7, M8, M9, M10, M10a, M10b, M11 (quote), G1a, G3, G3a, G3b, G4 (at apply), G4a, G5, G6, F1d (discounts), Q3c (cart limits), A9a (coupon).
- **Out:** `Idempotency-Key`, confirmation token, redemption (phase 5).

### 5 — Checkout and orders
- **Scope:**
  - the two-transaction checkout; the S5 lock helper with the **full** global order (including `payment_event` and `placement_guard`, even though they aren't locked yet)
  - `IdempotencyKey` with its lifecycle and in-progress sweeper; `ConfirmationToken`
  - Order and OrderItem with every copied and snapshot column (F1b including COD refusal and return rules, R6 evidence, quote hash, unique cart id)
  - `transition_to()` with the full S1 table; `OrderStatusLog`; `ReviewCase` with every cause
  - the method registry; `allocate_order()`; `DiscountRedemption`; the zero-total path and its cap
  - `FraudAssessment`; `display_status`; guest order access; the kill switch
  - `Invoice` with issuance, numbering, the I7 trigger and the no-authority adapter; the invoice sweeper
- **Owns:**
  - M6, M6a, M11 (order), M12
  - C4b, C10, C10a, C11, C12, C12a
  - G1, G2, G4 (at commit)
  - O1–O6, O8, O9
  - S1, S1a, S1b, S1c, S3, S4, S5, S7 (columns only), S9
  - R6, F1b, F1d (orders)
  - I1, I1a, I1b, I3, I4, I5, I5b, I7
  - V6 (zero-total cap), V7, N1
  - A8, A8a, A8b, A9a (checkout, guest link)
  - D7a (`Order`, `OrderItem`)
- **Out:** payment attempts and reservations (phase 6); cancellation of any kind (phase 9).
- **Protected tables:**
  - D7: `OrderStatusLog`, `FraudAssessment`, `Invoice`
  - D7a: `Order`, `OrderItem`
- **Order-referencing tables:** OrderItem, OrderStatusLog, ReviewCase, FraudAssessment, DiscountRedemption, Invoice, IdempotencyKey (if it stores an order reference).

### 6 — Provider payments
- **Scope:**
  - Payment, with the payable and both partial indexes, all three balance columns, and a nullable provider key shaped for P13b
  - `OrderAdjustment` table only (section 1, item 10)
  - Reservation; `PaymentEvent` in access-controlled storage
  - the two-transaction webhook; the return-page check
  - MockProvider: sessions, events, settlement report, secret rotation, live/test mode
  - reconciliation for attempts; provider disable; a "no rules" `FraudAssessment` on every attempt; the provider `paid` invoice trigger
- **Owns:** P1–P13a, P14–P18, M13 (columns), C2, C2b, C3 (with reservations), C4, C4a, C5, C9a (reserved), T5, T6 (attempts), X12, A10, A9a (return-page), N2, W2a (payment).
- **Out:** refunds, disputes (phase 8); fraud rules (phase 7).
- **Protected tables:**
  - D7: `PaymentEvent`, `OrderAdjustment` (status trigger)
  - D7a: `Payment`
- **Order-referencing tables:** Payment, Reservation, PaymentEvent, OrderAdjustment.
- **Due before this phase:** parked item 1 (whether `on_hold` gets a guaranteed message), because this is the first phase that enters `payment_review`.

### 7 — Fraud controls
- **Scope:** failed-attempt limits, initiation limits, card-level blocking, card-testing detection with 3-DS escalation, 3-DS threshold, AVS/CVV recording.
- **Owns:** V1, V1a, V1b, V2, V3, V4, V5; V6 is extended.
- **Due before this phase:** V3's threshold defaults. The owner has to approve starting values, and V3 doesn't ship without them.

### 8 — Refunds and disputes
- **Scope:**
  - Refund with `refund_group`, the full status enum and the R1c splitter; second approval
  - `CreditNote`
  - Dispute and the dispute-deadline alert
  - C6a automatic resolution and the C6b alert
  - refund reconciliation; settlement reconciliation (T7)
- **Owns:** R1, R1a, R1b, R1c, R2, R2a, R2b, R2c, R4, R5, M14, M15, C6a, C6b, I2 (credit notes), T6 (refunds), T7; T2a is extended to refunds and `allocation_failed`.
- **Out:** the offline COD payout (phase 10); refunds caused by cancellations or returns (phase 9 adds those callers).
- **Protected tables:**
  - D7: `CreditNote`
  - D7a: `Refund`
- **Order-referencing tables:** Refund, Dispute, CreditNote.

### 9 — Fulfilment, cancellations, adjustments, returns
- **Scope:**
  - Shipment and ShipmentItem with delivery statuses, including refusal and `received_back` for prepaid orders
  - derived fulfilment; the courier port
  - CancellationRequest; item cancellation; the abandoned-order job
  - OrderAdjustment writers: address change with difference payment, refused delivery
  - `DebitNote`; ReturnRequest with restock and the expiry job
- **Owns:** S2, S2a, S2b, S6, S8 (non-COD), O10, O11, G7, C6, R3, R7, R8, I2 (debit notes), W2a (courier).
- **Protected tables:** D7: `DebitNote`.
- **Order-referencing tables:** Shipment, ShipmentItem, CancellationRequest, ReturnRequest, DebitNote.

### 10 — Cash on delivery
- **Scope:**
  - admin-confirmed payment with its row created at commit
  - allocation at placement
  - `PlacementGuard` and V8 caps
  - COD refusal with `received_back`; collection adjustment; `uncollected`; offline refund payout
  - the COD invoice trigger
- **Owns:** P13b, P13c, C2a, V8, S8 (COD leg); S1 `uncollected` is exercised here.
- **Due before this phase:** parked item 2 (the per-IP COD cap default).
- **New tables:** `PlacementGuard` (in I10b's inventory).

### 11 — Tax authority, data protection, retention
- **Scope:**
  - authority submission and reconciliation through the port
  - `Consent`; erasure against I10b's inventory, with deferred erasure; the erasure log and restore replay
  - staff-started export
  - the retention job with I8's deletion order; the monthly restore test; backups
  - a full DoD re-run
- **Owns:** I5a, I6, I8, I8a, I9, I10, I10a, I10b, I11, I12, Q2c, D4, D4b, D4c.
- **Protected tables:** `Consent` (D7, with `subject` writable only by the retention role).

---

## 3. Rules that apply to every phase

Every phase file lists these under "Contracts that apply" whenever it touches
the area, and fills their rows for its own tables and endpoints:

- M1, M1b, M2: every money column
- Q1, Q2, Q2a, Q2b, Q3, Q3a, Q3b: every list, detail and admin page
- X1–X11, X13, X13a, X5a: every new error code goes in the registry
- D1, D2–D2f, D5: every uniqueness rule has a concurrency test
- D7 and D7a: grants and triggers go in the migration that creates the table
- D7b, T1–T3, A6, A7, A12, W7, W8, W8a, L2, L4
- F1a: every setting; N4a: every job; N5: every alert; S5: every lock
- I8: every new table that references an order is placed in one of I8's three groups

---

## 4. Test data strategy (open item 5)

1. **PostgreSQL only.** Tests use PostgreSQL at the production major version,
   never SQLite. Grants, triggers, partial indexes and `lock_timeout` are part
   of what's under test.
2. **Tests run as the real roles.** The migration role builds the test
   database, and tests connect as `web`, or as `job` for job tests. A bare
   `save()` or a raw stock update then fails in tests exactly as it would in
   production.
3. **No JSON fixtures.** They bypass services and break on every migration.
4. **Factories only for rows with no invariant**: product, variant, category,
   user, address, discount, shipping rule (factory_boy).
5. **Scenario builders for everything with an invariant.** Orders, payments,
   refunds, adjustments and stock are built only through domain services, with
   functions such as `place_order(cart, method)`, `pay_with_mock(order,
   outcome)` and `refund(order, amount)`. A factory that writes an order
   directly would bypass D7a, M11 and the ledger. Each phase adds the builders
   for its services.
6. **M11 is checked automatically.** A pytest fixture asserts M11 on every order
   a test touches, in the tax mode the test runs in. This covers the DoD item.
7. **Concurrency tests use real connections.** They run as transactional tests
   with threads, separate connections and a barrier. Every D5 row and the S5
   deadlock test use this, and they're gating in CI.
8. **Time is frozen.** `time-machine` handles every TTL and window. DST tests
   run in a store timezone that has a transition.
9. **MockProvider is scripted per test.** A test sets:
   - the session outcome: success, decline, `requires_action`, timeout or ambiguous
   - the events: delayed, duplicated, reordered, wrong amount or currency, unknown payment, signed with the previous secret
   - the settlement report

   Webhooks go through the real endpoint as raw bytes (P3).
10. **Port contract suites.** Each port (payment, tax, notification channel,
    courier, tax authority) has one parametrized suite that every adapter must
    pass. Core's own adapters run it in gating CI. A real adapter runs it
    against its sandbox in a separate, non-gating CI job, and must pass before
    any deployment enables it.
11. **Query counts are measured at two sizes.** Each list is run at N and 3N
    rows and must give the same count.
12. **`seed_demo` command.** It runs through the services, is idempotent, and is
    extended every phase. The smoke script and the upgrade-path gate (section 1,
    item 8) use it as their "realistic data".

---

## 5. Gates outside the phases

These come before the first paying client, not before a phase: open item 2
(PITR verified against `BACKUP_RPO`), item 3 (the first jurisdiction's authority
adapter), item 6 (erasure log storage), item 7 (license text, W9) and item 8
(retention values).

---

## Assumptions

- The test runner is pytest with pytest-django.
- Core ships an SMTP email adapter. The demo points it at a sandbox SMTP inbox.
- `CreditNote` and `DebitNote` arrive with their first issuer (phases 8 and 9), not with `Invoice`. The I7 trigger covers each one in its own migration.
- The method registry lists all three v1 codes (`cod`, the MockProvider card method, `zero_total`) from phase 5. COD isn't offered until phase 10. The order's method column is validated against the registry, with no database enum to migrate.
- L1a's store-local business-day scheduling is built and tested in phase 1 with a test job, because no v1 job is known yet to need it.
- Each phase is released as core minor `0.N.0`. 1.0.0 is the first version sold.
- Consent capture is added to the registration and checkout APIs in phase 11 as a new optional field, which X8 treats as non-breaking.
