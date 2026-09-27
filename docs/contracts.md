# contracts.md

Invariants for this codebase. These do not change between phases.

Read this file before every task. If a requested change would break a rule
here, stop and say so instead of implementing it. A phase file can narrow
scope but can never override a contract.

Each rule states **what must hold** and **why**. The "why" is not decoration —
it is how you judge an edge case the rule does not literally cover.

**Overlap versus conflict.** Two rules *overlap* when both apply to the same
code and both can be satisfied: satisfy both, which in practice means meeting
the stricter requirement, because it is the one both imply. Two rules
*conflict* when satisfying one breaks the other: **stop and ask the owner,
quoting both.** Never resolve a conflict by picking the stricter rule — the
conflict itself is information the owner needs, and the stricter rule may be
the wrong one.

The closing section, **Enforcement principle**, is the test to apply to any
situation these rules do not name.

---

## 1. Money

### Representation

**M1. All monetary amounts are integers in the currency's minor unit, stored
as 64-bit integers** (`BigIntegerField` / `bigint`). `1999` means 19.99 EGP;
`1999` means 1.999 KWD. Never float. Never Decimal in a JSON response.
*Why:* JSON has no decimal type, so a fractional number becomes a float in the
client and errors compound across a cart. A 32-bit column caps at about
21 million EGP — reached by reports and aggregates long before any single
order, and by a single order in currencies such as VND.

**M1a. Each currency's minor-unit exponent comes from one ISO-4217 table in
core** (EGP 2, KWD 3, JPY 0), used by every calculation, formatter and
adapter. Never assume two decimals. Where a provider's convention for a
currency differs from ISO, the payment adapter converts at its boundary; the
domain never sees the provider's convention.
API responses carry the exponent with every amount (Q3b).
*Why:* three-decimal currencies are common in the region (KWD, BHD, OMR, JOD,
TND). Assuming two misprices them by a factor of ten.

**M1b. Stored monetary amounts are never negative.** `CHECK (amount >= 0)` on
every money column. Direction is carried by the record type — `Refund`,
`CreditNote`, `Dispute`, a discount — never by sign. Computed values (M14) may
be negative; stored values may not.
*Why:* signed amounts make every sum depend on a sign convention someone will
get wrong once. A record type cannot be inverted by accident.

**M2. Every monetary amount is paired with an ISO-4217 currency code.**

**M3. One currency per order.** Every line, the payment, and every refund
share the order's currency. A cart may never mix currencies. The single
exception is `dispute_fee_amount`, which carries its own currency (M13).

**M3a. In v1 the currency is one store setting, `STORE_CURRENCY`.** Every cart
and order takes its currency from it. Multi-currency is out of v1 scope.
Locked once any order or discount exists (F1d).

**M4. Client-supplied monetary amounts and currencies are never read by
pricing or domain code.** Not validated — ignored.
*Why:* validating a client-supplied price still makes the client a source of
truth. It must not be one.

### The quote

**M5. The cart stores a server-computed quote, and it is the sole baseline for
price-change detection.** The quote covers every amount the customer is shown:
line prices, allocated discount, shipping, tax and total.

- **Source of truth:** the pricing service, reading the catalog, shipping
  rules and tax calculator at quote time. Never client input (M4), never the
  live catalog at checkout.
- **Mutation path:** `reprice_cart()`. **Its computation never runs inside
  `atomic()`** (T1, M6a), because the tax calculator may be a network adapter.
  No other code writes cart amounts.
- **Concurrency boundary:** `reprice_cart()` hashes its inputs — cart lines and
  quantities, variants, shipping address, shipping method, discount code —
  before it computes. The write is a separate small `atomic()` that locks the
  cart row, recomputes that hash under the lock, and **discards the result if
  it differs**; the caller reprices again. The quote is replaced wholesale,
  never field by field.
  *Why:* a row lock cannot be held outside a transaction, so the computation
  cannot run under one — and the comparison under the lock is what stops a slow
  repricing from overwriting a newer quote.
- **Triggers:** `reprice_cart()` runs whenever an input to any amount changes —
  cart lines, shipping address, shipping method, discount code — and the new
  quote is returned to the client in that response.
- **Incomplete quotes:** before an address is known, shipping and tax are
  `null` (not calculated), never `0`. Checkout rejects an incomplete quote.

Every cart carries `priced_at` and a per-line unit price. A quote older than
`CART_SNAPSHOT_TTL` (default 30 minutes, configurable) is stale and is repriced
before checkout proceeds; if the repricing changes any amount, M6 applies.

*Why:* M6 compares against "what the customer saw." Shipping and tax depend on
the address, so a snapshot taken before the address existed would fail M6 on
every checkout. The quote is the server-side artifact that holds what was
actually shown, and M4 forbids the only other candidate.

**M6. If any amount differs between the quote and a fresh repricing at
checkout, no order is created.** The API returns the new quote with a
`price_changed` code **and a server-issued `confirmation_token` bound to a hash
of that new quote.** Submitting the token with a fresh `Idempotency-Key` is the
confirmation. If prices change again before the confirmation arrives, the
token is rejected and a fresh `price_changed` with a new token is returned.
The token expires after `CONFIRMATION_TOKEN_TTL` (default 15 minutes).
*Why:* the customer must not be charged a number they never saw — including
the second time. The server-issued token is what keeps C10 from locking out an
honest client forever — see C10.

**M6a. The checkout comparison spans two transactions, and the commit
re-asserts what it can.** `reprice_cart()` may call a tax calculator backed by
a network adapter (M10a), so it never runs inside `atomic()` (T1). Checkout is
therefore:

1. Reprice outside any transaction. Compare against the cart's quote (M6).
2. Hash the quote that comparison approved, and carry the hash into the commit.
3. Open the order-commit transaction. Under the S5 locks, re-read and re-assert
   the inputs the hash covers that live in the database: each line's unit
   price, the discount's validity and value (G4), and the shipping cost.
4. Any divergence: no order is created, and the response is `price_changed`
   (M6) with a fresh quote and token.

**Tax is not re-asserted inside the transaction.** Where the calculator is a
network adapter, the window between the repricing and the commit is accepted.
Where it is in-process, the domain may re-assert it and does.

The approved quote and its hash are stored on the order as the totals shown at
checkout (R6).

*Why:* M6 promises the customer is never charged a number they never saw, and
T1 makes the comparison and the commit two separate transactions, so something
has to close the gap between them. The database-backed inputs are the ones a
concurrent writer can change and the ones a lock can cover; a tax service's
answer is neither, and pretending otherwise would put an HTTP call inside the
checkout lock — the exact failure T1 exists to prevent.

### Rounding and allocation

**M7. Non-tax arithmetic multiplies first and rounds once per value, using
`ROUND_HALF_UP` to the minor unit (M1a).** That mode is fixed, not
configurable.

**Tax rounding is declared by the tax calculator (M10a)**: its mode, and its
level — per line, or per document. The domain applies what the adapter
declares and records it on the order. Where the level is per document, the
document tax is allocated back to lines by M8, so M9 and M11 still hold.
*Why:* some jurisdictions prescribe how tax is rounded. Everything else is our
choice, and one fixed choice keeps it reproducible.

**M8. Order-level amounts are allocated across lines by largest remainder.**

| Amount | Computed | Allocated |
|---|---|---|
| Percentage discount | at order level, on the discountable subtotal | to lines, weighted by line value |
| Fixed discount | the fixed value, clamped (G3) | to lines, weighted by line value |
| Free-shipping discount | against shipping only | never to lines |
| Document-level tax (M7) | at order level, by the tax calculator | to lines, weighted by line tax base |

The residual goes to the line with the largest fractional remainder; ties
break on lowest line id. Allocation is deterministic and reproducible from
stored values.

**M9. Order-level `subtotal`, `discount` and `tax` are defined as the sum of
the stored per-line values** (plus shipping values where M11 says so). They
are never computed a second time from percentages.
*Why:* O1/O2 require integer amounts per line. The sum of rounded lines
differs from a rounded sum by a minor unit or two, routinely — so one of the
two must be derived from the other. Summing the lines makes M11 true by
construction rather than by coincidence.

### Totals

**M10. Tax is computed per line from the line's tax category, not from a
single store-wide rate.**

```
line_net_i    = line_total_i - allocated_discount_i
shipping_net  = shipping - shipping_discount
line_tax_i    = tax_calculator(line_net_i, tax_category_i, jurisdiction)
shipping_tax  = tax_calculator(shipping_net, SHIPPING_TAX_CATEGORY, jurisdiction)
```

Every product carries a tax category (standard, reduced, zero-rated, exempt).
Shipping's taxability is its own category, not derived from
`PRICES_INCLUDE_TAX`.
*Why:* a single `TAX_RATE` cannot express mixed baskets (food vs non-food),
zero-rated goods, or a second jurisdiction — and whether shipping is taxable
is a fact about the law, not about how prices are displayed. Retrofitting
per-line tax into a live order model is one of the worst migrations in
commerce.

**M10a. Tax calculation is a pluggable port.** The domain calls
`tax_calculator(...)`; adapters implement a flat rate, a rate table, or an
external tax service, and each declares its rounding (M7). The domain never
contains a rate.

**M10b. The rate, category and rounding used are snapshotted onto each
`OrderItem` and the order.** Historical orders never recompute tax from
current configuration (O4).

**M11. The total invariant, asserted at every stage of the order lifecycle:**

```
tax == sum(line_tax_i) + shipping_tax
```

Tax-exclusive (`PRICES_INCLUDE_TAX = False`):
```
total == sum(line_net_i) + shipping_net + tax
```

Tax-inclusive (`PRICES_INCLUDE_TAX = True`):
```
total == sum(line_net_i) + shipping_net
```
Under inclusive pricing each `line_tax_i` is extracted from the line, never
added.

The mode is the order's copied `PRICES_INCLUDE_TAX` (F1b), never the current
setting.

Asserted on **effective** totals (O10) each form gains one term,
`collection_difference` — the sum of applied `collection_adjustment` deltas
(P13c), and zero on every order that has none:

```
effective_total == sum(line_net_i) + shipping_net + tax + collection_difference
```
(and the same term added to the tax-inclusive form). It sits outside every line
and every tax base: it changes no `line_net_i`, no `line_tax_i` and no `tax`.
*Why:* a cash difference at the door is not a price change, so allocating it
across lines (M8) would move a tax base over a rounding error. Given no term of
its own it has nowhere to live, and M11 fails on the first order that has one —
which is an assertion failure on a delivered, collected sale.

**M12. Dependent monetary fields are mutated atomically.** No transaction may
expose an intermediate state where M11 does not hold.

### Balances out

**M13. A payment carries three independent balance columns**, each with its
own ceiling:

| Column | Currency | Ceiling | Meaning |
|---|---|---|---|
| `refunded_amount` | order currency | `<= paid_amount` | refunds the store initiated |
| `disputed_amount` | order currency | `<= paid_amount` | money reversed by the provider |
| `dispute_fee_amount` | `dispute_fee_currency` | none | provider penalty, an expense |

Row-level `CHECK` on the first two. `dispute_fee_amount` is not part of any
ceiling, and carries its own currency because providers commonly charge it in
the settlement currency rather than the order currency.

`paid_amount` is the amount actually captured on that attempt. It is written
once, by the confirmation that moves the attempt to `succeeded` (P1) — for an
admin-confirmed method, the cash the admin recorded (P13b) — and it is the base
of both ceilings above and of M14.
*Why:* folding disputes into the refund ceiling makes real sequences
unrecordable — paid 10000, goodwill refund 3000, then a full chargeback of
10000 is 13000 genuinely gone, and a single ceiling refuses the write so the
dispute cannot be recorded at all. Dispute fees are an expense, not a return
of the customer's money.

**M14. Net received is computed, never stored:**
`paid_amount - refunded_amount - disputed_amount`, all in the order currency.
It may go negative once fees are counted, and that is a real state.

**M15. The refundable balance is read, checked and consumed inside one
transaction, under `select_for_update` on the payment row.**
*Why:* the CHECK constraint does not stop two admins both reading the same
balance, both passing, and both refunding. The limit is a concurrency
invariant, not a validation rule.

## 2. Orders — historical accuracy and change

### What the order copies

**O1. `OrderItem` copies, at purchase time and from the database, never from
the request:** product name, variant name, SKU, the variant's option values
("Size: L, Colour: Black"), unit price, tax category and rate (M10b). A FK to
the variant may exist for reference, but display, fulfilment, invoices,
refunds, accounting and historical totals always read the copied values.

Text fields are copied **in the order language (O8)**, and additionally in the
invoice language when the tax-authority adapter requires one that differs
(L3).
*Why:* the warehouse picks by SKU and options, and a variant can be renamed,
re-optioned or deactivated after the sale. An invoice that must be in a legal
language cannot be produced later from a catalog that has since changed.

**O2. The same copy rule applies to shipping cost, tax amount and discount
amount.** The applied discount is snapshotted with everything needed to
explain it, so it is never recalculated from the current coupon.

**O3. The order copies its shipping and billing addresses** — recipient name,
phone and every address field — as its own columns. It never holds a live FK
to a customer's saved `Address`.
*Why:* a customer editing their address book must not rewrite where a past
order was shipped, what its invoice says, or what the dispute evidence
(R6) shows.

**O4. No historical order calculation depends on mutable product, variant,
category, shipping, tax, coupon, pricing or address data.**
*Why:* changing a promotion, a tax rate or an address book entry must never
rewrite the meaning of an existing order.

### Identity and access

**O5. A guest order stores its own `email` and `phone` columns.** A guest
order is attached to a customer account **only after that account's email is
verified** and matches the order's email. Attaching revokes the guest access
token (A8).
*Why:* attaching by unverified email lets anyone register with a victim's
address and read their order history, including where they live.

**O6. Order numbers are random, human-readable and enumeration-resistant.**
8 characters — a constant in code (D2f) — from an alphabet without
look-alikes (no `0/O`, `1/I/L`), unique by constraint (D5), regenerated on
collision (X11a). Internal primary keys never appear in URLs, API responses or
customer communication.
*Why:* COD customers read order numbers to couriers and support over the
phone. Sequential or internal ids leak volume and invite enumeration.

**O7. Records referenced by history are never hard-deleted.** Products,
variants and categories use `active = False`. Every FK from an order, order
item, payment, refund, invoice, credit/debit note, adjustment or ledger row
uses `on_delete=PROTECT`, never `CASCADE` or `SET_NULL`. A row that must
outlive what it references — the stock ledger outliving its order (C8a) —
records that reference by copied identifier instead, because `PROTECT` and a
later delete of the parent cannot both be satisfied through a foreign key.
Users are removed
only through erasure (I10), which anonymises the row in place.
A deactivated variant still in a cart is flagged unavailable by
`reprice_cart()` (M5), and checkout is blocked until it is removed.
*Why:* soft deletion is meaningless if one cascading delete through
a user or product can still wipe the orders beneath it.

**O8. The order copies the language it was placed in**, and every
customer-facing document and message about it renders in that language (L3).

### After the order is placed

**O9. Once committed, an order's lines and amounts are immutable.** The only
ways the order changes afterwards:

| Change | Path |
|---|---|
| Cancel the whole order | S2 |
| Cancel an item, or part of its quantity | S2a |
| Change the shipping address | O10 |
| Refused delivery | S8 |
| Money back | refunds and returns (section 5) |

Every change after commit is an `OrderAdjustment` or a refund, never an edit
of the original rows, and every one writes an audit record with actor and
reason. The database enforces this by grant (D7a).
*Why:* an order is evidence — for the customer, the tax authority and a
dispute. Edited history cannot be trusted by any of them.

**O10. `OrderAdjustment` records every post-commit change to what the order is
worth.** It is immutable once applied, and holds: order, type
(`address_change`, `item_cancellation`, `refused_delivery`,
`collection_adjustment` — P13c), before and
after snapshots, per-line
tax deltas, shipping and shipping-tax deltas, total delta, status
(`awaiting_payment | applied | cancelled | expired`), actor, reason.
Its status moves only `awaiting_payment → applied | cancelled | expired`,
enforced by trigger (D7).

- **Effective totals** = original totals + all `applied` adjustments. M9 and
  M11 are asserted on effective totals, per line and in total, M11 including the
  `collection_difference` term (P13c).
- **The deltas above are computed from the before and after snapshots, never
  stored as signed columns.** M1b admits no negative stored money amount, and
  an adjustment's direction is not fixed by its type — an `address_change` runs
  either way — so there is no record type to carry the sign. The snapshots are
  the stored values; every delta, per line and in total, is derived from them
  and may be negative as M1b's computed values may.
- Each applied adjustment issues a linked **debit note** (delta > 0) or
  **credit note** (delta < 0) against the invoice (I2). A zero delta issues
  neither. An adjustment applied **before the invoice is issued** (I1a)
  issues no note; the invoice, when issued, reflects the effective totals. The
  refund that pays out a negative delta issues no second note (R1c).

**O11. Shipping-address change.** Admin only, and only before the first
shipment. The new address is repriced through the pricing service (M5), which
yields the shipping and tax deltas — the tax jurisdiction may change with the
address.

**The discount is not re-evaluated.** The repricing keeps the order's discount
terms, as S2a does: a free-shipping discount covers the new shipping cost, and
the discount's minimum is not re-checked.

| Delta | Provider-confirmed method | Admin-confirmed method (COD) |
|---|---|---|
| `0` | Applied immediately | Applied immediately |
| `> 0` | Adjustment `awaiting_payment`; the customer receives a payment link for exactly the delta. Applied in the same transaction as that payment's `paid` confirmation (P1) | Applied by the admin; the amount to collect increases; the customer is notified |
| `< 0` | Applied; the delta is refunded (R1, M15) | Applied; the amount to collect decreases; the customer is notified |

A `zero_total` order (S1c) follows the provider-confirmed column; its payment
link offers provider-confirmed methods only.

Rules for `awaiting_payment`:
- The address does not change, **no shipment may be created**, and **no further
  address change may be started**, until the adjustment is applied or ends. At
  most one adjustment per order is in `awaiting_payment`, by constraint (D5,
  P13a).
- The difference payment is a normal attempt (P13): expected amount copied
  from the adjustment (P10), own idempotency key (P14). P12's payable total
  includes the adjustment it pays for.
- A failed attempt may be retried. After `ORDER_ADJUSTMENT_TTL` unpaid, the
  adjustment `expires` and the original address stands.
- **An adjustment and its attempt end together.** In the transaction that
  expires or cancels the adjustment — the TTL job, or the cancellation that
  ends it first (S2) — its active attempt is moved to `cancelled` (P13) and
  cancelled at the provider where the adapter can (P13a, outside the
  transaction, T1). A capture that still arrives on it is a
  `superseded_capture`: the order enters `payment_review` (S1, S1b) and staff
  refund it.
  *Why:* an attempt left live past its adjustment can capture money for an
  address change that will never be applied — the adjustment is terminal, so
  nothing can apply it, and the capture exceeds the order's payable total
  (P12) with no rule saying where it goes. Ending the attempt with the
  adjustment puts that money on the one path the file already has for money
  that arrived after the thing it was for stopped waiting.
- Order payment status does not change **on this path**: the adjustment is
  applied only once its money is confirmed, so the order is never left owing.

Creating or applying an adjustment never writes payment status itself. A
*negative* delta is not an exception to that but a consequence of it: applying
it refunds the difference, and that refund moves the order through R1 and S1
exactly as any other confirmed refund does — `paid → partially_refunded`.
*Why:* a card cannot be charged again without the customer, so "pay the
difference" is a customer action, and the order must not move to an address
nobody has paid for. Re-evaluating the discount would charge the customer for
an address correction under terms they never agreed to.

---

## 3. Order state

**S1. Payment status and fulfilment status are two independent fields on the
order, each with the closed transition set below.** `transition_to()` rejects
any move not listed.
*Why:* with cash on delivery, goods ship before money arrives. And a status
chain that does not list every legal move gets extended ad hoc by whichever
code path first needs a new one.

**Payment status is order-level and reads order-level aggregates**, summed
across every successful `Payment` on the order (an order may have several: the
original — which for an admin-confirmed method is created at commit, P13b — and
adjustment top-ups under O11):

```
paid_total      = sum(paid_amount)       over successful payments
refunded_total  = sum(refunded_amount)   over successful payments
disputed_total  = sum(disputed_amount)   over successful payments
effective_total = the order's effective total (O10)
```

| From | To | Trigger |
|---|---|---|
| `unpaid` | `pending` | online payment attempt created **for the order's own total**. An attempt created for an `OrderAdjustment` (O11) creates no transition — the order's payment status does not change. |
| `unpaid` | `paid` | admin records cash collected, **equal to `effective_total`** — admin-confirmed methods only (P1, item 3; S1a). A difference between the cash and the total is recorded as a `collection_adjustment` first (P13c) |
| `unpaid` | `paid` | the system, at order commit — **`zero_total` orders only** (P1, item 4; S1c) |
| `unpaid` | `uncollected` | admin action, admin-confirmed methods only, permitted **only when every shipment is `received_back` and nothing was collected** (S8). It is never automatic — see S8. |
| `pending` | `paid` | authenticated confirmation (P1) that passes P11 and P12 |
| `pending` | `failed` | authenticated failure result, or a definitive session-creation rejection (P13) — never a timeout (P15) |
| `pending` | `unpaid` | the order's only active attempt **for its own total** ended `expired` or `cancelled` (P13) — the customer abandoned checkout. An attempt on an adjustment payable (P13a) is not counted here |
| `pending` | `payment_review` | amount or currency mismatch (P11), allocation failure (C5, C9a), undeterminable outcome (P16), or capture on a superseded attempt (P13a) |
| `failed` | `pending` | new attempt on the **same order**: a new `Payment` row with its own idempotency key (P13, P14). The order id and number never change. |
| `paid` | `partially_refunded` | confirmed refund, less than `paid_total` (R1) |
| `paid` | `refunded` | confirmed refund equal to `paid_total` (R1) |
| `partially_refunded` | `partially_refunded` | a further confirmed partial refund (logged per S4) |
| `partially_refunded` | `refunded` | cumulative confirmed refunds reach `paid_total` |
| `paid`, `partially_refunded`, `refunded` | `payment_review` | dispute opened (R4), or capture on a superseded attempt (P13a) |
| `unpaid`, `failed` | `payment_review` | an authenticated capture on an attempt that had already ended `expired` or `cancelled` (P13, P13a) — money that arrived after the order stopped waiting for it |
| `payment_review` | `paid`, `partially_refunded`, `refunded`, `charged_back`, `failed` | human resolution or reconciliation result |
| `charged_back` | `payment_review` | the provider reinstates disputed funds (R5) — a new `ReviewCase` is opened and the exit is recomputed from the aggregates |

`uncollected` is terminal: goods back, no money, order closed.
`charged_back` is **not** terminal — a reversed chargeback re-enters review
(above), because the money came back and the balances must follow it (R5).

**A capture on an attempt that had already ended reaches the order wherever it
sits.** `pending` on a live attempt, `unpaid` after an abandoned checkout
(P13's `expired`/`cancelled` rows are exactly what put the order there), or
`failed` after a later attempt failed — all three enter `payment_review` with
the S1b cause. An order already cancelled (S2, S2b) enters review too and stays
cancelled: `cancelled_at` is a timestamp, not a state, and staff refund from
there. Nothing about this path may end in a rejected transition, because the
money has already moved.

A dispute opened while the order is already in `payment_review` leaves the
status unchanged and opens its own review case (S1b). `pending` resolves
automatically through an authenticated confirmation or reconciliation (P1);
`payment_review` resolves through a human, except the automatic resolution
in C6a.

**Exits from `payment_review` are determined by the aggregates, not chosen,
and happen only once every review case is resolved (S1b). First match wins.**
`transition_to()` computes the status they imply and rejects any other target:

| Aggregates | Status |
|---|---|
| `paid_total == 0`, method not `zero_total` | `failed` |
| `paid_total == 0`, method `zero_total` (S1c) | `paid` |
| `refunded_total + disputed_total == 0` | `paid` |
| `0 < refunded_total + disputed_total < paid_total` | `partially_refunded` |
| `refunded_total + disputed_total >= paid_total`, `disputed_total == 0` | `refunded` |
| `refunded_total + disputed_total >= paid_total`, `disputed_total > 0` | `charged_back` |

Status names describe the balance; *why* money left is recorded on the
`Refund` and `Dispute` rows, never inferred from the status.

The last two rows are `>=`, not `==`, because **money out can exceed money
in**: a goodwill refund followed by a full chargeback of the same capture is
more than `paid_total`, which M13 keeps recordable on purpose and M14 reports
as a negative net. Tested for equality, that order matches no row, and a table
that rejects every target it did not compute would hold it in `payment_review`
for good.

**Fulfilment status is fully derived from item quantities** (S6, S7). Summed
over the order's lines, with `Q` quantity, `S` shipped, `C` cancelled,
`R` returned — first match wins:

| Condition | Status |
|---|---|
| `R > 0` and `R == S` and `S + C == Q` | `returned` |
| `R > 0` | `partially_returned` |
| `S == 0` | `unfulfilled` |
| `S + C == Q` | `fulfilled` |
| otherwise | `partially_fulfilled` |

Legal transitions (the derived target must be one of these, or
`transition_to()` rejects it and alerts):

| From | To |
|---|---|
| `unfulfilled` | `partially_fulfilled`, `fulfilled` |
| `partially_fulfilled` | `fulfilled`, `partially_returned` |
| `fulfilled` | `partially_returned`, `returned` |
| `partially_returned` | `partially_returned`, `returned` |

Fulfilment may advance while payment is `unpaid` **only for methods registered
as ship-before-payment** (COD alone in v1). For every other method, fulfilment
requires payment status `paid` and a verified stock allocation (C4b, C6).

**S1a. The order stores its payment method as a code from a registry in core.**
Each registered method declares two facts, and domain code reads only those
facts, never the method code itself:

| Fact | Values | Governs |
|---|---|---|
| `confirmation` | `provider`, `admin` or `system` | which P1 path may mark it `paid`; whether a `Payment` row exists, and when it is created (P13b, S1c) |
| `ships_before_payment` | `true` or `false` | whether S1 lets fulfilment run while `unpaid`; allocation timing (C2a); refusal handling (S8) |

v1 registers `cod` (`admin`, ships before payment), provider-confirmed card
payments through `MockProvider`, and `zero_total` (`system`, does not ship
before payment — S1c). Later methods — InstaPay, Vodafone Cash,
Apple Pay — are a registry entry plus, for `provider` methods, a payment
adapter (P17). Adding one never changes domain code.
*Why:* a check written as `if method == "cod"` gets duplicated across status,
stock and permissions, and every new method becomes a hunt for those lines.
Registering an `admin`- or `system`-confirmed method widens P1, so it is a
stop-and-ask decision, not a config change.

**S1b. Every entry into `payment_review` opens a `ReviewCase`**: order, cause,
status (`open | resolved`), opened_at, resolved_at, resolved_by (typed actor,
S4), resolution, `auto_resolution_attempted_at` (nullable). Causes:
`amount_mismatch` (P11), `allocation_failed` (C5, C9a), `undeterminable`
(P16), `superseded_capture` (P13a — any authenticated capture on an attempt
that had already ended, whether superseded by a newer one, `expired` or
`cancelled`), `dispute` (R4). A cause arising while the
order is already in review opens another case.

- The order leaves `payment_review` only when every case is resolved, by the
  aggregate-determined exit in S1.
- An `allocation_failed` case resolves only when every line not cancelled has
  a verified allocation (C4b) **and** every refund requested under it is
  `refunded`. The order leaves review in the transaction that completes the
  last condition.
- Other causes resolve by staff action.

*Why:* five different problems share one status. Without a recorded cause,
staff cannot tell what they are resolving, and a status exit can quietly skip
the one still open. And T2a's sweeper can only find the cases C6a never
reached if the case records whether it was attempted.

**S1c. A zero-total order is paid at commit, by the system.** When the
quote's total is 0 at checkout, the order is placed with the `zero_total`
method (S1a). No other method is offered for it, and `zero_total` is refused
for any order whose total is above 0. In the transaction that creates the
order:

- stock is allocated through `allocate_order()` (C4b); if any line is short,
  no order is created and `OutOfStock` is raised;
- payment moves `unpaid → paid` with actor `system` (P1, item 4). No
  `Payment` row is created;
- one `FraudAssessment` is written (V7).

Placement is capped: at most `ZERO_TOTAL_ORDER_LIMIT` zero-total orders
(default 3) per normalized email (A1a), phone (V8) and IP (A9b) in any
24 hours. **The count is held in the rate-limit store (A9) and incremented
atomically (C1)**, keyed on each normalized identity. A breach refuses the
order with `fraud_blocked` (V6).

After commit the order follows the provider-confirmed rules: an address
change with a positive delta sends a payment link offering provider-confirmed
methods only (O11), and a cancellation's refund step does nothing while the
order has no successful payment (S2).
*Why:* a 100% discount with free shipping is a legitimate promotion, and
without this path the order could never reach `paid` — no provider takes a
zero-amount charge, and the review exits map `paid_total == 0` to `failed`.
A free order costs an attacker nothing to place, so it is capped as COD is
(V8).

**S2. Cancelling the whole order sets a nullable `cancelled_at` timestamp; it
is not a state.** Customer-initiated via `CancellationRequest`, resolved by
staff with `approve_cancellation` (A6a); the order does not change until they
act. Item-level cancellation is S2a.

**`CancellationRequest` lifecycle:** `open → approved | rejected | withdrawn`.
At most one `open` request per order at a time — enforced by a partial unique
constraint — and the customer may edit it while it is open. Sequential
requests are normal: cancel one item, get it approved, then request another.
Approval executes the cancellation (S2 or S2a) **in the same transaction**;
rejection records a reason.

Before any cancellation executes, **an `OrderAdjustment` in
`awaiting_payment` on the order is cancelled first** (O11), in the same
transaction.

Every combination that permits cancellation is listed; **any combination not
in this table is not cancellable and raises `InvalidTransition`.**

| Payment | Fulfilment | On cancel |
|---|---|---|
| `unpaid` | `unfulfilled` | Release active reservations; for COD, return allocated stock (C2a). Close. |
| `unpaid` (COD) | `partially_fulfilled` | Return unshipped allocated stock. The shipped portion follows S8. Payment stays `unpaid` until cash for delivered goods is collected. |
| `failed` | `unfulfilled` | Release active reservations. Close. |
| `paid`, `partially_refunded` | `unfulfilled` | Return allocated stock; refund the remaining refundable balance (M15). |
| `paid`, `partially_refunded` | `partially_fulfilled` | Return unshipped allocated stock; refund the unshipped portion, capped at the refundable balance (M15); the shipped portion follows the return flow (R7). |
| `refunded`, `charged_back` | `unfulfilled` | Return allocated stock. No money moves. Close. |
| `refunded`, `charged_back` | `partially_fulfilled` | Return unshipped allocated stock; the shipped portion follows the return flow. No money moves. |
| `payment_review`, whose only open case is `allocation_failed` (S1b) | `unfulfilled` | Staff or the system (C6a) act directly; no `CancellationRequest`. Cancel the whole order or specific lines (S2a); refund the cancelled portion (R1), capped at the refundable balance. Remaining lines may be allocated (C4b). The order leaves review when the case resolves (S1b). |

Where a row refunds, the amount is split across the order's successful
payments and the balance it is capped at is the sum of theirs (R1c). Where the
order has no successful payment — a `zero_total` order that never took an O11
top-up (S1c, R1c) — the refund step does nothing.

Explicitly not cancellable, for the avoidance of doubt:

- **Fulfilment `fulfilled`, `partially_returned` or `returned`** — return flow
  only.
- **`pending`** — the attempt may still succeed. The `CancellationRequest`
  stays `open` and is re-evaluated when payment resolves.
- **`payment_review` with any open case other than `allocation_failed`** —
  resolve the review first.
- **`uncollected`** — already closed.

Stock returned on cancellation goes back through the stock service as a
`StockMovement` (C9). It is not a restock decision under R3: the goods never
left the building. Only consumed quantity is returned: a line with no consumed
reservation — for example after an expired one (C5) — returns nothing and
writes no movement. The line's consumed reservation is reduced by the same
quantity (C4b).

A whole-order cancellation returns the order's coupon use (G7).

**S2a. An item, or part of its quantity, can be cancelled while it is
unshipped.** Via a `CancellationRequest` scoped to specific `OrderItem`s and
quantities, under the same lifecycle and table as S2. Shipped quantity is not
cancellable (return flow only). Cancelling every remaining unshipped unit on
an unshipped order is a whole-order cancellation (S2).

- **The amount is the line's stored values** — unit price, allocated discount
  and tax (O1, O2) — for the cancelled quantity. For part of a line, the
  line's stored amounts are split per unit by largest remainder (M8).
- **Discount and shipping are not re-evaluated.** If the cancellation takes
  the order below a coupon's minimum or a free-shipping threshold, the
  customer keeps the original terms.
- It is recorded as an `item_cancellation` adjustment (O10): `cancelled_quantity`
  incremented (S7), stock returned through the stock service, a credit note
  issued, and the amount refunded (provider method, split per R1c) or removed
  from the amount to collect (COD).

*Why:* re-evaluating the discount on a partial cancellation charges the
customer for keeping part of the order — a surprise the customer never agreed
to and a dispute waiting to happen.

**S2b. Abandoned unpaid orders are cancelled by the system.** A scheduled job
cancels, through S2 with actor `system` and no `CancellationRequest`, every
order where all of these hold:

- the payment method is not ship-before-payment (S1a);
- payment status is `unpaid` or `failed`, and fulfilment is `unfulfilled`;
- no attempt on the order's own total is active (P13a) — an attempt on an
  adjustment payable does not keep the order alive, and the cancellation ends
  that adjustment first (S2);
- `UNPAID_ORDER_TTL` (default 24 hours) has passed since the later of the
  order's creation and its last attempt ending.

The job re-checks every condition under the order lock (S5). The cancellation
returns the coupon use (G7) and queues the guaranteed cancellation message
(T2b). N4 monitors the job.
*Why:* an order nobody will pay otherwise never closes, and it holds its
coupon use — against the discount's global limit and the customer's own —
forever.

**S3. All status changes go through `transition_to()`, which validates the
move is legal from the current state.** No code assigns a status directly
(checked statically, W8a). Illegal transitions are rejected and logged.

**S4. Every transition writes an `OrderStatusLog` row**: from, to, trigger,
actor type, actor id, timestamp. Actor type is one of `staff`, `customer`,
`system`, `provider_event`; the id is the user id, job name or
`PaymentEvent` id respectively. Never free text.
*Why:* "who did this" is the first question in every support case and every
dispute, and free text cannot be queried.

**S5. Every transaction acquires row locks in one global order:**

```
payment_event → placement_guard(s) → cart → discount → order → payment(s)
              → reservation(s) → variant(s) → invoice_sequence
```

Tables a transaction does not touch are skipped; the order among those it
does touch never changes. `placement_guard` comes first among the checkout rows
because V8's cap must be decided before anything else is committed to; the
discount counter comes before the order so an
exhausted coupon fails before stock is touched; variants, the most contended
rows, are locked late and held briefly; only `invoice_sequence` follows them
(I1a, I3).

Within a table, rows are locked in ascending primary-key order. All locking
goes through one helper; no service calls `select_for_update()` in its own
order. `transition_to()` locks the order row first and re-reads the current
status inside the same transaction as the write. C7 follows this order.
*Why:* two transactions that lock the same rows in opposite orders each hold
what the other needs. PostgreSQL detects the deadlock and kills one of them —
a random failure that appears only under real traffic. One fixed order makes
the cycle impossible. Re-reading under the lock stops two concurrent events
both finding the same move legal and both writing.

**S6. Fulfilment status has exactly one computing path:
`recalculate_fulfillment()`, which runs in the same transaction as any change
to shipped, cancelled or returned quantity, computes the target from S1's
derivation table, and applies it by calling `transition_to()`.**
It is never assigned directly, and can never be supplied by an API client,
admin form, serializer, import or background job. The `OrderStatusLog` actor
is `system`, with the causing shipment, cancellation or return id as the
trigger.
*Why:* derivation and validation are not alternatives. The quantities are the
single source of truth for the value; `transition_to()` remains the single
path that writes it, so S3's guarantee and S4's log hold for fulfilment as
they do for payment.

**S7. `OrderItem` carries three denormalized quantity columns** —
`shipped_quantity`, `cancelled_quantity`, `returned_quantity` — each written
under `select_for_update`, with row-level checks:

```
CHECK (shipped_quantity + cancelled_quantity <= quantity)
CHECK (returned_quantity <= shipped_quantity)
```

**S8. Each shipment has its own delivery status:**

| From | To | Recorded by |
|---|---|---|
| `shipped` | `delivered` | admin from the courier's report, or a carrier adapter |
| `shipped` | `delivery_failed` | same — customer unreachable, may be reattempted |
| `delivery_failed` | `shipped` | reattempt |
| `shipped`, `delivery_failed` | `refused` | same — customer refused at the door |
| `refused` | `received_back` | **warehouse staff, on physical receipt** |

- **`refused` moves nothing.** No stock, no money — the goods are in transit
  back.
- **`received_back` is the trigger**: `returned_quantity` incremented (S7), the
  restock decision (R3), and a `refused_delivery` adjustment (O10) removing
  the refused lines from the effective total. Fulfilment is recalculated (S6).
- **`delivered_at` starts the return window** (R7) and is dispute evidence (R6).

**Ship-before-payment refusals (COD):**
- `COD_PARTIAL_ACCEPTANCE` (default **off**): when off, the customer accepts
  or refuses the whole shipment. When on, the courier may report refusal of
  specific items, and only those follow the path above.
- `COD_REFUSAL_SHIPPING_FEE` (default **on**): the `refused_delivery`
  adjustment keeps shipping and its tax in the effective total. If the courier
  collected it, the admin records that cash and payment moves to `paid` (cash
  must equal the effective total; a difference is adjusted first, P13c). If not,
  the admin moves payment to
  `uncollected` once every shipment is `received_back` (S1). The move is an
  admin action, not an automatic consequence of the last receipt.
- **Cash for a refused shipment is recorded after the adjustment, not before.**
  The `refused_delivery` adjustment exists only from `received_back`, and S1
  requires recorded cash to equal the effective total — so cash the courier
  collected at the door is recorded once the goods are back and the adjustment
  is applied, and the order stays `unpaid` until then. Under
  `COD_PARTIAL_ACCEPTANCE` this delays recording real cash, and the invoice
  that follows it (I1a), for as long as the return leg takes. That is a stated
  consequence of the exact-cash rule, not an oversight.
- Both settings are read from the order's copy (F1b).
*Why:* the courier reports what happened at the door; only the warehouse knows
what came back and in what condition. Stock and money follow the goods, not
the report. And a store that later collects the money another way must not be
locked out of a terminal status by a job.

**S9. The API exposes a computed `display_status`** for frontends, from one
table in core — first match wins. It is never stored and never accepted as
input.

| Condition | `display_status` |
|---|---|
| `cancelled_at` set | `cancelled` |
| payment `payment_review` | `on_hold` |
| payment `uncollected` | `not_delivered` |
| payment `refunded` or `charged_back` | `refunded` |
| fulfilment `returned` | `returned` |
| fulfilment `partially_returned` | `partially_returned` |
| fulfilment `fulfilled`, every shipment `delivered` | `delivered` |
| fulfilment `fulfilled` | `shipped` |
| fulfilment `partially_fulfilled` | `partially_shipped` |
| payment `failed` | `payment_failed` |
| payment `unpaid` or `pending`, not ship-before-payment | `awaiting_payment` |
| payment `partially_refunded` | `partially_refunded` |
| otherwise | `processing` |

`partially_refunded` sits this low deliberately: a goodwill refund on a
delivered order must still read `delivered`, while an unshipped partly-refunded
order has nothing better to say than `processing` without it. A *full* refund
still outranks fulfilment, as it always has.

Codes are part of the public API (X8); labels are translated (L4).
*Why:* without it, every client's frontend developer combines two statuses
and a timestamp their own way, and they disagree with the admin and with each
other.

---

## 4. Payments

### Authenticity

**P1. A payment moves to `paid` only through an authenticated provider
confirmation.** There are exactly four:
1. A signature-verified webhook.
2. A provider API reconciliation result that independently verifies payment
   identity, amount, currency and legal transition (see P15).
3. An authenticated, permission-gated admin action recording an offline
   payment as received, **only for payment methods registered as
   admin-confirmed** (S1a). In v1 that is COD alone.
4. The system, in the order-commit transaction, **only for a `zero_total`
   order** (S1c) — its total is 0, so there is nothing to confirm.

A browser redirect is never one of them.

**P1a. Returning from the provider may trigger an immediate status check.**
When the customer lands back on the frontend, the API may query the provider
for that attempt — path 2 above, server to server with our credentials. The
redirect's parameters only identify **which** attempt to check; nothing in
them is believed. The check:
- is allowed only to the order's owner or a valid guest token (A6, A8);
- is rate-limited per order and per IP (A9);
- runs outside any transaction with an explicit timeout (T1, T4);
- applies its result through the **same function and locks as the webhook**,
  so whichever of the two arrives second is a no-op;
- leaves the attempt `pending` on any ambiguous answer (P15); the frontend
  keeps polling.
*Why:* webhooks can lag by minutes. A customer staring at "processing…" pays
again or calls support. Correctness does not depend on this check; speed
does.

**P2. Webhook signature verification happens before anything else.**
Unverified → 401, nothing written.

**P2a. Each provider may have two active signing secrets during a rotation
window.** Verification tries the current secret, then the previous one until
the window closes. The window is configured, and the previous secret is
removed when it ends.
*Why:* changing a secret with a hard cut-over rejects every event signed in
between, and those are payments.

**P2b. Live and test mode are never mixed.** A deployment configured as live
refuses to boot with test-mode provider keys, and an event whose live/test
flag does not match the deployment is rejected before processing.
*Why:* a staging webhook pointed at production must not be able to mark a
real order paid.

**P3. Signature verification reads the raw request body, byte for byte.** The
event id is extracted by parsing a **copy**; the original bytes are stored
unmodified.
*Why:* Django parses the body before the view runs, and reserialization changes
the bytes so the signature can never match.

**P4. Replay protection uses a clock-skew window applied in both directions.**
Timestamps too old *or* excessively future-dated are rejected before
processing.

### Event processing

**P5. Webhook handling is two separate transactions, in this order.**

1. **Receipt.** Insert `PaymentEvent` — raw body, provider, event id,
   `processed_at = NULL` — and **commit**. Unique on
   `(provider, provider_event_id)`.
2. **Processing.** In a second transaction, apply the domain transition and
   set `processed_at`. Both or neither.

An event with `processed_at IS NULL` is unprocessed and eligible for
reprocessing (P6). A duplicate delivery whose row already has `processed_at`
set performs no side effect.

*Why:* deduplicating on *seen* rather than *processed* is what loses payments —
crash after the insert and the retry is skipped forever. Once `processed_at`
exists, insert-then-act is safe and correct. Putting both in one transaction
reintroduces the hole from the other side: X12's transient-failure path returns
500, which rolls back, taking the receipt with it.

**P5a. Processing locks the event row and re-checks `processed_at` under the
lock** before doing anything, following the global lock order (S5) with the
event row first.
*Why:* a provider retry, the replay command (P6) and a return-page check (P1a)
can all try to process the same event at once.

**P5b. Every processed event records an outcome and a reason:**

| Outcome | Meaning |
|---|---|
| `applied` | a legal transition was applied |
| `no_op` | valid, but nothing to change (already in that state, or an event type the adapter declares ignored, P7) |
| `ignored_illegal` | the transition is illegal from the current state (P8) |
| `unprocessable` | cannot be matched or understood (P5c, P7) |

`ignored_illegal` and `unprocessable` raise an alert (N5).

**P5c. An event for a payment we do not know is stored, marked
`unprocessable`, answered with 200, and alerts.** It is never dropped and
never creates a payment.

**P6. Unprocessed events have an operator replay path.**
A management command and an admin action re-drive events with
`processed_at IS NULL`, and a monitored job reports any older than a
threshold.
*Why:* X12 answers a valid-but-unprocessable event with 200, so the provider
stops retrying. Without a replay path those events rot in a table behind an
alert nobody can act on.

**P7. Each provider event type maps to an explicit domain transition and
explicit side effects.** Unknown, unsupported or ambiguous event types never
mutate payment state. Each adapter declares the event types it knowingly
ignores; those record `no_op` (P5b) and do not alert. Any other type the
adapter does not map records `unprocessable` and alerts (X12).
*Why:* providers send many event types a store never acts on; alerting on each
buries the alerts that matter. An undeclared type is different — it may be a
payment event the adapter was never taught.

**P8. Out-of-order events are resolved by legal state transitions and provider
event metadata, never by timestamp comparison alone.** An event that
contradicts a terminal state — `failed` arriving after `paid` — is recorded as
`ignored_illegal` (P5b), changes nothing, and alerts.

**P9. `PaymentEvent` raw bodies are stored in access-controlled storage with
defined retention (I8a).** Never exposed through API serialization, application
logs or client-facing errors.
*Why:* "append-only" must not become "readable by everyone forever." Provider
payloads carry customer and payment metadata.

### Amounts

**P10. No payment attempt is ever committed before its order.** An online
attempt is created after the order row is committed; an admin-confirmed
method's row is created inside the order-commit transaction itself (P13b),
which cannot outlive a rollback either. The
payment attempt's expected amount and currency are copied from the committed
order, or — for a difference payment — from the applied-pending
`OrderAdjustment` it pays for (O11), and are immutable thereafter (frozen by
grant, D7a). **The attempt names which of the two payables it pays for** (P13a),
frozen with them. Never sourced from client input or provider-returned values.
*Why:* if a payment can succeed against an order that was never durably
written, the customer is charged with no record connecting them to the money.
The order is the anchor; the payment references it, never the reverse.

**P11. Before a payment moves to `paid`, the event's amount and currency must
equal the payment's expected amount and currency.** A mismatch goes to
`payment_review`.
*Why:* a signature proves the event came from the provider, not that the
customer paid what was owed. And P11 is only meaningful because P10 gives the
expected amount a trusted source.

**P12. Total successfully captured amount for an order may never exceed the
order's payable total.** Where multiple attempts are possible, the aggregate
is checked and consumed atomically.
*Why:* several individually valid payments must not collectively overpay.

**P13. A `Payment` is one attempt. An order may have several.** Each attempt
has its own status, separate from the order's:

| From | To | Trigger |
|---|---|---|
| `created` | `requires_action`, `pending` | provider session opened |
| `created` | `failed` | definitive rejection of session creation (below) |
| `requires_action` | `pending` | customer completed 3-D Secure or a wallet approval |
| `pending`, `requires_action` | `succeeded`, `failed` | authenticated result (P1) |
| `created` | `succeeded` | the P1 path-3 admin confirmation — admin-confirmed methods only (P13b) |
| `created`, `pending`, `requires_action` | `expired` | authenticated session-expiry event, or reconciliation |
| `created`, `pending`, `requires_action` | `cancelled` | superseded (P13a), cancelled at the provider, or — for an admin-confirmed method — the order cancelled or ended `uncollected` (P13b) |
| `expired`, `cancelled` | `succeeded` | authenticated capture that arrived anyway — **the order goes to `payment_review`** (P13a) |

A timeout is none of these: the attempt stays where it is until
reconciliation resolves it (P15). When the order's only active attempt **for its
own total** ends `expired` or `cancelled`, the order moves `pending → unpaid`
(S1) and its reservations are released (C4a). An attempt on an adjustment
payable (P13a) never stands in for that one: counting it would leave an order
whose own session expired sitting in `pending` for ever, holding reservations
nothing releases and outside S2b's reach.

**Definitive rejection** is declared per adapter: the provider responses that
prove no session exists, such as a validation error. Anything the adapter does
not declare definitive is ambiguous (P15) and leaves the attempt in `created`
for reconciliation (T6).

**P13a. An order has at most one active attempt per payable.** A **payable** is
either the order's own total or one `OrderAdjustment` awaiting payment (O11);
every attempt names the payable it pays for, which is where its expected amount
was copied from (P10). A request to pay a payable while an attempt on **that
same payable** is active:
1. **Reuses** it — returns the same provider session — when it is still live
   for the same amount and method, and its provider is enabled (N2). No new
   attempt, nothing to pay twice.
2. Otherwise **cancels** it at the provider, then creates a new attempt.
   Whether a provider can cancel a session is a declared adapter capability;
   the cancel call runs outside any transaction (T1).
3. A capture that still arrives on a superseded attempt moves the order to
   `payment_review`. An admin resolves it — typically a one-click refund of
   the duplicate. **Nothing refunds automatically.**

Two partial unique constraints enforce it (D5): one over the order for attempts
with no adjustment, one over the adjustment for difference payments — a unique
index treats NULLs as distinct, so a single constraint cannot cover both. **At
most one `OrderAdjustment` per order is in `awaiting_payment`** (D5, O11), so an
order never carries more than two live payment pages, each for a different
amount it genuinely owes. Reservations carry across attempts as C2 and C2b
describe; an adjustment's attempt takes none (C2).
*Why:* two open payment pages for the *same* money is how a customer gets
charged twice. Reuse removes the second page; cancellation covers the rest;
review catches what cancellation cannot, with a human deciding every refund so a
second glitch cannot fire refunds in a loop. Scoped to the order rather than the
payable, the constraint would refuse O11's difference payment on any order whose
own attempt is still live — and item 2 would then cancel the customer's main
payment page to open the delta page, and cancel the delta page again on the next
retry of the main one, so neither could ever be paid and the order would die at
`UNPAID_ORDER_TTL` (S2b) owing money it was never able to take.

**P13b. An admin-confirmed method creates its `Payment` row in the
order-commit transaction.** COD is the only one in v1 (S1a). Without a row, the
order-level aggregates in S1 sum to zero, M13's ceilings have no `paid_amount`
to bound, and a refund (R1, R2b) has no payment to attach to.

- The row is created **in the same transaction as the order**, never before it,
  with status `created`, the expected amount and currency copied from the order
  being committed (P10), and **no provider idempotency key** — P14 governs
  provider calls, and an admin-confirmed method makes none.
- It stays `created` while the order is `unpaid`. **It is not an online
  attempt:** it opens no provider session, so it triggers no `unpaid → pending`
  transition (S1), reconciliation never polls it (T6), and it takes no
  reservation of its own — its stock was allocated at commit (C2a).
- The P1 path-3 admin confirmation moves it `created → succeeded` and writes
  `paid_amount` from the cash recorded, in the same transaction as the order's
  `unpaid → paid` (S1). **What the cash must equal is the order's effective
  total at collection** (S1, O10), not the expected amount copied at commit —
  which on an admin-confirmed row is a record of the total at commit and
  nothing more. P11 governs provider events and does not apply here.
- Cancelling the order, or ending it `uncollected` (S8), moves the row
  `created → cancelled`.
- Its `FraudAssessment` (V7) hangs on this row, so "one per attempt" is uniform
  across every method that has one (D5).
- It is the attempt for the order's own total, so P13a's constraint over that
  payable counts it. Nothing collides with it, because P13a's reuse-then-cancel
  path is about **provider** sessions and an order on an admin-confirmed method
  has no pay endpoint: its money arrives through P1 path 3. An O11 difference on
  such an order is collected by the admin, not by an attempt (O11's
  admin-confirmed column), so its adjustment payable never takes a row either.

*Why:* every rule about money out — the refund ceiling (M13), the refundable
balance (R1a), the review-exit aggregates (S1) — is written against `Payment`.
A method with no row is invisible to all of them: a COD order would read
`paid_total == 0` forever and could not carry a refund at all. COD is the
method this product was built for, so it cannot be the one the money model
cannot see.

**P13c. Where the cash actually collected differs from the effective total, the
difference is recorded as a `collection_adjustment` before the cash is.** S1
requires recorded cash to equal the effective total exactly, and an
admin-confirmed collection is the one place where the amount is decided outside
this system: a courier keeps the change, rounds to the nearest note, or hands
over short.

- It is an `OrderAdjustment` of type `collection_adjustment` (O10), applied
  immediately, by a staff user holding `collect_cash` (A6a), with a required
  reason. Its delta may be negative (short) or positive (over), and may not take
  the effective total below 0 (G3).
- It moves no stock and returns no coupon use (G7): the goods were delivered
  under the order's own terms.
- **It is never allocated to lines and never refunded on its own.** A refund's
  allocation (R2b) covers the effective per-line and shipping values; where a
  refund covers the whole effective total of an order carrying a
  `collection_difference`, that difference appears as its own line on the refund
  and on the credit note, exactly as a return fee does, so the document sums to
  the amount actually refunded. Without that line the credit note's lines sum to
  one number and the refund to another, and the M9/M11 assertion across the
  split (R1c) fails on a refund that is otherwise entirely correct.
- It issues a note only where an invoice already exists (O10). On the default
  issuance trigger none does — the invoice is issued by the same transaction
  that records the cash (I1a) — so the invoice carries the amount actually
  collected.
- **Admin-confirmed methods only.** Where a provider states the amount, a
  mismatch is P11's `payment_review`, not an adjustment.

*Why:* exact cash is the right rule — it is what makes `paid_amount` trustworthy
on a method with no provider to check it. But without a path for the difference
the rule has no exit: the order cannot reach `paid`, because the cash does not
equal the total, and it cannot reach `uncollected` either, because that requires
that nothing was collected (S1, S8). It stays `unpaid` for ever, real money sits
off the books, and no invoice is ever issued for a delivered sale (I1a). In a
COD-heavy market a one-unit rounding difference is an ordinary day, not an edge
case.

### Outbound calls

**P14. Every charge has one stable provider idempotency key permanently bound
to exactly one `Payment` attempt.** Every retry of that attempt reuses the
same key; a new attempt gets a new one. The same rule applies to refunds, each
bound to one internal refund id. The attempt's key also covers session
creation, so a retried session call cannot open a second payment page. The row
carrying a key is committed before the call it guards (T1).
*Why:* generating a fresh key per retry defeats provider-side idempotency
entirely and is how a timeout becomes a double charge.

**P15. A timeout or ambiguous provider response never means `failed`.** The
operation stays unresolved until reconciliation determines the outcome.
Reconciliation results have explicit semantics for `paid`, `failed`,
`pending`, `not_found`, `unauthorized` and transient errors. No ambiguous or
transient response moves a payment to a terminal state:

| Result | Effect on an attempt |
|---|---|
| `paid` | applied through the same function and locks as the webhook (P1a) |
| `failed` | `failed` |
| `pending` | no change |
| `not_found` | no change before session expiry plus grace (C2b); `expired` after it |
| `unauthorized` | no change; alerts |
| transient error | no change; retried next cycle |

Refunds follow the same table, except `not_found`: a refund in `requested`
that was never sent is sent under its existing key (P14); a refund in `sent`
that the provider cannot find alerts and changes nothing.
*Why:* the provider may have charged the customer even when our request timed
out. Reconciliation exists to resolve uncertainty, not manufacture certainty.

**P16. When the outcome cannot be determined, the state is `payment_review`.**
A human resolves it; nothing auto-fulfils.

**P17. The domain never imports a payment provider.** All providers implement
the same port interface.

**P18. Card data never touches this system.** No PAN, CVV or expiry accepted,
stored, logged or proxied. Card entry happens only on the provider's hosted
page or the provider's embedded fields. **The client's frontend never renders
its own card form** — this is stated in the buyer docs and the setup guide,
because the frontend is where this rule is actually broken.
*Why:* handling card data pulls the system into PCI-DSS scope — and a custom
card form on the client's site pulls the client in, whatever the backend does.

---

## 5. Refunds, returns and disputes

### Refunds

**R1. A refund has a closed lifecycle:**

| From | To | Trigger |
|---|---|---|
| — | `pending_approval` | admin action, when R1b is on and the amount is above `REFUND_SECOND_APPROVAL_THRESHOLD` |
| — | `requested` | admin action below the threshold or with R1b off, or the system under C6a |
| `pending_approval` | `requested` | approved by a **different** staff user holding `approve_refund` (R1b) |
| `pending_approval` | `rejected` | the approver declines, with a recorded reason |
| `requested` | `sent` | provider call committed (P14 key), or admin begins an offline payout |
| `sent` | `refunded` | authenticated confirmation (below) |
| `requested`, `sent` | `refund_failed` | authenticated failure |
| `refunded` | `refund_failed` | provider reports the refund reversed after success |

`rejected` is terminal: a refund that should still happen is requested afresh.

The admin action is authorized as A6a describes: `request_refund` for an
amount staff choose, or the permission of the cancellation or return that
computes it.

**Confirmation** follows the payment's method (S1a):
- **Provider-confirmed methods:** an authenticated provider confirmation
  (P1, paths 1–2).
- **Admin-confirmed methods (COD):** a permission-gated admin action recording
  the payout method (cash, bank transfer, wallet) and a reference.

`refunded_amount` increases **only** on `refunded`, and decreases when a
confirmed refund is reversed. Both happen in the same transaction as the
status change, under the payment lock (S5).

**R1a. The refundable balance counts refunds in progress:**

```
refundable = paid_amount - refunded_amount - disputed_amount
             - sum(refunds in pending_approval, requested or sent)
```

Read, checked and consumed under the payment lock (M15). A request exceeding
it raises `RefundExceedsPaid`.
*Why:* without the in-progress term, two refunds can both be requested before
either is confirmed, each passing against a balance that ignores the other.
And without `pending_approval` in that term, two large refunds can both sit
awaiting approval against a balance that covers only one, and the second
passes R1a at request time and fails at approval time — after a second staff
member has already approved it.

**R1b. Second approval for large refunds is a per-deployment option, off by
default.** When on, a refund above `REFUND_SECOND_APPROVAL_THRESHOLD` stays
`pending_approval` until a **different** staff user with the approval
permission approves it; only then does it become `requested`. Both users are
recorded. It applies to cancellation and return refunds as well as
discretionary ones. System refunds under C6a are exempt: their amount is the
refundable balance of a provider-confirmed capture, chosen by nobody.
*Why:* it limits what one compromised or dishonest staff account can pay out.

**R1c. A refund computed from order values is split across the order's
successful payments.** Cancellations (S2, S2a), returns (R8), automatic
resolution (C6a) and a negative adjustment (O11) each produce one order-level
amount, while every ceiling and balance is per payment (M13, M15, R1a) — and an
order may hold several successful payments: the original and O11 top-ups (S1).

- The amount is consumed against the order's successful payments, **most recent
  capture first** (ties broken by payment id, descending), each portion capped
  by that payment's refundable balance (R1a). One `Refund` row is created per
  payment that contributes, all in the same transaction, with every payment row
  locked first in S5 order.
- The rows created together share a `refund_group` identifier — a random public
  id (Q3a), because documents, messages and the API name it. **The group is the
  event.** The named permission (A6a), the
  second approval (R1b), the document and the message below are per group; the
  provider call, the P14 key and the R1 lifecycle stay per row, so one payment's
  refund may fail (R2) without reversing the other, and R1b's threshold is
  measured against the event total. Unique on (group, payment) (D5). A refund
  against a single payment is a group of one: there is no second shape. The
  identifier is a reference target like any other — the credit note and the
  notification name it by id (I2, T2b), and at most one note per group is a
  constraint (D5).
- If the order-level amount exceeds the sum of those balances, nothing is
  created and `RefundExceedsPaid` is raised (X5a). A payment with an open
  dispute contributes nothing (R2c); where the rest cannot cover the event it
  raises `dispute_open` instead, because that money is not missing, it is
  frozen.
- Deductions (R2b) are taken from the event total before the split; each row
  then carries its share of them and its own per-line allocation of its own
  portion (M8), and the document renders the group's sums, so M9 and M11 hold
  across the split.
- **One document per event, issued by the event.** Where the refund pays out an
  applied `OrderAdjustment` — item cancellation (S2a), refused delivery (S8), a
  negative address-change delta (O11) — the adjustment issues the note (O10) and
  the refund issues none. Where no adjustment exists — a return (R8), a
  whole-order cancellation, a goodwill refund — the group issues one credit note
  (I2), whatever the split. Money already credited by a note is never credited
  by a second one.
- The guaranteed "refund completed" message (T2b) is written per group, in the
  transaction where the group's last row leaves the in-progress states
  (`pending_approval`, `requested`, `sent`), and states the amount actually
  refunded. Its trigger is the group, so a split cannot send two. A group where
  nothing refunded sends nothing and alerts instead (R2); a reversal after a
  group's message (`refunded → refund_failed`, R1) is its own alert, not a
  second message.
- Where the order has **no successful payment**, the refund step does nothing
  (S2). That test is the absence of a successful payment, never the method code
  (S1a): a `zero_total` order that took an O11 top-up has one, and that money is
  refundable like any other.

*Why:* every rule that causes a refund names an order-level amount and every
rule that bounds one names a payment. With no stated split, the obvious
implementation refunds against one payment — silently keeping an O11 top-up the
customer paid, or raising `RefundExceedsPaid` on a legitimate cancellation.

**R2. `refund_failed` always alerts.** It never silently stays `requested` or
`sent`. A reversal after `refunded` means the customer does not have their
money; the alert says so.

**R2a. Provider refunds go only to the original payment.** Never to a
different card, account or wallet. Store credit is out of v1.
*Why:* refunding to a different instrument is a standard money-laundering and
fraud pattern, and most providers forbid it.

**R2b. Every refund is allocated across lines and shipping**, so the credit
note for it carries per-line tax (I2, I4). Which document carries it — the
adjustment's note or the refund group's — is R1c, and no refund issues a second
note for money a note already credited. A refund of specific items uses their
stored values (S2a); an arbitrary goodwill amount is allocated by largest
remainder (M8). Return fees (R7) appear as explicit deduction lines on the
refund and the credit note, never netted silently.

`Refund.amount` is what the customer receives — net of deductions. The
deductions are recorded alongside it and appear as their own lines on the
refund and the credit note; the gross the return entitled the customer to is
the sum of the two. M13's ceiling and R1a's balance operate on the net
amount, because they measure money that left.

**R2c. No refund is created while a dispute is open on that payment.**
*Why:* refunding and then losing the dispute pays the customer twice.

**R3. Restock is a separate decision from refund.** Explicit flag on the
return, defaulting to off.
*Why:* damaged goods are refunded but not resold; a goodwill refund may have
no return at all.

### Disputes

**R4. Disputes and chargebacks are modelled.** `Dispute`: payment, provider
reference, amount, reason, status, `evidence_due_by`, opened_at, resolved_at.
A dispute never mutates `paid` directly; opening one transitions the order to
`payment_review` (S1).

| From | To |
|---|---|
| — | `inquiry`, `needs_response` |
| `inquiry` | `needs_response`, `closed` |
| `needs_response` | `under_review`, `accepted` |
| `under_review` | `won`, `lost` |

`accepted` means the merchant chose not to contest. An alert fires
`DISPUTE_DEADLINE_WARNING` before `evidence_due_by` for any dispute still in
`needs_response`.
*Why:* a chargeback is money leaving weeks later with no store action. A
missed evidence deadline loses by default.

**R5. `disputed_amount` changes only when the provider moves money** — it
increases when funds are withdrawn and decreases when they are reinstated
(typically on `won`). A dispute that moves no money (`inquiry`) changes no
balance. `dispute_fee_amount` is recorded when charged and reversed only when
the provider reports it reversed. Disputed amounts and fees are never folded
into `refunded_amount` (M13), and a dispute never raises or lowers the refund
ceiling except through R1a. A reinstatement on an order that already left
review as `charged_back` re-enters review (S1).
*Why:* a chargeback and a refund are different events with different causes,
and money out can legitimately exceed money in once both are counted. The
balance must follow the money, not the paperwork.

**R6. Dispute evidence is captured at order time, not at dispute time.**
Stored on the order: IP address, user agent, device/session fingerprint,
checkout timestamps, the exact totals shown at checkout and the quote hash
they were approved under (M6a), the shipping address as entered, **the version
of the terms and refund policy accepted at checkout**, delivery confirmation
and carrier tracking, the guest-token access log, and a log of customer
communications about the order (the notification rows, T2b).
*Why:* a chargeback arrives weeks later with a 7–14 day response window, and
none of this can be reconstructed afterwards. Banks ask whether the customer
agreed to the policy; without the accepted version, there is no answer.
Losing costs the money *and* the ratio damage that feeds section 14.

### Returns

**R7. Returns follow per-deployment return rules** (the merchant's policy, as
Shopify does): return window (default 14 days from `delivered_at`, S8),
final-sale categories, return shipping fee, restocking fee. v1 has one set of
rules per deployment. The rules in force at commit are copied onto the order
(F1b), and eligibility is judged against that copy.

- A request outside the rules is rejected, unless an admin records a goodwill
  override with a reason.
- A request inside the rules is approved or declined by an admin, with a
  recorded reason. There is no customer returns portal in v1; requests are
  recorded by staff.
- The deployment may set a `LEGAL_RETURN_WINDOW`. Declining inside it is
  allowed but shows a warning in the admin and is recorded as acknowledged.
- Nothing moves on approval. Stock (R3), `returned_quantity` (S7), refund and
  credit note happen when the goods are received and inspected.
*Why:* the backend is the merchant's tool and consumer law is the merchant's
responsibility — but the tool must make the legal position visible at the
moment of the decision, and leave a record of it.

**R8. `ReturnRequest` has a closed lifecycle:**

| From | To | Trigger |
|---|---|---|
| — | `requested` | staff records the customer's request, per item and quantity |
| `requested` | `approved`, `declined` | admin decision with reason (R7) |
| `approved` | `received` | warehouse receipt |
| `approved` | `expired` | goods not received within `RETURN_SHIP_BACK_WINDOW` |
| `received` | `inspected` | inspection recorded: condition, restock decision (R3) |
| `inspected` | `closed` | refund issued (R1) and credit note issued |

Requested quantity per line may not exceed `returned`-eligible quantity
(delivered minus already returned or in an open return).

---

## 6. Stock and concurrency

### Stock

**C1. Any bounded counter is checked and decremented in one atomic
operation.** Stock, coupon usage limits, per-customer redemption limits, and
any other quantity with a ceiling. `select_for_update()` inside
`transaction.atomic()`, or a conditional `UPDATE ... WHERE counter >= n` whose
affected-row count is checked. Read-then-write in two steps is forbidden.

The conditional `UPDATE` is valid only when the whole ceiling lives in the
updated row, as with coupon counters. Stock availability depends on the
`Reservation` table (C3), so reserving and allocating stock always lock the
variant rows (S5) and compute availability under that lock.

**C1a. `variant.stock` is never negative.** `CHECK (stock >= 0)`. Backorders
are out of v1: a variant with no available stock cannot be reserved or
allocated.
*Why:* a backordered unit has no allocation, so C6 blocks its fulfilment
forever. Making it work needs a waiting state, an order for handing out
restocked units, and a never-restocked path — none of it designed. Adding the
flag later is a backwards-compatible column.

**C1b. A variant with `track_inventory = false` is never counted.** It takes
no reservation, writes no `StockMovement`, and counts as allocated for C6.
Switching it to `true` sets the starting count through the stock service as an
`initial` movement (C8a), never a direct edit.

### Reservations

**C2. Stock is reserved at payment start, not at add-to-cart.** The
reservation is created in the same transaction as the attempt's `Payment` row
in `created`, before any provider call (T1). If any line lacks available
stock, the transaction raises `OutOfStock` and no provider session is opened.

This rule is about provider-confirmed attempts. Admin-confirmed methods
(P13b) and `zero_total` orders take no reservation of this kind: their stock is
allocated when the order is committed (C2a, S1c).

A reservation belongs to the order, not the attempt: a superseding attempt
(P13a) carries the order's active reservations over instead of releasing and
re-reserving them. Payments for an order adjustment (O11) take no
reservation — their stock is already consumed.
*Why:* reserving at cart locks inventory for abandoned carts. Reserving after
the provider call opens a payment page for stock that may not exist.

**C2a. Ship-before-payment orders (COD) are allocated when the order is
committed** — in the same transaction that creates the order, through
`allocate_order()` (C4b). If stock is unavailable, no order is created and
`OutOfStock` is raised. COD has no payment start and its confirmation arrives
after delivery, so no expiry can cover it. Cancellation or refused delivery
returns the stock through the stock service. COD placement is subject to the
abuse controls in V8.
*Why:* a COD order ships before payment (S1). Without an allocation at
placement, C6's "no fulfilment without verified stock allocation" cannot be
satisfied, and a short hold would expire days before the cash arrives.

**C2b. A reservation expires with its attempt's provider session, plus a
grace period.**

```
session_expires_at     = attempt created_at + CHECKOUT_SESSION_TTL
reservation.expires_at = session_expires_at + RESERVATION_GRACE
```

The payment adapter sets the provider session's expiry to
`session_expires_at`. Each adapter declares the range of session expiries its
provider accepts. **The app raises at boot if `CHECKOUT_SESSION_TTL` is
outside the range of any enabled provider**, or if a provider cannot set a
session expiry at all. Defaults: `CHECKOUT_SESSION_TTL` 30 minutes,
`RESERVATION_GRACE` 10 minutes.

- **Reuse** (P13a, item 1): same session, so neither clock changes.
- **New attempt** (P13a, item 2): the carried reservations reset to the new
  session's expiry plus grace, in the transaction that creates the attempt.

*Why:* a reservation shorter than its payment session manufactures C5 reviews
on every slow checkout. Tied together, a capture can arrive after expiry only
through confirmation lag longer than the grace period.

**C3. Available stock is always computed, never stored:**

```
available = stock - sum(qty of reservations
                        where status = active and expires_at > now())
```

A reservation stops holding stock the moment `expires_at` passes, whether or
not the release job has marked it `expired` yet. Reservations carry a partial
index on `variant` where `status = active`.
*Why:* two columns that must agree will eventually disagree. And a lagging
release job must not hold stock.

**C4. A reservation is consumed, not released, on payment success.** In one
transaction: reservation → `consumed`, `variant.stock` decremented,
`StockMovement` written. Consumption re-checks under the lock that the
reservation is `active` **and** `expires_at > now()`, and that `stock` covers
it; otherwise C5 or C9a applies.
*Why:* this seam is exactly where overselling lives.

**C4a. An active reservation ends in exactly one of four ways:**

| Event | Reservation | When |
|---|---|---|
| Authenticated payment success (P1) | `consumed` (C4) | same transaction as the `paid` transition |
| Authenticated payment failure (P1), or definitive session-creation rejection (P13) | `released` | same transaction as `pending → failed` |
| The order's only active attempt **for its own total** ends `expired` or `cancelled`, with no replacement | `released` | same transaction as `pending → unpaid` (S1, P13) |
| `expires_at` passes | `expired` | the release job, which N4 monitors |

A superseded attempt is not an ending: its reservations carry over to the new
attempt (C2). A timeout or ambiguous provider response is **not** a failure
(P15): the reservation stays active until it is consumed or expires, and a
success that arrives after expiry goes to review (C5). A new attempt after
`failed` takes a new reservation.
*Why:* releasing on a timeout frees stock the customer may already have paid
for; not releasing on a confirmed failure or an abandoned checkout holds stock
for a payment that is known to be dead.

**C4b. `allocate_order()` is the only path that allocates stock outside a
normal payment success.** Under the S5 locks, for every tracked line (C1b)
with `quantity - cancelled_quantity > 0`, it checks availability (C3) for that
quantity, then creates a `consumed` reservation, decrements `variant.stock`
and writes the `StockMovement`. **All lines or none:** if any line is short,
nothing is allocated and `OutOfStock` is raised naming the short lines **by the
public id the caller addressed them under** — cart lines at checkout, where the
transaction rolls back and its order items never existed for the client, and
order items on every later call (Q3a, X7).

Callers: COD placement (C2a), zero-total placement (S1c), leaving review (C6),
automatic resolution (C6a).

A **verified stock allocation** means every tracked line has consumed
reservations equal to `quantity - cancelled_quantity`. This is what C6 and
S1's fulfilment guard check.

**A cancellation reduces the line's consumed reservation.** When a cancellation
returns stock (S2, S2a), the stock service reduces that line's consumed
reservation quantity by the cancelled quantity, in the same transaction as its
`cancellation_return` movement, so the equality above holds by construction. A
reservation reduced to zero stays `consumed` with quantity 0; the ledger (C8)
is the record of what moved. Returns and refused deliveries do **not** change
it — the guard gates *entry* into fulfilment, which those lines have already
passed.
*Why:* without this, cancelling one unit of a three-unit line leaves a consumed
reservation for three against a required two, and the line never passes the
fulfilment guard again — the remaining units become unshippable.

### Stock and payment diverging

**C5. A payment succeeding after its reservation expired never silently
consumes stock.** The order enters `payment_review` with an
`allocation_failed` review case (S1b). Stock is taken only through
`allocate_order()`, logged and alerted — by staff, or by the system under C6a.

**C6. A paid order never enters fulfilment without a verified stock
allocation (C4b).** An `allocation_failed` case is resolved by one of:

- **Allocate** — `allocate_order()`; the case resolves and the order leaves
  review in the same transaction (S1b).
- **Cancel and refund** — the whole order or specific lines, from review
  (S2, S2a); the refund follows R1. Remaining lines may then be allocated.

Staff choose, or the system under C6a. Partial availability — some lines
available, others not — is always a staff decision.
*Why:* payment success and stock availability can diverge. Neither the money
nor the inventory may silently disappear.

**C6a. Automatic resolution — `AUTO_RESOLVE_UNFULFILLABLE`, default on.** When
an `allocation_failed` case opens and the setting is on, the system resolves
it, in a job enqueued on commit (T2), only if all hold:

- it is the order's only open review case (S1b);
- the capture passed P11;
- no dispute is open on the payment (R2c).

Then:

1. **Allocate first.** Call `allocate_order()`. On success the case resolves
   and the order leaves review.
2. **Otherwise refund.** If no line can be allocated in full, cancel the whole
   order (S2) and request a refund of the refundable balance (R1, R1c,
   `requested_by = system`, reason `stock_unavailable_after_payment`). If some
   lines can be allocated and others cannot, the case stays open for staff.
3. **At most one system refund per review case and payment**, enforced by a
   unique constraint on (review case, payment) — the amount may split across
   payments (R1c), so the constraint names both. A replayed event, a retried
   job or a duplicate enqueue does nothing.
4. **The customer is notified** of the outcome.
5. A system refund ending `refund_failed` alerts (R2) and leaves the case open
   for staff.

The attempt is recorded on the case as `auto_resolution_attempted_at` (S1b),
so T2a's sweeper can find a case the job never reached.

With the setting off, every `allocation_failed` case waits for staff.
*Why:* a customer who paid and has no goods is a likely chargeback, and
chargebacks feed the section 14 ratios. Unlike P13a's superseded capture, this
condition is checked under a lock and the right outcome is unambiguous.
Allocation is tried first, because refunding a customer whose product is on
the shelf is the worse outcome.

**C6b. An `allocation_failed` case open longer than
`ALLOCATION_REVIEW_ALERT_AFTER` alerts.** A scheduled job checks; N4 monitors
it.
*Why:* the customer's money is held with no goods, and nothing else puts a
deadline on it.

**C7. Reservation expiry, release, allocation and stock adjustment are
serialized against the relevant reservation and variant rows, using the global
lock order in S5.**
*Why:* `atomic()` alone does not stop two transactions making conflicting
decisions about the same reservation, and inconsistent lock order deadlocks.

### The ledger

**C8. `variant.stock` and `StockMovement` are written in the same transaction.
The ledger is authoritative; the integer is a cache of it.** A reconciliation
job (N4) asserts they agree. On any disagreement it alerts and **never
corrects either side**; a human decides which is wrong.
*Why:* two representations are safe only when the relationship is explicit and
checkable. An automatic correction picks a winner without knowing which one
broke.

**C8a. `StockMovement` is typed, never free text.** `reason` is one of
`initial`, `sale`, `cancellation_return`, `return_restock`,
`refused_restock`, `manual_adjustment`. The actor is typed as in S4.

**A movement records its cause by copy, never by foreign key**: a cause type
(`order`, `return`, `shipment`, `none`) and the cause's public identifier —
order number, return or shipment public id (O6, Q3a) — as plain columns.
*Why:* O7 puts `PROTECT` on every foreign key from a ledger row and W8a forbids
`SET_NULL`, so a foreign key here refuses the retention delete of the order
forever — and no role may update a `StockMovement` to clear it (D7, D6), so
"nullable" is a column nothing can ever null. A copied identifier is the same
pattern O1 and O3 already use, and a ledger row is evidence, not a relation.

**The ledger is retained with its variant, not with its cause.** It holds no
personal data (the actor is an internal id, X13a), it is outside the order
aggregate (I8), and it is not pruned while the variant exists, because C8's
reconciliation sums it: deleting any movement makes that sum disagree with
`variant.stock` permanently, which C8 refuses to auto-correct.

**C9. Nothing modifies `variant.stock` except the stock service** — no admin
action, management command, import, signal, migration (D2d) or background job.
Direct ORM assignment outside that service is forbidden (checked statically,
W8a). In the admin, `stock` is
read-only on the variant form; manual changes go through an admin action that
calls the stock service with a required reason (`manual_adjustment`).
*Why:* one bypass makes the ledger incomplete and destroys its audit value.

**C9a. A manual decrease may go below reserved stock, down to 0.** It alerts,
listing the active reservations it leaves uncovered. A later consumption that
finds `stock` below its reservation's quantity does not decrement; the order
enters `payment_review` with an `allocation_failed` case (C5, C6).
*Why:* a physical count is the truth about the shelf. The system accepts it
and routes the paid orders it strands to a decision, instead of failing a
check mid-webhook.

### Idempotency

**C10. Checkout accepts an `Idempotency-Key` and returns the existing order
for a repeated key.** The same key with a different request body is a 409
conflict, not a replay.

The key row is inserted first, under its uniqueness constraint (D5). A
concurrent request with the same key gets 409 `idempotency_in_progress`,
which the client may retry. Keys are kept for `IDEMPOTENCY_KEY_RETENTION` and
pruned by a scheduled job (N4). The app raises at boot if
`IDEMPOTENCY_KEY_RETENTION` is shorter than `CONFIRMATION_TOKEN_TTL` (M6).

**Exception:** a request carrying a valid, unused `confirmation_token` issued
by a `price_changed` rejection (M6) is a new operation and requires a fresh
key. The token is single-use, **cart-scoped** and expiring — there is no order
yet, which is the whole reason M6 issued it — and the server binds it to the
new key on first use. It is a row of its own: cart, the approved quote's hash,
issued_at, expires_at, used_at and the key it was bound to, unique by D5.
*Why:* without this the flow deadlocks — the confirmation is the same logical
operation with a different body, so C10 rejects it forever, and letting the
client mint a new key on its own reopens the double-order hole C10 exists to
close. The server-issued token is what makes the second attempt provably
authorized rather than merely different.

**C10a. An idempotency key row has an explicit lifecycle:
`in_progress → completed | failed`.** The row is inserted and committed before
the operation runs, which is what lets a concurrent request see it and answer
409 `idempotency_in_progress` (C10).

- **`completed`** stores the response. A repeat of the key returns it.
- **`failed`** is written when the operation ends in any error — a domain
  refusal, an infrastructure 503, or a sweeper finding the row abandoned past
  `IDEMPOTENCY_IN_PROGRESS_TTL` (default 5 minutes). **A `failed` key may be
  retried with the same key**, and the retry moves it back to `in_progress`.
- A repeat of an `in_progress` key answers 409 `idempotency_in_progress`.

*Why:* C10's row has to be visible before the work starts, so an operation that
fails leaves a row behind. Without a `failed` state an honest client retrying
after an `out_of_stock` or a lock timeout meets `idempotency_in_progress`
forever, and the only escape is minting a new key — which is the hole C10
exists to close. M6's `confirmation_token` covers the price-change path alone.

**C11. Idempotency key uniqueness is scoped by authenticated principal *and*
operation.** For guests, by the guest identity in C12 and operation.
*Why:* the same string must not collide across unrelated operations or
clients.

**C12. A guest's idempotency identity is the signed cart token.** The server
issues it when the cart is created; keys are scoped by (cart, operation). It
lives as long as the cart. A lost or expired token means a new cart and a new
scope. Checkout on a cart that has already converted returns that cart's
order (C12a). It never relies on IP address.
*Why:* "per session" is not an implementation. The cart is the thing a guest
retries against, and it already exists.

**C12a. A cart converts to at most one order, for every principal — guest and
authenticated alike.** The order stores the cart it was placed from **by copied
public identifier, never by foreign key** (Q3a, as C8a and N5 do) — set at
insert, updatable by no role (D7a) — and **a unique constraint on that column is
what makes the rule true** (D5). A foreign key would put `PROTECT` (O7) between
an order kept for ten years (I8a) and a cart table that has to be prunable, the
same trap the ledger and the alert table were pulled out of. The cart is marked
converted in the same
transaction, under the cart lock (S5, where the cart sits before the discount).
A checkout request on a converted cart creates nothing and returns that cart's
order, whatever `Idempotency-Key` it carries; the client works on a new cart
afterwards.
*Why:* C10's key row is committed *before* the operation and marked `completed`
*after* it, so a worker that dies in between leaves a key the sweeper marks
`failed` — and C10a exists precisely to let a `failed` key be retried. Without
this rule that retry places a second order from the same cart: a second coupon
redemption (G1), a second COD allocation (C2a) and a second shipment, on an
order the customer never placed. The same hole opens with no crash at all, from
two concurrent checkouts carrying two different keys — C10 scopes idempotency
per key, so it never compares them. The cart is the one fact both requests
share, which makes the constraint on it the only thing that closes both. A
uniqueness rule this load-bearing belongs in the database (D5), not in a
service check that races.

**C12b. Logging in claims the guest cart. Carts are never merged.** When a
request authenticates a customer who is carrying a guest cart token, that cart
is **claimed**: in one transaction under the cart lock (S5), `session_key` is
cleared and `customer` is set. Nothing else about the cart changes — not its
lines, not its public id (Q3a), not its signed token.

- **No merge.** Lines are never combined with those of a cart the customer
  already had, and no cart is deleted. An earlier customer cart is left exactly
  as it is. The customer's **current cart** is the most recently updated
  unconverted cart they own — the claimed one, immediately after a claim.
- **A converted cart is never claimed** (C12a). It belongs to an order; the
  client works on a new cart, as C12a already says.
- **The claimed cart is repriced before it is next shown** (M5). The customer's
  saved address, their `preferred_language` and their per-customer discount
  limits (G2) can each change the quote, and M6 compares against what the
  customer was last shown.
- **The idempotency scope changes with the principal, by design.** Keys taken
  before the claim are scoped to the cart (C12); keys taken after are scoped to
  the authenticated principal (C11). C12a is what makes that change safe: a
  checkout already in flight under the guest scope and a retry arriving under
  the new one serialize on the cart lock, and the cart still converts to at most
  one order.

*Why:* merging two carts is four decisions, not one — what happens to a line
present in both, whether the merged cart re-checks stock, whether a code the
guest applied is re-evaluated against the account's per-customer limit (G2), and
what becomes of the guest cart's idempotency scope once the principal is
different. Each is a rule, and the case they serve is rare: the cart a customer
is looking at when they log in is almost always the one they meant to buy.
Leaving it a session cart while the principal is authenticated is the other
cheap option and is the worse one — it contradicts C11, and the cart would not
follow the customer to another device. The claim is a two-column write, and
every rule that names a cart keeps pointing at the same row.

---

## 7. Transactions and external calls

**T1. No outbound HTTP call ever happens inside `transaction.atomic()`.**
Commit first, then call. Results are written in a second transaction. The
shared HTTP client (T4) raises if it is called inside an atomic block.
*Why:* a provider call inside a lock holds row locks and a connection for the
full timeout. One degraded gateway then exhausts the pool and takes the site
down.

**T2. No side effect outside the database happens inside `atomic()`.**
Emails, notifications and task enqueues register on `transaction.on_commit`.
Every task is idempotent, because it may run twice.

**T2a. An `on_commit` task can be lost; nothing that matters depends on it
alone.** A crash between commit and enqueue drops the task. Any task whose loss
would break an invariant is re-derivable from database state, and a sweeper
re-drives anything still outstanding `INTENT_SWEEP_AFTER` after commit:
refunds in `requested` not yet sent, `allocation_failed` cases C6a has not yet
attempted (S1b), queued notifications (T2b), and orders whose payment status
reached `paid` with no invoice issued (I1a). The sweeper is monitored (N4).
Idempotency comes from re-checking domain state under lock, never from task
deduplication.
*Why:* `on_commit` keeps a task out of a rolled-back transaction, but it runs
after commit, so there is a window where the change is durable and the task is
not. A sweeper closes it for any queue backend, including a later Celery swap.

**T2b. Transactional customer messages are guaranteed.** A `Notification` row
is written **in the same transaction as the change it reports**, and a job
sends it. The row holds: recipient (copied from the order, or the user's own
email for the account messages that have no order — A1c), channel, template
code, language (O8, or resolved by L3a where there is no order), rendered body,
trigger (the domain row that caused it),
status (`queued | sent | failed`), attempts, sent_at. Unique on
(trigger, template), so a replayed transition cannot queue a message twice.

- The send runs outside any transaction (T1), through a channel adapter behind
  a port. Email only in v1.
- Delivery is at-least-once: a crash between sending and marking `sent` can
  repeat a message; nothing can lose one.
- A failed send retries with backoff up to `NOTIFICATION_MAX_ATTEMPTS`, then
  becomes `failed` with an alert (N5). Staff can re-queue it.
- The body is rendered and stored when the row is created, so it records what
  the customer was told (R6).

Guaranteed messages: order confirmation, payment failed, address-change
payment link (O11), order or items cancelled, shipment sent, refund completed
(one per refund group, R1c),
automatic resolution outcome (C6a), return decision (R7), email verification
and password reset (A1c), guest order link (A8a). Marketing messages are
outside this rule.
*Why:* a customer who never learns their order was cancelled or refunded calls
support or files a chargeback. A message sent `on_commit` is lost on a crash;
a row written with the change is not.

**T3. `atomic()` blocks are small and specific.** Never wrap a whole view.

**T4. Every outbound HTTP call goes through one shared client that sets
connect and read timeouts.** Adapters never call `requests` or any other HTTP
library directly (checked statically, W8a).
*Why:* `requests` has no default timeout, and a convention every call must
remember fails on the first call that forgets. One hanging dependency holds
every worker open.

**T4a. The database enforces its own timeouts**, set at role level
(`ALTER ROLE … SET`), never per session:

| Setting | Web requests | Jobs |
|---|---|---|
| `lock_timeout` | 5 s | 5 s |
| `statement_timeout` | 30 s | 10 min |
| `idle_in_transaction_session_timeout` | 60 s | 60 s |

Web and job workers connect as separate database roles so each gets its
values. The migration and retention roles have their own settings (D6). A lock
or statement timeout is an infrastructure error — 503, retryable (X9) — and the
transaction rolls back whole (X11).
*Why:* one stuck transaction otherwise holds S5 locks indefinitely and every
checkout queues behind it. Connection poolers in transaction mode drop
session-level `SET`, so only role-level settings are reliable.

**T5. Retries never convert a transient provider failure into a terminal
payment state.** Status reads may be retried within the provider's rate
limits; anything that moves money is retried only under P14's stable key.

**T6. A reconciliation job polls the provider for everything a lost webhook
would strand:**
- **provider-confirmed** attempts in `created`, `requires_action` or `pending`
  past session expiry plus grace (C2b) — an admin-confirmed row (P13b) has no
  provider session and is never polled;
- refunds in `requested` never sent, or in `sent` never confirmed, older than
  `REFUND_RECONCILE_AFTER`.

Results are applied per P15.
*Why:* webhooks fail silently. Polling is the truth; webhooks are the fast
path.

**T7. A daily settlement reconciliation job diffs the provider's settlement
report against the payments table** — captures, refunds, fees and disputes —
and raises an alert (N5) on any divergence, in either direction.
*Why:* T6 only resolves payments we already know are stuck. Settlement
reconciliation is the only control that catches money problems nobody
anticipated: a capture never recorded, a refund sent twice, an overpayment
that slipped past P12. It is defined by finding the failures that are not on
anybody's list, which is why it cannot be replaced by more specific checks.

Matching rules:
- Items match by provider id — capture, refund, dispute, fee — never by
  amount.
- Settlement lags capture by days: an item still unmatched after
  `SETTLEMENT_MATCH_WINDOW` (default 7 days) alerts, in either direction.
- Amounts are compared in the currency the provider reports. Nothing is
  converted, so dispute fees stay as recorded (M13).
- `MockProvider` produces a settlement report, so T7 is tested like any other
  adapter path.

COD cash remittance — what the courier collected against what it paid the
merchant — is outside T7 and out of v1. The admin-recorded cash (P1, item 3)
is the truth.

---

## 8. Queries and payload

### Queries

**Q1. Query count must be constant with respect to row count.** Every list
endpoint, detail endpoint, admin list and admin change page (including its
inlines) uses `select_related` / `prefetch_related` / `list_select_related`.

**Q1a. Derived values are computed from annotation or prefetch, never by a
query per row.** This covers `display_status` (S9), fulfilment derivation (S1),
available stock (C3) and effective totals (O10), and any value like them.
*Why:* a derived field looks free in a serializer and runs one query per row
in a list. It is the N+1 that `select_related` does not catch.

**Q2. Every list endpoint is paginated with an enforced maximum page size.** A
client-supplied size above the cap is clamped, not honoured.
*Why:* a constant query count returning 200,000 rows is still a dead worker.

**Q2a. Public list endpoints use cursor (keyset) pagination**, default page
size 20, maximum 100, with no total count. Every paginated query orders by its
sort key and ends with a unique tiebreaker, and **that tiebreaker is the row's
public identifier — public id, order number or slug (Q3a) — never the internal
primary key.** The cursor encodes both, and a base64 cursor is readable by
anyone, so an `id` tiebreaker would publish internal keys on every list
response (O6). A tiebreaker needs a total order, not a meaningful one, so a
random public id serves. Each allowed sort is backed by an index on
(sort key, public identifier) (Q2b). The cursor is opaque to the client. The
Django admin keeps its own offset pagination.
*Why:* offset pagination repeats or skips rows while new ones are inserted,
and slows down with depth; a total count is a full scan on large tables. The
pagination shape is public API (X8), so it is fixed once.

**Q2b. Filters and sorts are allowlisted per endpoint, and each allowed one
is backed by an index.** An unknown filter or sort parameter is a 400
validation error (X9), never silently ignored.
*Why:* an arbitrary sort is an unindexed scan, which the statement timeout
(T4a) then kills in production and nowhere else. Silently ignoring an unknown
filter returns the wrong rows with a 200.

**Q2c. Anything larger than one page runs as a job that produces a file.**
Exports and reports never run inside a request. Admin lists on large tables
set `show_full_result_count = False`.
*Why:* the request would hit the statement timeout (T4a); the job has its own.

**Q3. No list endpoint, detail endpoint or admin page ships without a test
asserting the query count at two dataset sizes; list endpoints also assert the
page-size cap.**

### Payload

**Q3a. Every endpoint has an explicit output schema.** A model is never
serialized wholesale. Responses identify entities by public identifiers only —
order numbers, slugs, or a random public id — never an internal primary key
(O6). Entities addressed from outside and having neither an order number nor a
slug — variants, carts, cart lines, order items, addresses, shipments, return
requests, refund groups (R1c) — carry a random public id for this purpose. The
list is what v1 has, not a limit: the rule is the test.
*Why:* A7 guards what a client may write; this guards what a response may
leak. A new model field must not reach the API because nobody excluded it.

**Q3b. Every monetary amount in a response is an object:
`{"amount": 1999, "currency": "EGP", "exponent": 2}`**, with the exponent
from the ISO-4217 table (M1a).
*Why:* a frontend that keeps its own currency table will get KWD wrong by a
factor of ten. Carrying the exponent removes that bug class at the source.

**Q3c. Every request is size-bounded before domain code runs.** Request bodies
are capped at 1 MB (webhooks follow A10). Schemas cap list lengths and numeric
ranges: a cart holds at most 100 lines, and a line's quantity is between 1 and
`MAX_LINE_QUANTITY` (default 99, configurable). A violation is a 400.
*Why:* an unbounded array or quantity is a cheap way to make one request cost
the server a great deal.

### Search

**Q3d. Catalog search in v1 is PostgreSQL full-text search** over product
name and description, with a GIN index, per installed language over the
translation rows (L5). No external search engine.
*Why:* a storefront needs search, and the database already provides it
without another paid service per deployment.

---

## 9. Auth and access

**A1. The custom user model is email-based and was set before the first
migration.** It is never swapped.

**A1a. Emails are normalized and unique case-insensitively.** One
normalization function (trimmed, lowercased) is applied on write, and a
case-insensitive unique constraint enforces it. Every email comparison — login,
guest attachment (O5), per-guest coupon limits (G2), fraud limits (V1) — uses
the same function.
*Why:* `Foo@x.com` and `foo@x.com` are one inbox. Treated as two, they are two
accounts, and a guest order that never attaches.

**A1b. Passwords are hashed with Argon2id** and checked by Django's password
validators on every set or change.

**A1c. Email verification and password reset tokens are single-use,
expiring, and stored hashed.** Both messages are guaranteed (T2b). A password
reset or change bumps the user's `token_version` (A4b) and ends every admin
session, so every existing credential dies with the old password.
*Why:* O5 trusts a verified email to attach orders; that trust is only as good
as the token that proved it.

**A2. API clients authenticate with JWT; the admin uses Django sessions.**

**A3. JWT validation explicitly verifies signature, permitted algorithm,
issuer, audience, expiry and not-before.** No claim is trusted before
cryptographic verification. Algorithm selection is server-controlled and
algorithm confusion is rejected.
*Why:* authentication is not "decode a token and believe it."

**A3a. JWTs are signed with HS256**, fixed server-side. Tokens naming any
other algorithm are rejected.
*Why:* the same service signs and verifies, so asymmetric keys add key
management and nothing else.

**A4. Access-token and refresh-token lifetimes, rotation, revocation,
signing-key rotation and clock-skew tolerance are explicitly configured.**
Access tokens ≤ 15 minutes, refresh tokens rotate on use, a blacklist backs
logout.
*Why:* a JWT cannot be revoked. No credential lifetime may be inherited from a
library default.

**A4a. A rotated refresh token presented again revokes its whole family.**
Every refresh token belongs to a family started at login. Reuse of one that
was already rotated means two parties hold it; every token in the family is
revoked and the user must log in again.
*Why:* rotation alone lets a thief keep refreshing for as long as they use the
token first. Reuse detection turns theft into a forced logout.

**A4b. Every JWT carries the user's `token_version`, checked on every request**
with one primary-key read. Deactivation, password change, erasure (I10) and
"log out everywhere" bump it, and take effect immediately.
*Why:* an access token otherwise stays valid for up to 15 minutes after the
account behind it was locked.

**A4c. Signing keys rotate with two active keys, selected by `kid`,** during
a configured window: new tokens use the current key; verification accepts the
previous one until the window closes.
*Why:* the same reason as P2a — a hard cut-over logs out every user at once.

**A4d. Browser frontends keep the refresh token in an `HttpOnly`, `Secure`,
`SameSite=Strict` cookie, path-scoped to the refresh endpoint.** That one
endpoint is CSRF-protected. The access token lives in memory only, never in
`localStorage`. Mobile clients send the refresh token in the request body.
*Why:* a token in `localStorage` is readable by any script on the page, so one
XSS bug steals every session.

**A5. All session-authenticated state-changing endpoints require CSRF
protection.** JWT authentication never depends on ambient browser cookies,
except the refresh endpoint (A4d), which is CSRF-protected.
*Why:* session auth without CSRF lets another site drive an authenticated
admin's browser.

**A5a. Browser-facing security is enforced at boot.** CORS allows only the
origins configured for the deployment, never `*`. A production deployment
refuses to boot unless `manage.py check --deploy` is clean: HSTS, secure and
`HttpOnly` cookies, `SameSite`, clickjacking protection.

A deployment also warns at boot when a configured CORS origin's registrable
domain differs from the API's own, because A4d's `SameSite=Strict` refresh
cookie is not sent on a request that is cross-site by registrable domain — so
a frontend on a different registrable domain from the API cannot refresh at
all, silently. The API is served on the client's registrable domain; this is a
setup-guide requirement, not a code path.
*Why:* each of these is one missed setting away from off, and nothing fails
visibly when it is.

**A6. Authentication and authorization are separate checks.** Ownership is
enforced at the object level, not only at the endpoint. Queries are scoped to
the requesting principal, never filtered after retrieval. An object the caller
may not access answers exactly as a nonexistent one does (X9).
*Why:* knowing who a user is does not prove they may read order 5. Broken
object-level authorization is the most common serious API vulnerability.

**A6a. Every privileged action checks a named permission defined in core:**
`collect_cash`, `request_refund`, `approve_refund`, `approve_cancellation`,
`adjust_stock`, `resolve_review`, `manage_returns`, `change_address`,
`create_shipment`, `record_delivery`, `record_receipt`,
`view_payment_events` (P9), `manage_settings` (F1c). Core ships three default
groups — support, warehouse, finance — built from them; a deployment may
regroup, never rename. `manage_settings` belongs to no default group and is
granted explicitly.

Fulfilment is covered by three of them, splitting exactly as S8's "Recorded by"
column does: `create_shipment` creates a shipment and its items;
`record_delivery` records what the courier reports — `delivered`,
`delivery_failed`, `refused`; `record_receipt` records `received_back` on
physical receipt, which only the warehouse can know. `collect_cash` covers
recording an offline refund payout and its reference (R1) as well as collecting
COD cash: both are the same cash desk.

A refund whose amount the domain computes from stored values — a
cancellation (S2, S2a) or a closed return (R8) — is authorized by the
permission of the action that causes it: `approve_cancellation` or
`manage_returns`. `request_refund` governs refunds whose amount staff choose.
Second approval (R1b) applies to both.
*Why:* "permission-gated" is enforceable only when the permission has a name
the code checks. The person approving a cancellation does not choose its
refund amount, so the refund needs no separate permission; a goodwill amount
is chosen, so it does.

**A6b. Every staff account uses TOTP two-factor authentication**, and admin
sessions end after `ADMIN_SESSION_IDLE_TIMEOUT` without activity.
*Why:* one staff password is enough to issue refunds. A second factor is the
difference between a phished password and a phished store.

**A7. Client input may modify only explicitly writable fields.** Monetary
fields, ownership, audit fields, stock, payment status, fulfilment status,
`cancelled_at` and actor fields are never mass-assigned.
*Why:* a generic serializer update must not let a client bypass the domain
services every other rule here relies on.

**A8. Guest order access uses a signed, order-scoped, expiring,
non-enumerable token** with defined revocation behaviour on cancellation,
refund, account claiming, compromise, erasure and expiry.
*Why:* A6 scopes queries to the requesting user, and a guest has no user.

**A8a. Guest tokens are revocable.** The order carries
`guest_token_version`; every guest token names the version it was issued
under, and the server rejects any other. Revocation (A8, O5) bumps the
version, killing every link issued before. Guest tokens live
`GUEST_TOKEN_TTL` (default 60 days); after that the customer requests a fresh
link by email and order number (rate-limited, A9a; answered identically
whether or not they match, A9c).
*Why:* a signed token cannot be recalled on its own. One counter on the order
makes every earlier link revocable at once.

**A8b. Guest tokens never linger in URLs, headers sent elsewhere, or logs.**
The emailed link's token is exchanged on landing for a short-lived token held
in memory, and removed from the address bar. Order pages send
`Referrer-Policy: no-referrer`. Request logs and error tracking strip guest
and cart tokens (A12, X15).
*Why:* a token in a URL leaks through browser history, server logs, and the
`Referer` header sent to any third-party script — and it opens a page with the
customer's name, address and phone.

**A9. Every sensitive endpoint has an explicit rate-limit policy** naming the
principal, window, maximum, shared storage mechanism and exceeded-limit
response, enforced consistently across workers and instances. Covers login,
token refresh, password reset, checkout, payment initiation and coupon
validation. An exceeded limit answers 429 `rate_limited` with `Retry-After`
(X9).

**The default shared store is a PostgreSQL table**, one row per
(policy, principal, window), incremented with a single
`INSERT … ON CONFLICT DO UPDATE … RETURNING` so the increment and the read of
the new count are one atomic statement (C1). Expired window rows are pruned by
a scheduled job (N4 applies). Django's `DatabaseCache` is **not** acceptable
as this store: its `incr` is a read followed by a separate write, which races.
A deployment may move the store to Redis by configuration; the policies do not
change.

The same store holds the windowed placement caps that are not rate limits in
name: the zero-total placement cap (S1c). Two kinds of limit do not belong
here: gauges — counts that go down, such as V8's open-COD cap (see V8) — and
caps with no window at all, such as V1a's per-order failed-attempt limit,
because these rows are pruned per window (see V1a).
*Why:* "rate-limited" without a shared store is not enforcement — it is one
worker's opinion. And the stack runs without Redis by default, so the shared
store has to be the database, done atomically.

**A9a. Default rate-limit policies**, configurable per deployment:

| Endpoint | Limit |
|---|---|
| login | 5 / 15 min per account; 20 / 15 min per IP |
| password reset, verification resend, guest link request | 3 / hour per email; 10 / hour per IP |
| registration | 10 / hour per IP |
| token refresh | 30 / min per token family |
| checkout | 10 / min per principal |
| coupon validation | 20 / 10 min per principal and IP |
| return-page check (P1a) | 30 / min per order |
| search | 60 / min per IP |

Payment initiation follows V1b; failed payment attempts follow V1a.

**A9b. The client IP comes only from configured trusted-proxy hops**, never
from a raw `X-Forwarded-For` header. A9, V1 and R6 all read it through one
function.
*Why:* a client can write any `X-Forwarded-For` it likes. Trusting it makes
every IP limit and every recorded IP the attacker's choice.

**A9c. No endpoint reveals whether an account exists.** Login, registration,
password reset, verification resend and guest link requests respond
identically either way.
*Why:* an enumeration oracle hands attackers the list of customer emails to
phish and to feed into credential stuffing.

**A10. Webhook endpoints are exempt from global throttling but enforce a
strict maximum body size before parsing or database work.** Oversized bodies
are rejected with 413 without JSON parsing (X12).
*Why:* the throttling exemption would otherwise be an unbounded
resource-exhaustion path.

**A11. Secrets come from environment variables and the app raises at boot if a
required one is missing.**

**A12. Secrets are never logged.** No tokens (including guest and cart
tokens), signing keys, `Authorization` headers, passwords or card data.

---

## 10. Discounts and coupons

**G1. Redemption is atomic and is taken at order commit**, in the same
transaction that creates the order, with the discount row locked before the
order (S5): unique constraint on `(discount, order)` plus a conditional
`UPDATE` on the usage counter (C1). If the update affects no row, no order is
created (G4). This holds for every payment method, COD included.
*Why:* taking the redemption at payment success would let a paid order carry
a discount that ran out in between — a price the store never agreed to, or a
paid order that cannot be honoured.

**G1a. Discount values are integers.** A percentage `value` is basis points,
1–10000. A fixed `value` is in minor units of `STORE_CURRENCY` (M1, M2, M3a).
A free-shipping discount has no `value`. A fixed discount also carries
`value_currency` — required for a fixed discount, `NULL` otherwise — because
M2 admits no stored amount without a currency, and F1d's boot check has
nothing else to read. `DiscountRedemption.amount_applied` carries its currency
(M2).
*Why:* a percentage stored as a float is the one float left in the money
path, and it feeds every discounted line.

**G2. Per-customer limits are enforced at the database level, scoped by the
normalized email (A1a) for accounts and guests alike.** `DiscountRedemption`
stores that scope key. Under the discount row lock (S5), in the same
transaction as G1, the active redemptions for `(discount, scope_key)` are
counted — backed by an index — and checked against `max_uses_per_customer`.
Released redemptions (G7) do not count.
*Why:* a unique constraint cannot enforce a limit above one, and the discount
lock is what serializes two checkouts by the same customer. Scoping accounts
by user id and guests by email would let one customer redeem once as a guest
and again under the account the order later attaches to (O5).

**G3. A discount can never exceed the discountable subtotal, and a total can
never go negative.** Clamped, and asserted by M11. A total of exactly 0 is
placed as a `zero_total` order (S1c).

**G3a. The discountable subtotal is `sum(line_total_i)` before any discount,
on the store's price basis** — tax-inclusive or tax-exclusive, per
`PRICES_INCLUDE_TAX`. Every line is discountable in v1. Tax is computed on
`line_net_i` after the discount (M10). `min_order_total` is compared against
that same discountable subtotal — the pre-discount line subtotal on the store's
price basis, excluding shipping. It is never re-derived on a different basis:
under `PRICES_INCLUDE_TAX` the line subtotal includes tax, and so does the
minimum measured against it, which is the number the merchant entered and the
customer sees.
*Why:* M8 allocates against the discountable subtotal and G3 clamps to it; an
undefined base gives two implementations two different totals.

**G3b. A free-shipping discount covers the full shipping cost of whichever
method is chosen.** `shipping_discount` equals the shipping cost, so
`shipping_net` and `shipping_tax` are zero. No per-method restriction or cap
in v1. It never touches lines (M8).

**G4. Validity is re-checked at checkout, not only when the code is applied.**
Validity — active, inside the window, usage remaining, the per-customer limit,
the minimum — is an input to `reprice_cart()` (M5), and the discount's
validity and value are among the inputs the commit transaction re-asserts
(M6a). The per-customer limit is checked at checkout, when the order email is
known; applying a code before that checks everything else.

If the discount no longer applies at checkout, or the G1 update fails at
commit: no order is created, the quote is returned without the discount, and
the response is `price_changed` (M6) carrying the G6 reason.
*Why:* a code applied at 23:59 and submitted at 00:01 has expired. Dropping
the discount silently would charge a number the customer never saw.

**G4a. `starts_at` and `ends_at` are stored in UTC and entered in the store
timezone** (L1, L2). The admin shows them in the store timezone.
*Why:* "valid until the end of Friday" means the store's Friday.

**G5. One discount per order in v1.** `stacking_class` exists and is always
`EXCLUSIVE`.

**G6. When a discount does not apply, the reason is recorded and returned.**
Never a silent no-op. The reason is one code from a closed set, first match
wins:

| Code | Meaning |
|---|---|
| `not_found` | no such code, or the code is inactive |
| `not_started` | before `starts_at` |
| `expired` | after `ends_at` |
| `exhausted` | `max_uses` reached |
| `customer_limit_reached` | `max_uses_per_customer` reached (G2) |
| `below_minimum` | the discountable subtotal is below `min_order_total` (G3a) |

Codes are part of the public API (X8). An inactive code answers `not_found`.
The reason travels in the error's `details` (X7).
*Why:* a frontend can only explain what it can name. Answering `inactive`
would confirm that a code exists, and coupon validation is exactly where
people guess codes.

**G7. Cancelling the whole order returns its coupon use.** When a whole-order
cancellation executes (S2) — by staff, by the system under C6a, or under
S2b — the `DiscountRedemption` is marked `released` and the usage counter is
decremented, in the same transaction and under the discount lock (S5). The
row is kept, never deleted.

Item cancellation (S2a), refused delivery (S8), `uncollected`, refunds and
returns never return the use.
*Why:* a cancelled order delivered nothing, so it should not spend a
customer's one-time code. Every other path delivered something under the
discount's terms, and the customer keeps those terms (S2a).

---

## 11. Client configuration

**F1. Per-client differences live in configuration, never in code.** Every
setting is declared in the core settings registry (F1a). The registry is the
complete list, and the config reference in the buyer docs is generated from
it.
*Why:* a list kept in prose drifts from the code within one release.

**F1a. Every setting is declared once, in one registry in core**, with its
type, default, allowed range and change class:

| Class | Lives in | Changes by |
|---|---|---|
| `deploy` | deployment settings or environment | redeploy; validated at boot |
| `runtime` | a database table | admin action, without a deploy (F1c) |
| `locked` | deployment settings | fixed once any order or discount exists (F1d) |

A missing required value, a wrong type or an out-of-range value raises at
boot. Secrets follow A11. No code reads a setting except through the registry
(checked statically, W8a). Model definitions never read one (D2f).
*Why:* several rules already fail at boot (A11, C2b, P2b, A5a), each on its
own. One registry checks every setting the same way, so a misconfigured
deployment fails at start, not at the first order that reaches the bad value.

**F1b. Settings that change what an order is worth, or the customer's terms,
are copied onto the order at commit:** `PRICES_INCLUDE_TAX`,
`COD_PARTIAL_ACCEPTANCE`, `COD_REFUSAL_SHIPPING_FEE`, and the return rules in
force (R7). Every later path — the M11 assertion, refusal handling (S8),
return eligibility (R7) — reads the copy. The registry marks which settings
are snapshotted. A snapshotted setting added later is never backfilled onto
existing orders (D2e).
*Why:* O4 forbids historical calculations from reading mutable config.
Without the copy, changing a setting changes the M11 formula of an existing
order, or the cost of a refusal the customer accepted under other terms.

**F1c. Runtime settings in v1 are exactly two:** the checkout kill switch
(N1) and per-provider enable/disable (N2). Changing one requires the
`manage_settings` permission (A6a) and writes an audit row: setting, before,
after, typed actor (S4), reason, timestamp.
*Why:* a runtime setting is a production change with no deploy and no
review. The list stays limited to the emergency controls that need it, and
every pull is recorded.

**F1d. `STORE_CURRENCY` is locked once any order or discount exists.** The
app raises at boot if the configured value differs from the currency of
existing orders (`Order.currency`) or of existing fixed discounts
(`Discount.value_currency`, G1a). Changing it is a documented migration,
not a config edit.
*Why:* fixed discount values are minor units of `STORE_CURRENCY` (G1a).
Changing the setting silently re-denominates every one of them.

**F1e. A core release that adds a setting ships a default that preserves
prior behaviour**, or its changelog marks the release as requiring a manual
step (W4).
*Why:* deployments upgrade in place (W5). A new required setting with no
default fails boot on every client at once.

**F2. A client deployment never contains domain logic.** What a deployment
may contain, and the route for a client that needs different behaviour, is
W2.

**F3. Core ships a default template for every message template code (T2b) in
every installed language (L3).** A deployment may override a template's
subject, body and branding by template code. It may never add a code, remove
one, or change which trigger sends it.
*Why:* the backend is headless, so messages are the only customer-facing
output a deployment brands. Which messages are guaranteed is a domain rule,
not theming.

---

## 12. Migrations and data

**D1. Every migration is read by a human before it is run**, including its
SQL (`sqlmigrate`) and any `RunPython` or `RunSQL` it contains.
*Why:* autogenerate can turn a rename into a drop and recreate, which loses
data, and the SQL is where lock behaviour is visible.

**D2. Schema changes are backwards-compatible with the running code, by
expand/contract.** The previous release must run correctly against the new
schema.

- **Add a `NOT NULL` column:** with a constant `db_default`, one deploy —
  PostgreSQL 11+ adds it without a table rewrite. Otherwise three deploys:
  nullable, backfill (D2c), then constrain (D2b). Never a plain `default=` on
  a `NOT NULL` column: Django drops that default after adding the column, and
  the old code's inserts then fail.
- **Remove a column or table:** stop reading and writing it in one release
  and remove it from Django's state in that release
  (`SeparateDatabaseAndState`); drop it in the next release.
- **Rename:** add the new column, write both, backfill, switch reads, stop
  writing the old one, then drop it. Never an in-place rename on a table the
  running code reads.

*Why:* the old code runs during the deploy, and Django selects every field it
knows about, so a dropped or renamed column breaks every query on that table.

**D2a. A migration never waits long for a lock.** Migrations run as the
migration role (D6) with `lock_timeout` 3 s, and a lock timeout retries the
migration with backoff, up to `MIGRATION_LOCK_RETRIES`, then fails the deploy.
*Why:* an `ALTER TABLE` queued for its lock blocks every query queued behind
it, so a checkout waiting on a migration is an outage. Failing fast and
retrying costs seconds.

**D2b. On a table that already holds rows, indexes and constraints are built
without blocking writes.** Indexes use `AddIndexConcurrently` /
`RemoveIndexConcurrently` in a migration with `atomic = False`. `CHECK` and
foreign-key constraints are added `NOT VALID` and validated in a separate
migration (`VALIDATE CONSTRAINT`), through `RunSQL`. Unique constraints are
built as a concurrent unique index first, then attached. A CI check rejects
the blocking forms on existing tables. The same check flags destructive
operations for D3.
*Why:* a plain `CREATE INDEX` blocks writes for its whole build, and adding a
constraint with validation holds a strong lock for a full table scan.

**D2c. Backfills are jobs, not migrations.** A migration changes schema. Any
rewrite of data in a populated table runs as a batched, idempotent, resumable
job (Q2c) under the job role's timeouts (T4a). `RunPython` is allowed only on
tables that are empty or bounded by design (seed and lookup rows).
*Why:* a backfill inside one migration transaction holds locks and a
connection for its full duration, and a timeout halfway rolls all of it back.

**D2d. Migration code uses historical models only** (`apps.get_model`) and
never imports domain code or services. **Migrations and backfill jobs never
write stock, monetary amounts, payment or fulfilment status, or the existing
values of committed order, payment, refund, invoice, adjustment or ledger
rows.** A change that seems to need one is a stop-and-ask.
*Why:* a migration is exactly the "management command, import" that C9, S3
and O9 forbid. One bypass voids the ledger and the evidence.

**D2e. A new snapshot column is never backfilled from current configuration
or catalog.** On rows committed before the column existed it is nullable, and
`NULL` means "pre-snapshot"; code reading it handles that case explicitly. It
may be backfilled only from values the row itself already holds, under the
temporary grant D7a describes.
*Why:* O4. Filling today's value into last year's order rewrites what that
order meant.

**D2f. Model definitions never depend on settings or environment.** Field
choices, lengths, defaults and constraints are constants in code;
configuration is validated against them (F1a). Core CI runs
`makemigrations --check`. Deployments never generate or hold migrations for
core apps (W1, W2).
*Why:* a choice list built from installed languages or enabled providers
makes `makemigrations` produce a different migration per deployment, and
core's migration history forks.

**D2g. Migrations run once per deploy, in a single release step before the
new code starts** (Render `preDeployCommand` or its equivalent). Never on
application boot, never per instance.
*Why:* two instances migrating at once race on the same DDL.

**D2h. Production rollback is a code rollback, never a schema rollback.**
Expand/contract (D2) keeps the previous release compatible with the current
schema. Reverse migrations are written where possible, for development; they
are not the incident procedure.
*Why:* reversing a migration on live data loses whatever was written since
it ran, and the reverse path is never tested under load.

**D3. No destructive migration on a deployment holding real orders without a
verified backup first.** *Destructive* means dropping a column or table,
narrowing a type, or any change that rewrites existing values. *Verified*
means a backup or point-in-time restore point taken immediately before the
migration, its identifier recorded with the deploy, from a backup system whose
last restore test (D4) passed. The release step refuses a migration the D2b
check flags as destructive unless that identifier is supplied.

**D4. Any deployment with paying customers runs on a database tier with
automated backups and point-in-time recovery that meets its declared RPO
(D4a).** An automated job restores the current backup into a scratch database
monthly and alerts on failure. The restore is checked by content, not only by
success: the migration head matches the deployment, row counts are within the
expected range of production, and the newest order in the restore is no more
than `BACKUP_RPO` behind the newest order in production **at the time the
backup was taken** — never behind the clock, which would fail the test every
month on a store that simply took no order in the last hour. The measured
restore time is compared against the RTO.
*Why:* backups fail silently, and the one that has to work is the current one,
not the one you tested at launch. A restore that succeeds into an empty or
week-old database proves nothing.

**D4a. Every deployment declares its RPO and RTO in the settings registry**
(`BACKUP_RPO`, default 1 hour; `BACKUP_RTO`, default 4 hours; class
`deploy`). A database tier that cannot meet the declared RPO — typically a
free tier — does not satisfy D4. Before a deployment takes paying customers,
its hosting record states the provider's point-in-time recovery window,
verified against the provider's current plan, and that window meets
`BACKUP_RPO`.
*Why:* "has backups" says nothing about how much data a restore loses or how
long the store is down.

**D4b. Backups are encrypted, access-controlled like raw payment events (P9),
and stored in the deployment's residency region (I9).** `BACKUP_RETENTION` is
configuration and never exceeds what the I9 retention settings allow.
*Why:* a backup is a complete copy of every customer's personal data, and it
is subject to every rule the live database is.

**D4c. A restore re-applies erasures before it serves traffic.** Every
erasure (I10) is written to an erasure log that holds the internal
identifiers of the erased rows and the timestamp, never the erased data. The
log is kept outside the database it describes, so a restore cannot roll it
back. After any restore, every erasure newer than the backup is replayed.
*Why:* otherwise restoring last week's backup un-erases everyone who asked
this week.

**D5. Every identifier required for correctness has a database uniqueness
constraint covering its full correctness scope.** At minimum:

- provider payment, refund and event ids (P5, P14)
- order numbers (O6) and public ids (Q3a)
- idempotency keys, per principal and operation (C10, C11)
- `confirmation_token`, per cart (M6, C10)
- invoice numbers per series (I3)
- normalized email, case-insensitively (A1a)
- `(discount, order)` (G1)
- `(trigger, template)` on notifications (T2b)
- one open `CancellationRequest` per order (S2)
- one order per cart (C12a)
- one `PlacementGuard` per (identity type, identity value) (V8)
- one active payment attempt per payable: one over the order for attempts with
  no adjustment, one over the adjustment for difference payments (P13a, O11)
- one `OrderAdjustment` in `awaiting_payment` per order (P13a, O11)
- one system refund per (review case, payment) (C6a, R1c)
- one refund per (refund group, payment) (R1c)
- one credit note per refund group, where the group issues one (R1c, I2)
- one open alert per `(code, subject)` (N5)
- one fraud assessment per payment attempt, and one per order for a method
  that creates no attempt (V7, S1c)
- one translation per `(object, language)` (L5)

Each has a concurrency test.
*Why:* application-level checks race: two requests both check, both find
nothing, both insert.

**D6. The database is used through four roles, each with least privilege:**

| Role | Used by | Privileges | Timeouts |
|---|---|---|---|
| migration | the release step (D2g) | owns the schema; DDL | `lock_timeout` 3 s; no statement timeout |
| web | request workers | DML only, limited by D7 and D7a | T4a, web |
| job | background workers and backfills | DML only, limited by D7 and D7a | T4a, jobs |
| retention | the retention pruning job, and the erasure job for one write (I8, P9, I10b) | `DELETE` on retention-governed tables; `UPDATE` on `Consent.subject` alone (D7, I10b) | T4a, jobs |

The web and job roles hold no DDL rights.
*Why:* each role gets only what its work needs, and a bug in request code
cannot alter the schema or delete history.

**D7. Append-only tables are enforced by grants, not convention.** The web
and job roles have no `DELETE` on them, and `UPDATE` only on the columns
their lifecycle writes:

| Table | `UPDATE` allowed on |
|---|---|
| `StockMovement` | none |
| `OrderStatusLog` | none |
| `SettingChange` | none |
| `Consent` | none for web and job; `subject` by the **retention** role alone, for erasure (I10b) |
| `FraudAssessment` | none |
| `PaymentEvent` | `processed_at`, outcome, reason |
| `Invoice`, `CreditNote`, `DebitNote` | issuance status, number (set once, at issue — I3) and authority identifiers (I6, I7) |
| `OrderAdjustment` | status |

Status columns on these tables are guarded by a database trigger that permits
only the transitions their rule lists: `OrderAdjustment`
`awaiting_payment → applied | cancelled | expired` (O10); invoices and notes
per I7. The same trigger lets a document number go from `NULL` to a value
only in the update that moves the document to `issued` (I3), and never
change after.

`Consent.subject` is the one exception to a table's own append-only grant, and
it belongs to the retention role alone: the record — scope, wording version,
given or withdrawn, timestamp, source — stays immutable, and only the pointer
to the person is replaceable (I10b).

Deletion for retention (I8, P9) is done only by the retention role (D6).
*Why:* I1, C8 and O10 depend on these rows never changing. A grant makes that
true for every code path, including the ones nobody reviewed; a column grant
cannot say *which* new value is legal, so the trigger does.

**D7a. Committed orders, payments and refunds freeze their financial and
copied columns by grant.** The web and job roles hold `UPDATE` only as
listed:

| Table | `UPDATE` allowed on |
|---|---|
| `Order` | payment status, fulfilment status, `cancelled_at`, `guest_token_version`, customer (set once — a trigger allows only `NULL` to a value, O5), shipping address columns (O11), contact and fraud-signal columns (for anonymisation, I10) |
| `OrderItem` | `shipped_quantity`, `cancelled_quantity`, `returned_quantity` (S7) |
| `Payment` | every column except the order, the payable it pays for, expected amount, expected currency and idempotency key (P10, P13a, P14) |
| `Refund` | every column except the payment, refund group, amount, line and shipping allocation, deductions and idempotency key (R1c, R2b, P14) |

Code enforces the rest: shipping address columns change only when an
`address_change` adjustment is applied (O11), and contact columns only by
erasure (I10).

A migration that adds a column D2e allows backfilling grants the job role
`UPDATE` on that column for the backfill; the next release revokes it.
*Why:* O9 and P10 make these values immutable, and code alone makes that
true only on the paths someone reviewed. A column the grant does not list
cannot be changed by any path.

**D7b. Every write to a table governed by D7 or D7a names its columns.**
PostgreSQL checks a column grant against the columns in the `SET` list whatever
the values are, and Django's `Model.save()` writes every field by default — so
one ordinary `save()` on an order is refused by the grants, and so is every
Django admin change form, which saves the whole model.

- Domain services write through `QuerySet.update()` or
  `save(update_fields=[...])`. A bare `save()` on these models is forbidden
  (checked statically, W8a). Inserts are unaffected: these grants restrict
  `UPDATE` and `DELETE`, not `INSERT`.
- **No `auto_now` column on a model these grants govern**, unless the grant
  lists it and every write names it. `update_fields` skips an `auto_now` field
  that is not listed, so an `updated_at` here goes stale silently — and a stale
  column is worse than an absent one the moment something sorts or filters on
  it (Q2b).
- These models are **never edited through an admin change form.** `Order`,
  `OrderItem`, `Payment`, `Refund`, `OrderAdjustment`, invoices and notes and
  every append-only table are read-only in the admin; changes go through admin
  actions calling the domain services, exactly as C9 already requires for stock.
- A test asserts the database refuses a full-column save of a committed order.

*Why:* D7 and D7a are the enforcement layer most of this file leans on, and as
written they are unusable through the ORM's default write path — a fact that
surfaces the first time staff save an order, not in CI, because the
clean-install test (W8) only opens the login page. Found then, it is a write
discipline retrofitted through every service and every form, or the grants get
dropped, which is the same as never having had them.

---

## 13. Error handling

**X1. Never catch bare `Exception`. Never write `except: pass`.** Catch what
you know how to handle; otherwise let it propagate (checked statically, W8a).
*Why:* a swallowed exception destroys the error where you had the most
information about it.

**X2. Never return `None` to signal failure in the domain layer.** Raise a
domain exception.

**X3. An `except` block either recovers meaningfully or re-raises after
logging.** "Log and continue" only where the operation is genuinely optional,
with a comment saying why.

**X4. Catching an exception around a payment, stock or order write and
continuing is forbidden**, except the named unique violation in X11a.

**X5. All business-rule failures raise a subclass of `DomainError`, each
bound to one code in the error-code registry (X5a)** — `OutOfStock`,
`InvalidTransition`, `RefundExceedsPaid`, `DiscountNotApplicable`,
`PaymentVerificationFailed`, `PriceChanged` and the rest of the registry.

**X5a. Every error code is declared once, in one registry in core**, with its
HTTP status, its exception class and the shape of its `details` (X7). No code
is raised or returned that is not in the registry, and the error reference in
the buyer docs is generated from it. The status for each code is fixed here:
409 when the request conflicts with current state, 422 when a business rule
refuses valid input (X9). At minimum:

| Code | Status | Raised by |
|---|---|---|
| `validation_error` | 400 | schema, size and range checks (Q3c), unknown filter or sort (Q2b) |
| `unauthenticated` | 401 | missing or invalid credentials (A3) |
| `payment_verification_failed` | 401 | webhooks only (X12) |
| `permission_denied` | 403 | a privileged action without its named permission (A6a) |
| `not_found` | 404 | no such object, or one the caller may not access (X9) |
| `payload_too_large` | 413 | body over its cap (Q3c, A10) |
| `rate_limited` | 429 | A9, V1a, V1b |
| `invalid_transition` | 409 | S1, S2 |
| `price_changed` | 409 | M6, M6a, G4 |
| `confirmation_token_invalid` | 409 | used, expired or foreign token (M6) |
| `idempotency_in_progress` | 409 | C10, C10a |
| `idempotency_conflict` | 409 | same key, different body (C10) |
| `out_of_stock` | 422 | C2, C2a, C4b, S1c |
| `variant_unavailable` | 422 | O7 |
| `quote_incomplete` | 422 | M5 |
| `discount_not_applicable` | 422 | G6 |
| `refund_exceeds_paid` | 422 | R1a, R1c |
| `dispute_open` | 422 | R2c, R1c |
| `fraud_blocked` | 422 | V6, S1c |
| `cod_unavailable` | 422 | V8 |
| `provider_disabled` | 422 | N2 |
| `checkout_disabled` | 503 | N1 |
| `service_unavailable` | 503 | lock or statement timeout (T4a); retryable |
| `internal_error` | 500 | anything unhandled |

*Why:* X8 makes codes public API. A list kept in prose next to the exceptions
drifts; one registry means a frontend can rely on every code it was told about
and never meets one it was not.

**X6. Domain code raises domain exceptions only.** It never raises HTTP errors
and never imports from the API layer (checked statically, W8a).
*Why:* the same services are called by the API, the admin, MCP tools and
management commands.

**X7. Every error response uses one shape:**
```json
{"error": {
  "code": "out_of_stock",
  "message": "...",
  "field": "variant_id",
  "fields": [{"field": "lines[2].quantity", "code": "max_value", "message": "..."}],
  "details": {},
  "request_id": "..."
}}
```
`code`, `message` and `request_id` (X10a) are always present. `field` names a
single offending field; `fields` lists each one when validation fails on
several. `details` appears only where the registry (X5a) declares it:
`price_changed` carries the new quote, the `confirmation_token` (M6) and, where
a discount is why the price changed, the G6 reason (G4),
`out_of_stock` names the short lines by the public id the request used — a
cart line at checkout, an order item afterwards (C4b, Q3a),
`discount_not_applicable` carries the G6 reason. `message` is rendered in the
request's language (L3a); `code` never changes with language.
*Why:* a frontend branches on `code` and shows `message`. A code that changed
with language would break the first, and an untranslated message the second.

**X8. Error codes are part of the public API contract.** Changing or removing
one is a breaking change requiring a version bump; adding one is not.

**X9. Error classes map to status codes:**

| Class | Status | Meaning |
|---|---|---|
| Validation | 400 | malformed input |
| Authentication | 401 | no or invalid credentials |
| Authorization | 403 | authenticated, but lacks a named permission (A6a) |
| Not found | 404 | does not exist, **or exists but the caller may not access it** |
| Too large | 413 | body over its cap |
| Domain rule | 409 / 422 | 409: conflicts with current state; 422: a business rule refuses valid input — fixed per code (X5a) |
| Rate limited | 429 | carries `Retry-After` |
| Infrastructure | 500 / 503 | our fault or a dependency's; 503 is retryable |

*Why:* answering 403 for someone else's order confirms that order exists.
Order numbers and guest links (O6, A8) must not become an existence oracle.

**X10. Responses never leak internals.** `DEBUG=False` in production. No stack
traces, SQL, exception class names or file paths. Internal identifiers are not
exposed to clients merely because they appear in logs.

**X10a. Every request gets a random `request_id`**, generated server-side,
returned in the `X-Request-ID` header and in every error body (X7), and
attached to every log line and error report for that request. An inbound
`X-Request-ID` never replaces it. If the inbound value is at most 64
characters of `[A-Za-z0-9._-]`, it is logged alongside as
`upstream_request_id`; otherwise it is dropped.
*Why:* support can go from a customer's screenshot to the exact log line
without any internal identifier leaving the system. Keeping a valid upstream
id preserves tracing across a proxy or frontend; validating it keeps a client
from writing arbitrary text into the logs.

**X11. Never catch an exception inside `transaction.atomic()` and continue.**
*Why:* Django marks the transaction broken and every later query raises
`TransactionManagementError`, burying the real error.

**X11a. The one exception to X4 and X11: a named unique violation.** Code may
catch `IntegrityError` for one named constraint, only when raised inside an
inner `transaction.atomic()` block (a savepoint) wrapping the insert, and only
to retry with a new value (O6 order numbers) or to treat the request as a
replay of the existing row (C10, P5, T2b, G1). A violation of any other
constraint re-raises.
*Why:* insert-first uniqueness is how D5 is enforced, so the collision has to
be caught somewhere. The savepoint is what leaves the outer transaction
usable; without it, X11's broken-transaction problem returns.

**X12. Webhook responses follow this table exactly:**

| Situation | Response | What we do |
|---|---|---|
| Body over the cap (A10) | 413 | nothing parsed, nothing written |
| Signature invalid (P2) | 401 | nothing written |
| Timestamp outside the skew window (P4) | 401 | nothing written |
| Live/test mode mismatch (P2b) | 401 | no event written; alert (N5) |
| Valid, processed | 200 | `applied` or `no_op` (P5b) |
| Valid, already processed (`processed_at` set) | 200 | no side effect |
| Valid, an event type the adapter declares ignored (P7) | 200 | `no_op`, no alert |
| Valid, unprocessable — unknown payment (P5c), undeclared event type (P7) | 200 | `unprocessable`, alert (N5) |
| Valid, transient failure | 500 | receipt kept (P5); processing retried by the provider or the replay path (P6) |

Most providers retry any non-2xx response for days; the table states what
*we* do, never what the provider does. A permanent failure produces an alert
(N5). Logging alone does not satisfy this.
*Why:* 200 on a transient failure silently drops a payment; 500 on a
permanently unprocessable event causes a retry storm.

**X13. Every logged error carries context** — `request_id`, order id, payment
id, provider event id — and no more than needed. Never
`logger.error("payment failed")`.

**X13a. Application logs and error reports identify people by internal id
only** — never email, phone, name or address. Log retention is
`LOG_RETENTION` (I8a). The error tracker's retention and region are settings
(`ERROR_TRACKING_RETENTION`, `ERROR_TRACKING_REGION`), capped by I8a and I9,
and the tracker must be configured to meet them.
*Why:* logs and error trackers are copied to third parties and kept on their
own schedule. Erasure (I10) cannot reach them, so personal data must never
enter them.

**X14. Unhandled exceptions must reach a human.** Error tracking uses the
Sentry protocol, configured by `ERROR_TRACKING_DSN`. A production deployment
(`DEPLOYMENT_ENV = production`) refuses to boot without it; the demo may run
without one.

**X15. Error tracking scrubs secrets, authentication headers, tokens,
passwords, card data and raw payment payloads before transmission.**
*Why:* A12 covers logs. Error trackers receive request and exception context
through a different path.

---

## 14. Fraud and abuse controls

These rules exist because the logic in every section above can work perfectly
while the business is destroyed. Card testing — running stolen card numbers
through a checkout to find which are live — turns an unprotected checkout into
a free validation oracle. The consequence is not a bug report. It is
termination by the payment provider and placement on the MATCH list, which
makes opening a new merchant account nearly impossible for five years.

**Thresholds.** Card-network monitoring programmes (Visa VAMP, Mastercard ECM)
act against merchants whose fraud and dispute ratios exceed thresholds that
differ by region and change most years. The current figures live in the fraud
ADR and the runbook, not here. The rules below keep the ratios down whatever
the figures are.

**V1. Failed payment attempts are capped per identity, per window.** Limits
apply independently to email (A1a), IP (A9b), device fingerprint, order and
principal — the identities the system sees before an attempt starts — and are
enforced at payment initiation. A breach blocks further attempts (V6) and
alerts. Card-level limits are V2.

A device fingerprint is a signal, not an identity: taken from the provider
where it supplies one, otherwise from the client. A client can forge it, so it
is never the only identity a limit keys on.
*Why:* A9 rate-limits by principal, and a guest principal is free to create.
An attacker makes a new guest identity per attempt unless the limits key on
something they cannot mint.

**V1a. Default failed-attempt limits**, configurable per deployment. The
windowed limits are counted in the rate-limit store (A9). The per-order limit
is not: it has no window, and that store's rows are pruned per window (A9), so
a lifetime cap kept there resets on the next prune. It is a count of the
order's `failed` payment attempts (P13), read under the order lock at
initiation.

| Identity | Failed attempts | Counted by |
|---|---|---|
| email | 5 / hour | rate-limit store (A9) |
| IP | 10 / hour | rate-limit store (A9) |
| device fingerprint | 10 / hour | rate-limit store (A9) |
| order | 5 in total | the order's `Payment` rows in `failed` |

**V1b. Payment initiation is rate-limited regardless of outcome**: default
5 / 10 min per order and 20 / hour per IP, configurable.
*Why:* a card-testing bot can open sessions it never completes. Counting only
failures misses it.

**V2. Repeated authorization attempts against the same card are blocked.**
Card entry happens at the provider (P18), so this system cannot stop a card
being tried:
- **Blocking at the card is a declared adapter capability** — the provider's
  own velocity rules, configured by the adapter. The app logs a boot warning
  when an enabled provider lacks it.
- **The system records the card fingerprint and outcome from each
  authenticated event**, and once one card fails repeatedly, blocks further
  attempts on the same order, email and device (V1a).
*Why:* beyond the fraud exposure, networks bill per retry above a per-card
daily count. A card-testing run bills real money before a single chargeback
arrives.

**V3. Card testing detection runs on a rolling window** and alerts on the
signal pattern: many distinct cards from one IP, device or session; an
abnormal decline rate; a spike in small-value orders; many attempts with no
completed order. The thresholds are settings, and V3 does not ship until the
phase that builds it has set their defaults.

On detection it alerts (N5), and for `CARD_TESTING_ESCALATION_PERIOD`
(default 24 hours) every new attempt is escalated to a 3-D Secure challenge
where the provider supports it (V4). **Detection never trips the kill switch
(N1)**; that is a human decision.
*Why:* a false positive that closes the store costs more than a day of
escalated challenges.

**V4. 3-D Secure is configurable per deployment and mandatory above a
configured order value.** Failed-attempt breaches (V1) and card-testing
detection (V3) escalate the next attempt to a 3-DS challenge. Each adapter
declares whether it can require 3-DS; **the app raises at boot if a 3-DS
threshold or escalation is configured for a provider that cannot enforce it.**
*Why:* 3-DS shifts liability for fraudulent chargebacks to the issuer. It is
the single biggest lever on the dispute ratios.

**V5. AVS and CVV results are recorded on every attempt where the provider
returns them.** The CVV itself is never received (P18) — only the provider's
result code. A configurable policy may reject on a mismatch; it applies only to
results present, and an absent result is never a mismatch.
*Why:* they are the baseline filter against low-effort fraud where available,
and the stored result is dispute evidence under R6. AVS is largely unavailable
outside a few markets, so absence must not read as failure.

**V6. Fraud signals never silently discard a legitimate order.** A blocked
attempt returns `fraud_blocked` (X5a) with a clear message, and every block is
logged with its triggering rule for review.
*Why:* false positives are lost revenue the client will never see unless the
block is visible.

**V7. Every payment attempt carries a `FraudAssessment`**: rules fired,
signals seen (identities, AVS/CVV results, 3-DS outcome), and the decision. A
COD order (V8) carries one made at placement, on the `Payment` row P13b creates
for it; a `zero_total` order (S1c) has no payment row, so its single assessment
hangs on the order. Append-only (D7).
*Why:* an order may have several attempts, each judged on different signals.
The client needs to know why one was blocked, and it is dispute evidence.

**V8. COD abuse controls.** COD allocates stock when the order is committed
(C2a) and takes no payment, so placing COD orders costs an attacker nothing.
- **Open COD orders** — not cancelled, with payment still `unpaid` — are
  capped per normalized phone, email (A1a) and IP: default 3 each. This is a
  gauge, not a windowed counter: it falls when an order is paid or cancelled,
  so the A9 store cannot hold it.

  **Its concurrency boundary is a `PlacementGuard` row per normalized
  identity** — one row per (identity type, identity value), unique by
  constraint (D5), created on first use and never deleted. A COD placement
  locks the guard rows for its phone, email and IP **before the order** (S5),
  counts that identity's open COD orders under the lock, and refuses the
  placement on a breach. Nothing else is a boundary: a gauge has no counter row
  to increment atomically (A9) and counting open orders without a lock lets
  parallel requests all read the same count and all pass.

  The guard row holds the normalized identity, so it is personal data: erasure
  replaces the value with the subject's pseudonym, as it does
  `DiscountRedemption.scope_key` (I10b). It references no order and belongs to
  no aggregate (I8).
- **`COD_MAX_ORDER_TOTAL`** caps a COD order's total. It is required whenever
  COD is enabled (F1a).
- **A phone with `COD_REFUSAL_LIMIT` refused shipments (S8) within
  `COD_REFUSAL_WINDOW`** (defaults 2 and 180 days) is not offered COD. The
  count is a query over shipment history, not a counter: a refusal is recorded
  days before the placement it blocks, so there is no race to serialize. Staff
  with `resolve_review` may lift the block with a recorded reason.
- Phones are normalized to E.164 by one function, used by every comparison.
- A breach refuses COD with `cod_unavailable` (X5a); other methods stay
  available.

Phone verification by OTP is out of v1.
*Why:* fake COD orders are the COD equivalent of card testing: no chargeback,
but stock locked, courier fees paid and refusals absorbed. In COD-heavy
markets it is the more likely attack.

---

## 15. Operational safety

**N1. A kill switch stops new checkouts while leaving the site readable.**
A single runtime flag (F1c), changeable without a deploy.

| Stops | Keeps working |
|---|---|
| new orders, for every method, COD and `zero_total` included | catalog browsing and search |
| new payment attempts, including O11 difference links | the admin and every admin action |
| | webhooks and reconciliation (T6, T7) |
| | the return-page check (P1a) |
| | refunds |

A stopped request returns `checkout_disabled` (X5a). TTLs keep running: an
adjustment awaiting payment may expire while the switch is on.
*Why:* when card testing starts, a pricing bug ships, or the provider
misbehaves, the alternative is taking the whole site down or watching it
happen. Webhooks must keep working so in-flight payments still resolve.

**N2. Payment providers are individually disableable** without a deploy, so a
misbehaving gateway can be removed while others keep taking orders. Disabling
stops **new attempts only**: that provider's webhooks, reconciliation and
refunds continue (R2a). P13a never reuses a live session on a disabled
provider; a pay request for that order cancels it where the adapter can, and
the customer chooses another method or receives `provider_disabled`.
*Why:* refunds must go back to the instrument that paid. Disabling a provider
must not strand them or the payments still in flight.

**N3. Health is split in three:**
- **`/health`** — public, liveness only: 200 when the database is reachable,
  503 otherwise. No detail in the body. **Job staleness never appears here**,
  and this is the endpoint a platform health check may point at.
- **`/health/jobs`** — public, one boolean: 200 when no job is stale (N4a),
  503 when one is. No job names, no timestamps, no detail.
- **`/health/detail`** — authenticated by a staff session or a configured
  monitoring token: the last successful run of each job, the core version
  (W3), and open critical alerts (N5). The monitoring token is a secret
  (A11, A12, X15), grants access to `/health/detail` only, and rotates with
  two active tokens during a configured window, as A4c does for signing keys.
*Why:* a stopped job loses money silently, so something outside the app must
see it — but a late reconciliation job is not a dead instance. Folding
staleness into the liveness probe makes a platform health check restart or
de-pool healthy web workers because a cron job ran long, which turns a
monitoring signal into an outage. Two public endpoints keep both facts visible
and separate, and neither reveals which job or which version.

**N4. Every scheduled job alerts if it has not completed within its expected
window (N4a).** Reservation release, payment reconciliation, settlement
reconciliation, backup restore verification, rate-limit window pruning,
stock ledger reconciliation (C8), allocation review aging (C6b), idempotency
key pruning and in-progress sweeping (C10, C10a), intent sweeping (T2a),
notification sending (T2b), abandoned unpaid order cancellation (S2b),
retention pruning (D6), dispute deadline warning (R4), return ship-back expiry
(R8), adjustment payment expiry (O11), unprocessed-event report (P6),
card-testing detection (V3), invoice submission and reconciliation (I5a),
deferred erasure completion (I10a), alert notification (N5).
*Why:* the rules in this file assume these jobs run. A job that silently
stopped makes several invariants false with no error anywhere.

**N4a. Every job is declared once, in one job registry in core**: name,
schedule (in UTC, L1a), and maximum staleness. N4, `/health/jobs` and
`/health/detail` read it (N3); no job is scheduled outside it.
*Why:* "expected window" means nothing until each job states one, and a job
nobody registered is a job nobody monitors.

**N5. An alert is a durable row, not a log line.** Every "alert" in this file
means this. `Alert` holds a code from a closed set in core, severity
(`critical | warning`), a reference to the domain row it concerns, status
(`open | acknowledged | resolved`) with a typed actor for each change (S4),
and timestamps.

- Written in the same transaction as the condition it reports.
- Unique on (code, subject) while open (D5): a retry updates the open row
  instead of adding another.
- A job notifies staff through a channel adapter (email in v1) to
  `ALERT_RECIPIENTS`, at-least-once, as T2b does for customers.
- Listed in the admin, where staff acknowledge and resolve them.
- The subject reference is a **typed pair — subject type and identifier, never
  a foreign key** — because alerts name rows across every table in the system,
  and a foreign key would make a resolved alert block that row's retention
  delete forever (O7, I8, as C8a says for the ledger).
- Resolved alerts are pruned under `LOG_RETENTION` (I8a) by the retention job.

*Why:* an alert that lives in a log is read by nobody. One that lives in the
database can be counted, acknowledged, reported by `/health/detail` (N3), and
cannot be lost with a crash.

**N6. Every deployment with customers has an external uptime monitor polling
`/health`, and a second, separate check polling `/health/jobs`** (N3). Both are
mandatory steps in the setup guide, and they alert separately: `/health`
failing is an outage, `/health/jobs` failing is a stopped job.
*Why:* N4 runs inside the app, so a dead worker also kills the job that
notices dead workers. Only something outside the app can see that — and it has
to tell the two apart, or the first late job trains the client to ignore the
monitor.

---

## 16. Invoicing and compliance

An `Order` is not an invoice. Most VAT/GST jurisdictions require a formal
document with its own rules, and some require it cleared or filed with a tax
authority before it is legally valid.

**I1. `Invoice` is a separate entity from `Order`, and is immutable once
issued.** No edits, no deletes, ever — enforced by grants (D7); deletion
happens only at the end of retention (I8).
*Why:* an invoice is a legal document, not a view of current order state.

**I1a. The tax-authority adapter declares when an invoice is issued.** Core
default: when the order's payment status first reaches `paid` — for COD, when
cash collected is recorded (P1, item 3); for a `zero_total` order, at commit
(S1c). An adjustment applied before issuance issues no note (O10); the
invoice, when issued, reflects the effective totals.

**Issuance happens in the transaction that moves payment status to `paid`**,
under the `invoice_sequence` lock (S5, where it is last). Where that
transaction cannot carry it, the paid-order invoice sweeper (T2a) issues it.
*Why:* jurisdictions tie the invoice to the sale, the payment or the supply.
That is jurisdiction logic, and it belongs in the adapter. And a paid order
with no invoice is a legal document missing, while I3's gapless numbering
makes "issue it later" a lock on the sequence either way — so the sweeper is
the recovery path the Enforcement principle requires.

**I1b. v1 issues B2C documents only.** The adapter declares the document type
for a B2C sale — full invoice, or simplified invoice or receipt. Buyer tax
registration and B2B invoices are out of v1.

**I2. Corrections are new linked documents** — credit note (reduces) or debit
note (increases) — each referencing the original invoice.
*Why:* I1 means a refund cannot amend the invoice it reverses.

**I3. Invoice numbering is sequential, gapless within its series, and never
reused.** The number is assigned in the transaction that moves a document to
`issued`, under the `invoice_sequence` lock (S5); a draft has no number. A
document later `rejected` keeps its number, and that number is never issued
again. A series is configurable per deployment. Credit and debit notes follow
the same rule in their own series.
*Why:* gaps and reuse are audit findings in most jurisdictions. Numbering a
draft that is later abandoned would leave a gap.

**I4. An invoice snapshots everything needed to reproduce it** — seller legal
identity and tax registration, buyer details, per-line description, quantity,
unit price, tax category, rate and amount, totals, currency, issue date. It
never reads live configuration (O4).

**I5. Tax-authority integration is an adapter behind a port**, like payments.
Where a jurisdiction requires clearance or filing, the adapter owns the
protocol, the signing, and the returned identifiers; the domain owns the
document.
*Why:* clearance regimes differ per country and change often. One adapter per
jurisdiction, zero changes to the invoice model.

**I5a. Submission to a tax authority follows the outbound payment rules.** The
document row and its submission key are committed before the call (T1, P14);
every retry reuses the key. A timeout or ambiguous answer never means
`rejected` (P15): the document stays `submitted` until a reconciliation job
(N4) resolves it. `rejected` alerts (N5).
*Why:* an authority that accepted a document we recorded as failed receives
a duplicate on resubmission — the same hole P14 and P15 close for money.

**I5b. Core ships a "no authority" adapter.** Documents are `issued` and
never submitted. It is the default where no jurisdiction requires clearance.

**I6. Where a jurisdiction assigns identifiers** — an authority UUID, hash or
signature — they are stored alongside the invoice, and the exact submitted
payload is retained verbatim.
*Why:* regenerated documents fail signature verification. The original bytes
are the record.

**I7. Issuance state is explicit, for invoices, credit notes and debit notes
alike**, with this closed transition set, enforced by trigger (D7):

| From | To |
|---|---|
| `draft` | `issued` |
| `issued` | `submitted`, `cancelled` |
| `submitted` | `accepted`, `rejected` |
| `accepted` | `cancelled` |

`rejected` is terminal: a corrected document is issued as a new one, with a
new number (I3). `cancelled` happens only through an authority mechanism the
adapter declares; otherwise a correction is a credit note (I2). A rejected
document, or one the adapter requires submitted that is not yet accepted, is
never presented to the customer as valid.

**I8. Retention is configured per deployment and enforced** by the retention
role (D6), defaulting to the longest plausible requirement rather than the
shortest.

Retention deletes whole aggregates, never a row with surviving references.
O7's `PROTECT` refuses any other order, so the retention job deletes each row
before the rows it references — **which is not the order they were written
in**: notifications, credit and debit notes, refunds, disputes, payment events,
fraud assessments, payments, adjustments, invoices, shipment items, shipments,
return requests, cancellation requests, review cases, order status logs,
discount redemptions, reservations, order items, then the order.

Three of those positions are counter-intuitive and each is a `PROTECT` failure
if got wrong: notes reference both the invoice and the adjustment that caused
them, so they go before both; a difference payment references the adjustment it
pays for (P10), so payments go before adjustments; and a fraud assessment hangs
on a payment row (V7, P13b), so it goes before payments. The list is the
expected result, not the proof — the proof is a delete of a fully exercised
order in the test suite, because a hand-kept order goes stale the first time a
phase adds a table.

Two kinds of row reference an order and are deliberately **not** part of
the aggregate, and neither may block the delete: stock movements, which name
their cause by copy rather than by foreign key and are retained with their
variant (C8a), and alerts, which name their subject the same way and are pruned
on their own clock (N5, I8a).

Every table that references an order is in one of those three groups — the
aggregate, or one of the two exceptions. A phase that adds a fourth adds it to
this list, or the delete it blocks is discovered years later (D2, W6).
*Why:* a retention job is written once and first runs years later, against
`PROTECT` on every FK. Left to the implementer it either fails silently behind
N4 or is made to work by weakening a foreign key that history depends on.

**I8a. Retention is set per data class:**

| Class | Setting | Default |
|---|---|---|
| Tax records: orders, invoices, notes | `RETENTION_TAX_RECORDS` | 10 years |
| Raw payment events (P9) | `RETENTION_PAYMENT_EVENTS` | 2 years |
| Fraud signals: IP, device, assessments (V7) | `RETENTION_FRAUD_SIGNALS` | 1 year |
| Notifications (T2b) | follows its order | — |
| Consent records (I11) | `RETENTION_CONSENT` | 10 years |
| Resolved alerts (N5) | `LOG_RETENTION` | 90 days |
| Application logs (X13a) | `LOG_RETENTION` | 90 days |

Consent records sit with tax records because a consent row is the proof of the
processing it authorised, and it is worth nothing after the record it justifies
is gone. Without a clock of their own, a guest's email would sit in them
forever (I10b).

These are defaults, not legal advice: a deployment's values are confirmed for
its jurisdiction before it takes paying customers. Backups (D4b) and the error
tracker (X13a) are capped by these.
*Why:* "longest plausible" is not a number, and one period for everything
keeps IP addresses as long as invoices.

### Data protection

**I9. Personal data residency, retention and erasure are per-deployment
configuration, not assumptions.** Where personal data may be stored, how long
it is kept, and which jurisdiction's rules apply are settings. They govern
backups as well as the live database (D4b).
*Why:* most data-protection regimes restrict where personal data may sit and
for how long. Hosting choice becomes a compliance decision the moment there is
a real customer.

**I10. Erasure is selective.** An erasure request removes or anonymises
directly-identifying profile and marketing data while retaining the
transactional and tax records the law requires, with the retention basis
recorded. Every erasure is written to the erasure log (D4c).

- **The user row is never deleted** — orders protect it (O7). It is
  anonymised in place: email, name and phone replaced, account deactivated,
  `token_version` bumped (A4b), and every guest token on the user's orders
  revoked (A8a).
- **On retained orders**, personal data stays only where a retained document
  requires it — the invoice snapshot (I4). Contact fields and fraud signals
  (email, phone, IP, device) are anonymised.
*Why:* the right to erasure and the obligation to keep invoices both exist.
Code that treats erasure as `DELETE CASCADE` breaks the second, and is refused
by O7 anyway.

**I10a. Erasure of data an open matter still needs is deferred.** Open
matters: a dispute, a return window (R7), an unpaid COD order, an open review
case. The deferral and its basis are recorded, and a job (N4) completes the
erasure when the last matter closes.
*Why:* erasing the evidence mid-dispute loses the dispute, and erasing the
phone on an undelivered COD order loses the delivery.

**I10b. Erasure has one inventory, and it covers every table that identifies
the subject.** A request is complete only when every row below is handled, and
the erasure log (D4c) records them by internal identifier.

| Holder | On erasure |
|---|---|
| `User` (A1) | anonymised in place: email, name and phone replaced, account deactivated, `token_version` bumped (I10) |
| `Order` contact, copied address and fraud-signal columns | anonymised (I10, D7a); the copied address is personal data too, and only the invoice snapshot keeps its own (I4) |
| `Address` book rows (O3) | deleted — the order copied what it needed, so nothing historical depends on them (O3, O7) |
| `Notification` recipient and stored body (T2b) | recipient replaced with the pseudonym; the stored body deleted, or deferred while an open matter still needs it as evidence (I10a, R6) |
| `Consent.subject`, where it is a guest's email (I11) | replaced with the pseudonym — the one update D7 permits on that table, and only to the retention role |
| `DiscountRedemption.scope_key` (G2) | replaced with the pseudonym; the subject's per-customer limits start fresh from there |
| `PlacementGuard` identity value (V8) | replaced with the pseudonym; the subject's COD gauge starts fresh from there |
| `Invoice`, `CreditNote`, `DebitNote` snapshots (I4) | retained, with the retention basis recorded (I10) |
| `PaymentEvent` raw bodies (P9) | retained under P9's access control until `RETENTION_PAYMENT_EVENTS` (I8a), with the basis recorded |
| Application logs and error reports | nothing to erase: they never held personal data (X13a) |

The **pseudonym** is one opaque value per erasure, stable across the rows above
so the records stay countable, and resolving to nobody. The erasure job writes
`Consent.subject` through the retention role's connection (D6, D7); every other
row on the list it writes as the job role.

*Why:* an inventory naming only the user row and the order leaves the subject's
email sitting in consent, redemption and notification rows — and for `Consent`
the append-only grant made it not merely forgotten but impossible, with no
retention clock to remove it either. A rule the database forbids is worse than
one nobody wrote: it fails at the first request, in front of a regulator.

**I11. Consent is recorded as `Consent` rows**: subject (a user, or a guest's
normalized email), scope, the wording version shown, given or withdrawn,
timestamp, source (checkout, account, admin). Withdrawal is a new row, never an
edit (D7). Current consent is the latest row per subject and scope; no boolean
on the user stands in for it.
*Why:* a boolean records the answer but not the question, when, or where —
which is what a regulator asks for.

**I12. A personal-data export produces everything held about a subject**, in a
machine-readable format. In v1, staff start it from the admin after verifying
the requester, it runs as a job producing a file (Q2c), and staff deliver it.
No self-service export in v1.

---

## 17. Locale and time

**L1. Every deployment has an explicit store timezone**, and all business-day
boundaries — reports, "today's orders", cutoffs — are computed in it.
*Why:* "today" is undefined otherwise, and daylight-saving transitions silently
shift report boundaries. Reports that disagree with the client's own counting
is a trust problem.

**L1a. Jobs are scheduled in UTC (N4a).** A job tied to a business day —
reports, day-boundary cutoffs — runs keyed on the store-local date and is
idempotent per date.
*Why:* a job scheduled in local time runs twice or not at all on the night the
clocks change.

**L2. All timestamps are stored in UTC and converted at the edge.**

**L3. Each deployment installs a set of languages, each with its text
direction; the customer chooses one.** Customer-facing documents and messages
— invoices, receipts, emails, error messages — render in the order's language
(O8), or the language resolved by L3a where there is no order.
**Exception:** where the tax-authority adapter requires invoices in a specific
language (I5), the invoice renders in that language as well — bilingual when it
differs from the customer's.
*Why:* customers read documents in the language they chose, and some
jurisdictions legally require the invoice in theirs. Retrofitting translation
and RTL into hardcoded strings is a rewrite.

**L3a. The language is resolved in this order**, first match wins:
1. the order's language (O8), for anything about an order;
2. the user's `preferred_language`;
3. `Accept-Language`, limited to installed languages;
4. `STORE_DEFAULT_LANGUAGE`.

**L4. No user-facing string is hardcoded in the domain layer.**

**L5. Customer-facing catalog text lives in translation tables**, one row per
(object, language) — product name and description, variant and option labels,
category names, shipping method names; for example
`ProductTranslation(product, language, name, description)`.
- A missing translation falls back to `STORE_DEFAULT_LANGUAGE`. A product
  cannot be activated without its default-language translation.
- Search (Q3d) indexes each language's rows.
- Libraries that add a column per installed language are not used (D2f).
*Why:* O1 copies names in the order language and Q3d searches per language;
both need the content to exist per language. Adding it after launch is a
migration on every catalog table.

**L6. Numbers, dates and amounts in documents and messages are formatted per
language by one formatter in core** (Babel). Amounts use the M1a exponent,
never a formatter default.
*Why:* a formatter's default precision is two decimals, which is wrong for
KWD and JPY.

---

## 18. Release engineering

**W1. Core is a versioned package. Client deployments install and pin it.**
They never hold a copy of core source they can edit.
*Why:* a fix must reach every deployment by changing a version number. Forks
holding editable copies diverge until a security fix cannot be applied at all —
the documented failure mode of this model, which begins to bite at a handful of
clients.

**W1a. Core is distributed from a private git repository, installed by
tag** (`pip install git+ssh://…@vX.Y.Z`), with a read-only deploy key per
client. A private package index may replace it later without changing W1.

**W1b. The admin ships inside core.** One package, one version, one changelog.
A deployment installs core and gets the admin; it never installs or pins it
separately.
*Why:* every client runs the admin, so a second installable adds a second
release line and a second public surface under W4a for no deployment that
wanted it. A headless-only deployment, if one is ever sold, is a setting that
unregisters the admin URLs, not a second package.

**W2. A client deployment contains configuration (F1a), message template
overrides (F3) and adapters for the ports W2a allows.** If a client needs
different domain behaviour, it becomes a config flag or an adapter in core
first (F2).

**W2a. Ports that accept deployment adapters:** payment (P17), courier or
carrier (S8), notification channel (T2b). Tax calculation (M10a) and
tax-authority (I5) adapters live in core only (W7).
*Why:* a courier integration is one client's business. A tax rule is the same
for every client in a jurisdiction.

**W3. Every deployment records the core version it runs**, queryable via
`/health/detail` (N3).
*Why:* the first question in any incident is which version is affected.

**W4. Core follows semantic versioning with a changelog**, and any release
requiring a migration or manual step says so explicitly.

**W4a. Port interfaces are public API.** A change to a port that a
deployment adapter implements is a breaking change under W4.
*Why:* a deployment's adapter breaks on upgrade exactly as a frontend does
when an error code changes.

**W5. Deployments upgrade one minor version at a time.** Skipping versions is
unsupported, because migrations assume ordered application.

**W5a. Fixes, including security fixes, ship only on the latest minor.** A
deployment receives a fix by upgrading to it (W5). This is stated in the buyer
contract.
*Why:* backporting to every minor any client happens to run grows with each
client and each release.

**W6. A deployment mid-upgrade is never broken** — migrations follow D2.

**W7. Compliance logic lives in core, never in a client deployment.** Tax,
invoicing, data protection, consumer-law windows.
*Why:* these change by regulation, identically for every client in a
jurisdiction. In a fork they cannot be shipped to the fleet reliably.

**W8. Every core release passes the same CI gates**, none skippable: the test
suite; `makemigrations --check` (D2f); the blocking-migration check (D2b); the
static checks (W8a); the upgrade-path test from the previous minor (Definition
of done — not applicable to the first release); a clean-install test — the
built core package installs into a blank deployment skeleton and boots with
default settings, with the admin login page responding (W1, W1b); `pip-audit`
against the locked dependencies; a lockfile pinned with hashes.
*Why:* a gate that can be skipped under deadline is skipped on the release
that needed it.

**W8a. Static checks enforce what tests cannot**, using ruff, import-linter
and small AST checks in core:
- no assignment to a status field outside `transition_to()` (S3, S6), and
  none to `variant.stock` outside the stock service (C9);
- no setting read outside the registry (F1a);
- domain code imports no payment provider, no API layer and no HTTP library
  (P17, X6, T4);
- money columns use core's one money field type; `FloatField` is forbidden,
  and `DecimalField` is allowed only on an explicit allowlist of non-money
  columns (M1);
- no bare `except` and no `except: pass` (X1);
- no `CASCADE` or `SET_NULL` on a foreign key to a history-referenced model
  (O7);
- no bare `save()` on a model governed by D7 or D7a — every write names its
  columns — and no admin change form able to save one (D7b).
*Why:* each of these is one line of code that passes every test and breaks a
rule. A test proves a path works; a static check proves no path does the
forbidden thing.

**W9. Core is licensed to each client for use, not modification.** Python
source is readable, so W1 is enforced by the license and by W1a's
distribution, not by technology. The license text is a legal deliverable
required before the first sale.

---

## Definition of done

A phase is done when every item under **Every phase** passes, and every item
under **Rule tests** tagged with a rule in the phase's "Contracts that apply"
passes. An item tagged with several rules applies when any of them is in
scope.

### Every phase

- [ ] Tests pass, including the rule tests for every rule in the phase's "Contracts that apply"
- [ ] Every rule in "Contracts that apply" has at least one passing test or CI gate (W8, W8a)
- [ ] Every new list, detail or admin page has its query-count test, and every new list endpoint its page-cap test (Q1, Q2, Q3)
- [ ] The M11 total invariant holds, in the correct tax mode, in every test touching an order (M11)
- [ ] The failure path was tested, not only the happy path
- [ ] Migrations read by a human, including `sqlmigrate` output and any `RunPython` / `RunSQL` (D1), and applied cleanly to a fresh database
- [ ] Migrations applied cleanly to a database at the previous minor version holding realistic data, and the previous release's test suite passes against the expanded schema (D2, W5) — **not applicable to the first release; this gate and W8's upgrade-path test are enabled from the second**
- [ ] Every W8 CI gate passes
- [ ] The phase's invariant table (Enforcement principle) has no empty cell
- [ ] Nothing outside the phase's stated scope was modified
- [ ] The phase's Assumptions list has been reviewed by the owner
- [ ] Deployed and verified: the smoke script passes — `/health` returns 200, `/health/jobs` returns 200, `/health/detail` reports the released core version, and one happy-path call per new endpoint succeeds — and both external monitors (N6) are green

### Rule tests

Grouped by contracts section. Each item names the rules it proves.

**Money**
- [ ] Client-supplied monetary fields have no effect on any amount (M4)
- [ ] A client-supplied currency has no effect (M3a, M4)
- [ ] Zero- and three-decimal currencies round-trip through pricing, API and adapters unchanged (M1a)
- [ ] Every money column rejects a negative value (M1b)
- [ ] Changing address, shipping method or discount reprices the quote; checkout rejects an incomplete quote (M5)
- [ ] A `price_changed` rejection is confirmed with its token and a fresh key without a key conflict; the token is rejected when prices change again first, once used, or after `CONFIRMATION_TOKEN_TTL` (M6, C10)
- [ ] Checkout reprices outside `atomic()`; the shared HTTP client raises if a tax adapter is called inside the commit transaction (M6a, T1)
- [ ] A line price, discount value or shipping cost changed between the repricing and the commit creates no order and returns `price_changed` with a fresh token (M6a, M6)
- [ ] Non-tax rounding is `ROUND_HALF_UP` at the half-unit boundary; the tax adapter's rounding mode and level are recorded on the order (M7, M10b)
- [ ] Fixed-discount and document-level-tax allocations sum exactly; free shipping never touches lines (M8)
- [ ] Per-line allocated amounts sum exactly to the order-level totals (M9)
- [ ] A mixed-tax-category basket totals correctly in both tax modes (M10, M11)
- [ ] A dispute fee in a currency other than the order's is recordable (M13)
- [ ] A chargeback on a partly-refunded payment is recordable (M13)
- [ ] A repricing whose inputs changed under the cart lock is discarded and re-run, and cannot overwrite a newer quote (M5)
- [ ] M11 holds on effective totals after a `collection_adjustment`, with the difference outside every line and every tax base (M11, P13c, O10)
- [ ] Every adjustment delta is derived from the before and after snapshots, and every stored money column on an adjustment still rejects a negative value (O10, M1b)

**Orders**
- [ ] Historical order values are unchanged after pricing, tax, shipping, coupon or saved-address changes (O3, O4)
- [ ] Deleting a user, product or variant referenced by an order is refused by the database (O7)
- [ ] A guest order cannot be attached to an unverified account (O5)
- [ ] An order number is 8 characters, never exposes an internal id, and survives a forced collision (O6, X11a)
- [ ] The web and job roles cannot change an order's money, copied or snapshotted columns, or any `OrderItem` column other than its three quantities (O9, D7a)
- [ ] An address change with a positive delta leaves the address unchanged and blocks shipment until paid; payment applies it atomically; expiry restores the original (O11)
- [ ] An address change keeps the order's discount terms: free shipping covers the new shipping cost and the minimum is not re-checked (O11)
- [ ] A `zero_total` order's address change with a positive delta sends a payment link offering provider-confirmed methods only (O11, S1c)
- [ ] Effective totals satisfy M9 and M11 after every adjustment type, and each issues the right debit or credit note (O10)
- [ ] An address change with a negative delta refunds the difference and moves the order to `partially_refunded`; applying an adjustment writes no payment status itself (O11, S1, R1)
- [ ] An expiring or cancelled adjustment cancels its payment attempt in the same transaction, and a capture that arrives on it afterwards lands in `payment_review` as a `superseded_capture` (O11, P13, P13a, S1b)

**Order state**
- [ ] Every payment and fulfilment transition not listed in S1 is rejected (S1, S3)
- [ ] Payment status is computed from order-level aggregates when an order has more than one successful payment (S1)
- [ ] A dispute on a `partially_refunded` or `refunded` payment moves the order to `payment_review`, and the exit status matches the balances (S1, R4)
- [ ] A reinstated chargeback moves `charged_back` back to `payment_review` and the exit matches the restored balances (S1, R5)
- [ ] Each `payment_review` exit row is reached first-match-wins, including a `zero_total` order with `paid_total == 0` (S1, S1c)
- [ ] An order whose refunds plus disputes exceed `paid_total` exits review to `charged_back`, and to `refunded` when nothing was disputed (S1, M13)
- [ ] A capture on an attempt that ended `expired` or `cancelled` moves the order into `payment_review` from `unpaid` and from `failed`, opening its case, and is never rejected as an illegal transition (S1, S1b, P13, P13a)
- [ ] An order cancelled under S2b that then takes a late capture enters review, stays cancelled, and is refunded from there (S1, S2b, R1c)
- [ ] Creating an adjustment payment attempt leaves the order's payment status unchanged (S1, O11)
- [ ] An order whose own attempt expires while an adjustment attempt is still active moves to `unpaid` and releases its reservations, and S2b can still reach it (S1, P13, P13a, C4a, S2b)
- [ ] `uncollected` requires an admin action; the last `received_back` alone does not set it, and it is rejected while any shipment is not `received_back` (S1, S8)
- [ ] A method registered `provider` cannot be marked paid by an admin action (S1a, P1)
- [ ] An order cannot leave `payment_review` while any review case is open (S1b)
- [ ] The sweeper finds an `allocation_failed` case C6a never attempted (S1b, T2a)
- [ ] Leaving an `allocation_failed` review to `paid` allocates in the same transaction, and fails when stock is short (S1b, C6)
- [ ] A zero-total order is allocated and paid at commit, with no `Payment` row and exactly one `FraudAssessment`; short stock creates no order; `zero_total` is refused for an order whose total is above 0 (S1c, C4b, V7)
- [ ] Zero-total orders past `ZERO_TOTAL_ORDER_LIMIT` per email, phone or IP in 24 hours are refused with `fraud_blocked`, and the count is atomic across two workers (S1c, A9, C1)
- [ ] A `zero_total` order in `payment_review` with no successful payment exits to `paid`, not `failed` (S1, S1c)
- [ ] Every transition writes exactly one `OrderStatusLog` row with a typed actor (S4)
- [ ] Fulfilment reaches `fulfilled` when shipped plus cancelled equals quantity, and each derivation row is covered (S1, S6, S7)
- [ ] Every cancellation combination not listed in S2 raises `InvalidTransition` (S2)
- [ ] A second open cancellation request on the same order is rejected by the database; sequential requests succeed (S2)
- [ ] Approving a cancellation requires `approve_cancellation`; its refund needs no `request_refund`, and R1b still applies above the threshold (S2, A6a, R1b)
- [ ] Cancelling an order with an adjustment awaiting payment cancels the adjustment first (S2)
- [ ] Cancellation from `payment_review` is possible only when `allocation_failed` is the sole open case, and returns only consumed stock (S2)
- [ ] Cancelling a `zero_total` order with no successful payment returns its stock and refunds nothing (S2, S1c)
- [ ] A partial item cancellation refunds exactly the line's stored per-unit amounts and does not re-evaluate discount or shipping (S2a)
- [ ] An abandoned provider-method order is cancelled after `UNPAID_ORDER_TTL` and returns its coupon use; a COD order, an order with an active attempt on its own total, or one inside the TTL is left alone (S2b, P13a, G7)
- [ ] Two operations locking the same order, payment and variants concurrently do not deadlock (S5)
- [ ] A refusal moves no stock or money; `received_back` does both (S8)
- [ ] COD cash on a refused shipment is recorded only after the `refused_delivery` adjustment is applied, and the invoice follows it (S8, S1, I1a)
- [ ] A refused COD order ends `paid` when the shipping fee was collected and `uncollected` when it was not (S8)
- [ ] With `COD_REFUSAL_SHIPPING_FEE` off, a wholly refused COD order can end `uncollected` (S8)
- [ ] Every `display_status` row is reachable and the code is never accepted as input (S9)
- [ ] A partly-refunded unshipped order displays `partially_refunded`; a partly-refunded delivered order still displays `delivered` (S9)
- [ ] A COD order carries a `Payment` row from the commit transaction, with no provider key, that reconciliation never polls and that leaves the order's status `unpaid` (P13b, P10, T6, S1)
- [ ] Recording COD cash moves that row `created → succeeded` with `paid_amount` equal to the cash, in the same transaction as `unpaid → paid`, and is refused when the cash differs from the effective total (P13b, S1, O10)
- [ ] Cash short of the effective total is recorded after a negative `collection_adjustment`, the order reaches `paid`, and the invoice carries the amount collected; cash over it works the same way; the adjustment requires `collect_cash` and a reason, moves no stock, returns no coupon use, and cannot take the effective total below 0 (P13c, S1, O10, I1a, G7, A6a)
- [ ] A `collection_adjustment` is refused on a provider-confirmed method (P13c, P11)
- [ ] A full refund of an order carrying a `collection_difference` sums exactly: the difference appears as its own line on the refund and the credit note (P13c, R2b, R1c, M11)
- [ ] Cancelling a COD order, or ending it `uncollected`, moves its payment row to `cancelled` (P13b, S8, S2)

**Payments**
- [ ] Concurrent duplicate webhook deliveries produce exactly one side effect (P5, P5a)
- [ ] A rolled-back processing transaction still leaves a durable receipt (P5)
- [ ] An unprocessed event can be re-driven by an operator (P6)
- [ ] The return-page check and the webhook racing each other produce exactly one transition (P1a, P5a)
- [ ] The return-page check is refused without ownership and at its rate limit (P1a, A9a)
- [ ] Events signed with the previous secret verify inside the rotation window and fail after it (P2a)
- [ ] A live deployment refuses test keys at boot; a mode-mismatched event is rejected (P2b)
- [ ] A signature verifies against the raw bytes of a body whose JSON would reserialize differently (P3)
- [ ] Both too-old and future-dated timestamps are rejected (P4)
- [ ] An event contradicting a terminal state records `ignored_illegal`, changes nothing, and alerts (P5b, P8)
- [ ] An event for an unknown payment is stored as `unprocessable`, returns 200, and alerts (P5c)
- [ ] A declared-ignored event type records `no_op` without an alert; an undeclared type records `unprocessable` and alerts (P7)
- [ ] No payment attempt can be created for an order that is not committed; the expected amount and currency cannot be changed, whether copied from the order or from an adjustment (P10, O11, D7a)
- [ ] A correctly signed event with the wrong amount or currency cannot mark a payment paid (P11)
- [ ] Multiple payment attempts cannot overpay an order (P12)
- [ ] An expired or cancelled only-attempt returns the order to `unpaid` (P13, S1)
- [ ] A definitively rejected session creation fails the attempt and releases the reservation; an ambiguous one leaves it `created` (P13, C4a)
- [ ] A second pay request reuses the live attempt; a changed method cancels it first; a late capture on a superseded attempt lands in `payment_review` with no automatic refund (P13a)
- [ ] An order whose own attempt is live can still open a difference attempt for an `awaiting_payment` adjustment, and neither cancels the other; a second attempt on either payable is refused by the database (P13a, O11, D5)
- [ ] A second `OrderAdjustment` in `awaiting_payment` on the same order is refused, and a further address change is refused while one awaits payment (P13a, O11, D5)
- [ ] A retried session-creation call reuses the attempt's key (P14)
- [ ] A provider timeout cannot mark a payment failed (P15)
- [ ] Each reconciliation result applies exactly the effect in P15's table, for attempts and refunds, and an indeterminate payment resolves without violating P1 (P15, P16)
- [ ] A refund on a COD order attaches to its payment row and is bounded by the cash recorded, not by the order total (P13b, M13, R1a)

**Refunds, returns and disputes**
- [ ] Concurrent refunds cannot exceed the refundable balance, counting refunds still in progress and awaiting approval (R1a, R1b, M15)
- [ ] A refund above the threshold enters `pending_approval`; the requester cannot approve their own; a declined approval ends `rejected` and is not retried in place (R1, R1b)
- [ ] `refunded_amount` moves only on confirmation, and back down on a reversal, which alerts (R1, R2)
- [ ] A COD refund is confirmed only by a permissioned admin action with a reference (R1)
- [ ] A provider refund cannot target a different instrument (R2a)
- [ ] Refund allocations sum exactly; return fees appear as deduction lines on the credit note, and `Refund.amount` is the net the customer receives (R2b, M13)
- [ ] A refund is refused while a dispute is open on the payment (R2c)
- [ ] An order-level refund on an order holding an original payment and an O11 top-up creates one `Refund` per payment, sums exactly to the event total, and issues one credit note (R1c, R2b, I2)
- [ ] A refund event above the sum of the refundable balances raises `RefundExceedsPaid` and creates nothing (R1c, R1a)
- [ ] A `zero_total` order that took an O11 top-up refunds that top-up when cancelled (R1c, S1c, S2)
- [ ] The named permission and the second approval are checked once per refund event, against its total (R1c, R1b, A6a)
- [ ] A split refund issues one credit note and sends one "refund completed" message; the refund paying out a negative adjustment issues none, because the adjustment already did (R1c, I2, O10, T2b)
- [ ] One row of a split refund failing leaves the other `refunded` and alerts (R1c, R2)
- [ ] A refund event that the remaining payments cannot cover because one is disputed raises `dispute_open`, not `RefundExceedsPaid` (R1c, R2c)
- [ ] Restock defaults to off; a refund without restock moves no stock (R3)
- [ ] An undecided dispute alerts before `evidence_due_by` (R4)
- [ ] A won dispute reduces `disputed_amount`; an inquiry changes no balance (R5)
- [ ] Dispute evidence, including the accepted terms and refund-policy version and the checkout quote hash, is present on every order at creation time (R6, M6a)
- [ ] A return outside the rules is rejected without an override; a decline inside the legal window records the warning (R7)
- [ ] An approved return not received in its window expires; quantities cannot exceed what is eligible (R8)

**Stock and concurrency**
- [ ] Concurrent reservations cannot oversell (C1, C3)
- [ ] Stock can never go negative (C1a)
- [ ] An untracked variant takes no reservation and writes no movement; switching tracking on writes an `initial` movement (C1b)
- [ ] A reservation is created with its attempt before any provider call; with stock short, no provider session opens (C2)
- [ ] A COD order holds a consumed allocation from placement, and cancelling it returns the stock (C2a)
- [ ] Boot fails when `CHECKOUT_SESSION_TTL` is outside an enabled provider's settable range, or a provider cannot set a session expiry (C2b)
- [ ] A reused attempt keeps its reservation expiry; a new attempt resets it to the new session plus grace (C2b)
- [ ] A reservation past `expires_at` but not yet swept is unavailable and cannot be consumed (C3, C4)
- [ ] Reservation expiry racing payment success cannot silently consume stock (C4, C5)
- [ ] A confirmed payment failure releases the reservation immediately; a timeout does not (C4a)
- [ ] An abandoned checkout releases the reservation in the same transaction as `pending → unpaid` (C4a)
- [ ] `allocate_order()` allocates all lines or none (C4b)
- [ ] Two late captures competing for one unit: exactly one is allocated, the other is cancelled and refunded automatically (C6a)
- [ ] Replaying the event or retrying the job produces exactly one system refund per payment (C6a, R1c)
- [ ] Partial availability, an open dispute, a P11 mismatch, or a second open case leaves the case to staff (C6a)
- [ ] With `AUTO_RESOLVE_UNFULFILLABLE` off, every `allocation_failed` case waits for staff (C6a)
- [ ] An `allocation_failed` case open past its threshold alerts (C6b)
- [ ] A ledger/stock mismatch alerts and corrects nothing (C8)
- [ ] A `StockMovement` holds no foreign key to its cause, and deleting the order it names leaves the movement intact (C8a, I8, O7)
- [ ] Stock is read-only in the admin; a manual adjustment requires a reason; a decrease below reserved stock alerts (C9, C9a)
- [ ] A consumption that finds stock short goes to `payment_review` instead of failing (C9a)
- [ ] Two concurrent requests with the same key: one proceeds, the other gets 409 `idempotency_in_progress` (C10)
- [ ] Boot fails when `IDEMPOTENCY_KEY_RETENTION` is shorter than `CONFIRMATION_TOKEN_TTL` (C10)
- [ ] A failed checkout leaves its idempotency key `failed` and the same key is retryable; an abandoned `in_progress` key is swept after `IDEMPOTENCY_IN_PROGRESS_TTL` (C10a)
- [ ] The same key string under a different operation or principal does not collide (C11)
- [ ] A guest checkout retried on an already-converted cart returns its order (C12)
- [ ] An authenticated checkout retried on an already-converted cart returns its order and creates nothing — with the same key after the sweeper marked it `failed`, and with a different key (C12a, C10a, C12)
- [ ] Two concurrent checkouts on one cart with two different idempotency keys produce exactly one order; the database refuses the second (C12a, D5)
- [ ] A worker killed after the order commits and before the key is marked `completed` leaves one order, and the retried key returns it (C12a, C10a)
- [ ] Logging in with a guest cart clears its `session_key` and sets its customer, leaving its lines, public id and token unchanged; an earlier customer cart is left untouched and nothing is merged (C12b)
- [ ] A converted cart is never claimed, and a claimed cart is repriced before it is next shown (C12b, C12a, M5)
- [ ] A checkout in flight under a cart's guest idempotency scope when the claim happens still produces exactly one order, whichever scope the retry arrives under (C12b, C12a, C10a, C11)
- [ ] Cancelling part of a line reduces that line's consumed reservation, and the remaining quantity still passes the fulfilment guard (C4b, S2a, C6)
- [ ] Cancelling a whole line leaves its consumed reservation at quantity 0, and the ledger still reconciles (C4b, C8)

**Transactions and external calls**
- [ ] The shared HTTP client raises when called inside `atomic()` (T1)
- [ ] A task enqueued inside a transaction that rolls back never runs (T2)
- [ ] A task dropped between commit and enqueue is re-driven by the sweeper (T2a)
- [ ] An order that reaches `paid` with no invoice is issued one by the sweeper (T2a, I1a)
- [ ] A notification is written in the same transaction as its change, is never queued twice for one trigger, and survives a crash before sending (T2b)
- [ ] A notification that exhausts its retries becomes `failed` and alerts (T2b)
- [ ] An account message with no order records its own recipient and resolves its language by L3a (T2b, L3a, A1c)
- [ ] A transaction blocked on a lock fails at `lock_timeout` with a retryable 503 (T4a)
- [ ] Reconciliation picks up attempts stuck in `created`, `requires_action` or `pending`, and refunds stuck in `requested` or `sent` (T6)
- [ ] A settlement divergence in either direction raises an alert (T7)
- [ ] A settlement item unmatched past the window alerts; an item reported in another currency is compared unconverted (T7)

**Queries and payload**
- [ ] A list showing `display_status`, available stock or effective totals runs a constant number of queries (Q1a)
- [ ] Paging through a list while rows are inserted never repeats or skips a row; page size defaults to 20 and clamps at 100 (Q2a)
- [ ] A tampered cursor returns nothing the caller could not already see (Q2a, A6)
- [ ] An unknown filter or sort returns 400; every allowlisted filter and sort has an index (Q2b)
- [ ] An export runs as a job and produces a file (Q2c)
- [ ] No response contains an internal primary key or a field outside its schema; cart lines and order items are addressed by public id (Q3a)
- [ ] Every amount in a response carries currency and exponent, including a zero- and a three-decimal currency (Q3b)
- [ ] A body over 1 MB, a cart over 100 lines, or a quantity outside 1..`MAX_LINE_QUANTITY` returns 400 (Q3c)
- [ ] `out_of_stock` at checkout names cart lines the client can map to what it sent; after placement it names order items (C4b, X7, Q3a)
- [ ] Catalog search uses the GIN index (Q3d)
- [ ] No pagination cursor decodes to an internal primary key; every allowlisted sort has its (sort key, public identifier) index (Q2a, Q2b, O6)

**Auth and access**
- [ ] Two emails differing only in case cannot create two accounts, and a guest order attaches regardless of case (A1a)
- [ ] Passwords are stored as Argon2id hashes; a password failing the validators is refused (A1b)
- [ ] Verification and reset tokens work once, expire, and are stored hashed; a reset ends every session and token (A1c)
- [ ] JWT validation rejects bad signatures, algorithms, issuers, audiences, expiry and timing (A3)
- [ ] A token naming any algorithm other than HS256 is rejected (A3a)
- [ ] Reusing a rotated refresh token revokes the whole family (A4a)
- [ ] A deactivated user's unexpired access token is rejected on the next request (A4b)
- [ ] A token signed with the previous key verifies inside the rotation window and fails after it (A4c)
- [ ] The refresh endpoint rejects a request without a valid CSRF token when the refresh token arrives by cookie (A4d)
- [ ] CSRF covers every session-authenticated state-changing operation (A5)
- [ ] Production refuses to boot with `check --deploy` warnings or a wildcard CORS origin, and warns when a CORS origin's registrable domain differs from the API's own (A5a, A4d)
- [ ] An object the caller may not access returns the same 404 as one that does not exist (A6, X9)
- [ ] Each privileged action is refused without its named permission (A6a)
- [ ] A staff account cannot reach the admin without a second factor; an idle session expires (A6b)
- [ ] Client-supplied internal state fields cannot bypass domain services (A7)
- [ ] Guest order access fails with only an order id or number (A8)
- [ ] Bumping `guest_token_version` rejects every earlier guest link (A8a)
- [ ] Logs and error reports contain no secrets, guest or cart tokens, card data or raw payment payloads (A8b, A12, X15)
- [ ] Rate limits hold at their configured boundaries, with concurrent requests across two workers (A9, A9a)
- [ ] A spoofed `X-Forwarded-For` does not change the recorded or rate-limited IP (A9b)
- [ ] Login, registration, reset and guest link requests answer identically for known and unknown emails (A9c)
- [ ] Oversized webhook bodies are rejected before parsing or database work (A10, X12)
- [ ] A missing required secret fails boot (A11)
- [ ] Creating a shipment, recording a courier outcome and recording `received_back` are each refused without their own permission (A6a, S8)
- [ ] Recording an offline refund payout is refused without `collect_cash` (A6a, R1)

**Discounts and coupons**
- [ ] Two concurrent checkouts on a coupon with one use left: exactly one order carries it; the other gets `price_changed` with `exhausted` and no order (G1, G4)
- [ ] The redemption is taken in the order-commit transaction; a failed redemption creates no order, for COD and provider methods alike (G1)
- [ ] Discount values are stored as integers; a percentage outside 1–10000 is rejected; a fixed discount stores `value_currency` and a free-shipping one stores neither (G1a, M2)
- [ ] One customer cannot exceed `max_uses_per_customer` across guest and account checkouts, case variants of the email, or concurrent checkouts (G2)
- [ ] A fixed discount above the discountable subtotal is clamped and no total goes negative, in both tax modes (G3, G3a)
- [ ] `min_order_total` is measured against the discountable subtotal on the store's price basis, excluding shipping — tax included under inclusive pricing (G3a)
- [ ] Free shipping zeroes shipping and shipping tax for every method (G3b)
- [ ] A code that expires between being applied and checkout returns `price_changed` with `expired` and creates no order (G4)
- [ ] A code that expires between the repricing and the commit is caught by the commit's re-assert (G4, M6a)
- [ ] The validity window starts and ends at the right instant in the store timezone, across a DST transition (G4a)
- [ ] A second discount code on the same order is rejected (G5)
- [ ] Every G6 reason is reachable; an inactive code answers `not_found` (G6)
- [ ] A whole-order cancellation releases the redemption and restores both limits; item cancellation, refused delivery, `uncollected`, refunds and returns do not (G7)
- [ ] Boot fails when a fixed discount's `value_currency` differs from `STORE_CURRENCY` (G1a, F1d)

**Client configuration**
- [ ] A missing, mistyped or out-of-range setting fails boot (F1a)
- [ ] Changing `PRICES_INCLUDE_TAX`, a COD refusal setting or the return rules leaves every existing order's totals, refusal handling and return eligibility unchanged (F1b)
- [ ] Only the kill switch and provider toggles change at runtime; each change requires `manage_settings` and writes an audit row (F1c)
- [ ] Boot fails when `STORE_CURRENCY` differs from existing orders or fixed discounts (F1d)
- [ ] A deployment template override renders; an override for a code unknown to core is rejected (F3)

**Migrations and data**
- [ ] A migration that cannot get its lock fails at 3 s and retries, without blocking queued queries beyond that (D2a)
- [ ] A CI check rejects a blocking index or constraint migration on an existing table, and flags a destructive one (D2b)
- [ ] A new snapshot column is `NULL` on orders committed before it existed, and code reading it handles that (D2e)
- [ ] `makemigrations --check` passes in core CI, and no model definition reads a setting (D2f)
- [ ] The release step refuses a flagged destructive migration without a restore-point identifier (D3)
- [ ] The monthly restore test fails when the migration head differs, or when the newest restored order is more than `BACKUP_RPO` behind production's newest at backup time; it passes on a store that took no recent orders (D4)
- [ ] After a restore, every erasure newer than the backup is re-applied before traffic is served (D4c)
- [ ] Every uniqueness invariant has a concurrency test (D5)
- [ ] The web and job roles cannot run DDL (D6)
- [ ] A bare `save()` on an order, payment, refund or append-only row is refused by the database, and the static check rejects it in code (D7b, W8a)
- [ ] No admin change form can save a model governed by D7 or D7a (D7b)
- [ ] The web and job roles cannot delete append-only rows or update columns outside those D7 allows; the retention role can delete only retention-governed rows (D7)
- [ ] The database refuses an `OrderAdjustment` status change outside `awaiting_payment → applied | cancelled | expired`, any document transition not in I7, and a document number set outside the move to `issued` or changed after it (D7, O10, I3, I7)
- [ ] An order's customer can be set once, from empty, and never changed after (D7a, O5)
- [ ] The `confirmation_token` row is unique per cart, and one issued for another cart is rejected (D5, C10, M6)

**Error handling**
- [ ] Every error code raised or returned is in the registry, with its declared status (X5a)
- [ ] Every error body carries `request_id`; `price_changed`, `out_of_stock` and `discount_not_applicable` carry their `details` (X7, X10a)
- [ ] An error message renders in the request language and its code does not change (X7, L3a)
- [ ] An inbound `X-Request-ID` never replaces `request_id`; a valid one is logged as `upstream_request_id` and an invalid one is dropped (X10a)
- [ ] An `IntegrityError` on a named constraint inside a savepoint is retried or treated as a replay; any other constraint re-raises (X11a)
- [ ] Each X12 row returns its status and writes exactly what the table says (X12)
- [ ] Logs and error reports contain no email, phone, name or address (X13a)
- [ ] A production deployment refuses to boot without an error-tracking DSN (X14)
- [ ] A `price_changed` caused by a discount carries the G6 reason in its `details` (X7, X5a, G4)

**Fraud and abuse**
- [ ] Repeated failed payment attempts are blocked across new guest identities (V1)
- [ ] Failed-attempt limits hold per email, IP, device and order at their defaults, and the per-order limit still holds after the rate-limit store is pruned (V1a, A9)
- [ ] Payment initiation is limited even when no attempt fails (V1b)
- [ ] Repeated failures on one card block further attempts on the order, email and device; boot warns for a provider lacking card-level blocking (V2)
- [ ] A card-testing pattern raises an alert within its window, escalates new attempts to 3-DS for its period, and never trips the kill switch (V3)
- [ ] Boot fails when a 3-DS threshold or escalation is configured for a provider that cannot enforce it (V4)
- [ ] An absent AVS or CVV result is never treated as a mismatch (V5)
- [ ] A blocked attempt returns `fraud_blocked` and logs its triggering rule (V6)
- [ ] Every payment attempt, every COD order and every `zero_total` order has exactly one `FraudAssessment` (V7)
- [ ] COD is refused past the open-order cap, above `COD_MAX_ORDER_TOTAL`, and for a phone past its refusal limit, while other methods remain available; boot fails with COD enabled and no maximum (V8)
- [ ] Two concurrent COD placements for one phone already at the cap: exactly one is accepted, and the guard rows are locked before the order (V8, S5, D5)
- [ ] Erasure replaces the identity value on the subject's `PlacementGuard` rows (V8, I10b)

**Operational safety**
- [ ] The kill switch blocks new orders for every method, including COD and `zero_total`, and O11 payment links; catalog, refunds, admin actions, webhooks and reconciliation continue (N1)
- [ ] A disabled provider's webhooks, reconciliation and refunds continue; its live session is never reused (N2)
- [ ] `/health` and `/health/jobs` each reveal no detail beyond their status code; `/health/detail` refuses an unauthenticated request; the monitoring token opens nothing else, and the previous token works only inside its rotation window (N3)
- [ ] Every job in the registry is monitored; a stopped job alerts and `/health/jobs` returns 503 **while `/health` stays 200** (N3, N4, N4a, N6)
- [ ] An alert is written in the same transaction as its cause; a retry never opens a second open alert for the same code and subject (N5)

**Invoicing and compliance**
- [ ] An issued invoice cannot be edited; a refund produces a credit note (I1, I2)
- [ ] An invoice issues on the adapter's trigger, in the transaction that reaches `paid`; an adjustment applied before issuance issues no note and the invoice reflects the effective totals (I1a)
- [ ] Invoice numbering has no gaps and no reuse under concurrency; a number is assigned only at issue, and a rejected document keeps its number (I3)
- [ ] An invoice renders identically after catalog, tax or configuration changes (I4, O4)
- [ ] A submission timeout leaves the document `submitted`; reconciliation resolves it; `rejected` alerts (I5a)
- [ ] A rejected or not-yet-accepted document is never served to the customer as valid (I7)
- [ ] The retention job, as the retention role, deletes only rows past their class's retention (I8, I8a, D6)
- [ ] Retention deletes a whole order aggregate in dependency order; no row with surviving references is deleted, and `PROTECT` is never weakened (I8, O7)
- [ ] The aggregate delete runs against an order that exercised every table in the list — several payments, an adjustment and its note, a return, a dispute, a fraud assessment, a review case, a shipment — and leaves nothing behind (I8)
- [ ] Erasure anonymises the user row, bumps `token_version`, revokes guest links, anonymises order contact and fraud fields, and keeps invoice snapshots (I10)
- [ ] Erasure with an open dispute is deferred and completes when the dispute closes (I10a)
- [ ] Erasure clears the subject from consent, redemption and notification rows as well as the user and the order; the retention role is the only writer of `Consent.subject`, and no other role can change it (I10b, I10, D7)
- [ ] The retention job deletes an order that has stock movements, reservations and a resolved alert against it, and leaves the movements and the alert intact (I8, C8a, N5, O7)
- [ ] Consent records and resolved alerts are pruned on their own clocks (I8a, I11, N5)
- [ ] Withdrawing consent writes a new row; the latest row determines current consent (I11)
- [ ] A data export runs as a staff-started job and produces a machine-readable file (I12)

**Locale and time**
- [ ] Day-boundary reports are correct across a DST transition (L1)
- [ ] A business-day job runs exactly once per store-local date across a DST transition (L1a)
- [ ] An invoice renders in the order language, and bilingually when the adapter requires a legal language (L3)
- [ ] The language resolves in L3a order (L3a)
- [ ] A product cannot be activated without its default-language translation; a missing translation falls back (L5)
- [ ] KWD and JPY amounts format with their own exponent in every installed language (L6)

**Release engineering**
- [ ] A deployment adapter for a core-only port is rejected (W2a)
- [ ] `/health/detail` reports the running core version (W3)
- [ ] The clean-install test boots a blank deployment skeleton with the admin login page responding (W1b, W8)

---

## Enforcement principle

For every invariant in this file, the implementation must be able to name
five things:

1. **The source of truth** — where the authoritative value comes from.
2. **The authorized mutation path** — which service or transition may change it.
3. **The concurrency boundary** — which rows or atomic operation stop a
   competing writer from violating it.
4. **The recovery path** — how an interrupted or ambiguous mutation is
   detected and resolved: reconciliation, a sweeper, a review case, an alert.
   Where the database refuses the bad write outright, that refusal is the
   recovery path.
5. **The enforcement layer** — where the rule is made to hold, preferring, in
   order:
   1. the database — a constraint, grant or trigger;
   2. a CI check (W8a);
   3. a single code path with a test.

   An invariant enforced by code alone states why nothing stronger was used.

If any of the five cannot be named, the invariant is incomplete: stop and ask.

A rule that says "the value must be correct" is not enough. The code must make
it impossible — or transactionally safe — for an untrusted source, an
unauthorized path, or a concurrent writer to make it incorrect.

Every phase file carries one table for the invariants it introduces or
touches, with a column for each of the five. A row that cannot be filled is a
stop-and-ask.

Apply this test to any situation the rules above do not name.

---

## Revision history

**2026-09-18**
- Header: replaced "the stricter reading applies" with the overlap-versus-conflict
  rule, aligning with the stop-and-ask rule in the handoff.
- S1: added the complete payment and fulfilment transition tables, including
  dispute entry from `partially_refunded` and `refunded`, the `charged_back`
  status, and balance-determined exits from `payment_review`.
- S2: completed the cancellation table (COD, `pending`, `failed`,
  `partially_refunded`, `refunded`, `charged_back`, `payment_review`); anything
  unlisted is not cancellable. Corrected "release reservations" to "return
  allocated stock" for paid orders, whose reservations are already consumed (C4).
- C2a: new — COD allocation at order placement.
- Section 4: duplicate P6 resolved; the event-type mapping rule is now P7 and
  P7–P17 renumbered to P8–P18. All cross-references updated.
- Status values normalised to lowercase (`PAYMENT_REVIEW` → `payment_review`).
- V4: fixed the dangling reference to a nonexistent "V0".
- A9: named the shared rate-limit store (atomic PostgreSQL table; not
  `DatabaseCache`); N4 now covers its pruning job.
- Definition of done: added tests for S1, S2, C2a and cross-worker rate limits.

**2026-09-18 (second pass)**
- S1a: new — payment method registry; cash-collection and ship-before-payment
  rules read method facts, not the method code.
- P1 item 3: admin confirmation limited to methods registered `admin`.
- S1: `failed → pending` stays on the same order with a new `Payment` row;
  `pending` resolves automatically, `payment_review` only by a human.
- C2: boot fails if the reservation TTL is shorter than any enabled
  provider's session timeout.
- C2a: allocation happens when the order is committed, not when checkout opens.
- C4a: new — reservation outcomes (`consumed`, `released`, `expired`); a
  confirmed failure releases immediately, a timeout never does.

**2026-09-18 (section 1 review)**
- M1: amounts are 64-bit. M1a: per-currency exponent from one ISO-4217 table.
  M1b: stored amounts are never negative; direction comes from record type.
- M3: dispute fees exempt, with their own currency. M3a: `STORE_CURRENCY`.
  M4: client-supplied currency ignored.
- M5: the snapshot is now a full quote (lines, discount, shipping, tax,
  total), repriced on every input change; incomplete quotes block checkout;
  `CART_SNAPSHOT_TTL` defaults to 30 minutes.
- M6: confirmation token bound to a hash of the new quote.
- M7: `ROUND_HALF_UP` fixed for non-tax arithmetic; tax rounding mode and
  level declared by the tax adapter.
- M8: allocation table for percentage, fixed, free-shipping discounts and
  document-level tax. M10/M11: `shipping_net` after shipping discount.
- M10b: rounding snapshotted. M13: `dispute_fee_currency`.

**2026-09-18 (section 2 review)**
- Section renamed "historical accuracy and change"; rules renumbered O1–O11
  (old O3 "no recomputation" is now O4; references updated).
- O1: copies SKU and option values, in the order language and, when the tax
  adapter requires it, the legal invoice language.
- O3: addresses copied onto the order. O5: guest orders attach only to a
  verified account. O6: readable random order numbers; internal ids never
  exposed. O7: `PROTECT` on every historical FK; deactivated variants block
  checkout. O8: order language copied.
- O9–O11: new — post-commit immutability, `OrderAdjustment`, address change
  with price difference (payment link for provider methods, admin for COD).
- S2 wording tightened; S2a: new — item and partial-quantity cancellation.
- L3: installed languages, customer choice, legal-language exception.

**2026-09-18 (section 3 review)**
- S1: payment status reads order-level aggregates across all successful
  payments; new terminal `uncollected`; COD cash must equal the effective
  total. Fulfilment is fully derived from quantities, with new
  `partially_returned`.
- S2: `CancellationRequest` lifecycle (one open at a time, sequential allowed,
  editable while open); pending adjustments cancelled first; `uncollected`
  not cancellable.
- S4: typed actors. S5: one global lock order (order → payment →
  reservation → variant, ascending id); C7 points to it.
- S6: recalculation on shipment, cancellation or return. S7:
  `cancelled_quantity`, `returned_quantity` and their checks.
- S8: new — shipment delivery status; refusal moves nothing, `received_back`
  triggers stock and money; `COD_PARTIAL_ACCEPTANCE` (off) and
  `COD_REFUSAL_SHIPPING_FEE` (on).
- S9: new — computed `display_status`.
- R7: new — return rules per market, legal-window warning (Shopify model).
- O10: adjustment type `refused_delivery`.

**2026-09-18 (section 4 review)**
- P1a: new — return-page status check through P1 path 2, shared apply
  function with the webhook, ownership and rate limits.
- P2a: two signing secrets during rotation. P2b: live/test separation.
- P5a: event row locked and re-checked. P5b: event outcomes. P5c: unknown
  payments stored and alerted.
- P8: contradicting a terminal state is recorded and alerts.
- P13: attempt status machine (`requires_action`, `expired`, `cancelled`).
  P13a: one active attempt — reuse, then cancel; late capture on a superseded
  attempt goes to review, never auto-refunded.
- P18: hosted page or provider fields only; client frontends never build card
  forms.
- S1: `pending → unpaid` on abandoned checkout; superseded-attempt capture
  enters review.

**2026-09-18 (section 5 review)**
- R1: refund lifecycle (`requested → sent → refunded | refund_failed`,
  reversal after success); COD refunds confirmed by permissioned admin action.
- R1a: refunds in progress count against the refundable balance.
- R1b: optional second approval above a threshold, off by default.
- R2a: refunds to the original instrument only. R2b: refunds allocated per
  line; return fees as visible deductions. R2c: no refunds during a dispute.
- R4: dispute lifecycle and evidence deadline alert. R5: `disputed_amount`
  follows provider fund movements; a won dispute reinstates.
- R6: accepted terms and refund-policy version, and communications log.
- R8: new — return request lifecycle and ship-back window.

**2026-09-18 (section 6 review)**
- C1: conditional `UPDATE` only where the ceiling is in one row; stock always
  locks variants. C1a: new — `CHECK (stock >= 0)`, no backorders in v1.
  C1b: new — untracked variants.
- C2: reservation created with the attempt, before the provider call; belongs
  to the order and carries across superseding attempts; adjustment payments
  take none. C2a: COD allocates through `allocate_order()`.
- C2b: new — reservation expiry = session expiry + `RESERVATION_GRACE`;
  `CHECKOUT_SESSION_TTL` 30 min set on the provider session; boot check
  against each provider's settable range. Replaces the 15-minute default.
- C3: availability excludes reservations past `expires_at`. C4: consumption
  re-checks expiry and stock under the lock.
- C4a: abandoned checkout releases. C4b: new — `allocate_order()`, all or
  nothing; definition of a verified stock allocation.
- C5, C6: resolution by allocate or cancel-and-refund, by staff or system;
  resolves the conflict with R1 and P13a ("configured refund action" removed).
  C6a: new — automatic resolution, allocate first, else refund; default on.
  C6b: new — aging alert.
- C8: mismatch alerts, never auto-corrects. C8a: new — typed movements.
  C9: admin read-only. C9a: new — manual decrease below reserved stock.
- C10: in-flight 409, key retention. C11: guest scope points to C12.
  C12: guest identity is the signed cart token.
- S1b: new — `ReviewCase`; S1 exits wait for every case; allocation failure
  replaces "expired reservation" as a review trigger. S2: cancellation from
  an `allocation_failed` review; only consumed stock returns. S5: lock order
  extended (event, cart, discount, invoice sequence). R1, R1b: system refunds
  under C6a. P13a, N4 and S1 fulfilment guard cross-references.
- Definition of done: tests for all of the above.

**2026-09-18 (section 7 review)**
- T2a: new — lost `on_commit` tasks re-driven by a monitored sweeper; idempotency
  from domain state under lock.
- T2b: new — guaranteed transactional notifications: row written with the
  change, sent by a job, at-least-once, body stored as dispute evidence (R6).
- T4: one shared HTTP client with connect and read timeouts. T4a: new —
  role-level database timeouts (lock 5 s; statement 30 s web, 10 min jobs;
  idle-in-transaction 60 s).
- T6: polls attempts in `created`, `requires_action`, `pending`, and refunds in
  `requested` or `sent`.
- T7: matching by provider id, `SETTLEMENT_MATCH_WINDOW` 7 days, no currency
  conversion, `MockProvider` settlement report; COD remittance out of v1.
- P13: `created → failed` on adapter-declared definitive rejection. P14: key
  covers session creation; key row committed before the call. P15: result
  semantics table for attempts and refunds.
- S1, C4a: definitive session rejection as a failure trigger. N4: sweeper and
  notification jobs. R6: communications log is the notification rows.
- Definition of done: tests for all of the above.

**2026-09-18 (section 8 review)**
- Q1: covers detail endpoints and admin change pages with inlines. Q1a: new —
  derived values (`display_status`, fulfilment, available stock, effective
  totals) from annotation or prefetch.
- Q2a: new — cursor pagination, default 20, max 100, no total count,
  deterministic order with `id` tiebreaker. Q2b: new — allowlisted, indexed
  filters and sorts; unknown parameters are 400. Q2c: new — exports and
  reports as jobs; admin full counts off on large tables.
- Q3: query-count tests extend to detail endpoints and admin pages.
- Q3a: new — explicit output schemas, public identifiers only. Q3b: new —
  money object with currency and exponent; M1a cross-reference. Q3c: new —
  1 MB body cap, 100 cart lines, `MAX_LINE_QUANTITY` 99. Q3d: new —
  PostgreSQL full-text catalog search.
- Definition of done: tests for all of the above.

**2026-09-18 (section 9 review)**
- A1a: new — normalized, case-insensitively unique emails, one comparison
  function. A1b: new — Argon2id and validators. A1c: new — single-use, expiring,
  hashed verification and reset tokens; reset kills all credentials.
- A3a: new — HS256 fixed. A4a: new — refresh reuse revokes the family. A4b:
  new — `token_version` checked per request. A4c: new — `kid` key rotation.
  A4d: new — browser refresh token in a path-scoped `HttpOnly` cookie; A5
  amended for that one CSRF-protected endpoint.
- A5a: new — CORS allowlist; boot fails unless `check --deploy` is clean.
- A6a: new — named permissions and default groups. A6b: new — mandatory staff
  TOTP; admin idle timeout.
- A8a: new — `guest_token_version`, 60-day lifetime, fresh link by email.
  A8b: new — token exchange on landing, `no-referrer`, tokens never logged.
- A9a: new — default rate-limit table. A9b: new — trusted-proxy client IP.
  A9c: new — no account enumeration.
- A12 and T2b: guest and cart tokens never logged; account and guest-link
  messages guaranteed.
- Definition of done: tests for all of the above.

**2026-09-18 (section 10 review)**
- G1: redemption taken at order commit, in the order-creating transaction,
  for every payment method; a failed redemption creates no order.
- G1a: new — percentage in basis points (1–10000), fixed value in minor units
  of `STORE_CURRENCY`, free shipping has no value; `amount_applied` carries a
  currency.
- G2: per-customer scope is the normalized email for accounts and guests;
  limit counted under the discount row lock; released redemptions excluded.
- G3a: new — discountable subtotal is the pre-discount line subtotal on the
  store's price basis; all lines discountable in v1; `min_order_total` measured
  against it, excluding shipping and tax.
- G3b: new — free shipping covers the full cost of any method, no cap.
- G4: validity is a `reprice_cart()` input; per-customer limit checked at
  checkout; failure at checkout or commit returns `price_changed` with the G6
  reason and creates no order.
- G4a: new — validity window stored in UTC, entered in the store timezone.
- G6: closed reason set, public API; an inactive code answers `not_found`.
- G7: new — whole-order cancellation returns the coupon use (row marked
  `released`, counter decremented); partial paths never do. Resolves parked
  item "cancellation gives back coupon use".
- S2b: new — abandoned unpaid provider-method orders cancelled by the system
  after `UNPAID_ORDER_TTL` (24 hours). S2 points to G7.
- O11: address-change repricing keeps the order's discount terms.
- N4: covers the S2b job.
- Definition of done: tests for all of the above.

**2026-09-18 (section 11 review)**
- F1: the inline list replaced by the core settings registry; the config
  reference is generated from it.
- F1a: new — one registry with type, default, range and change class
  (`deploy`, `runtime`, `locked`); invalid config fails boot.
- F1b: new — `PRICES_INCLUDE_TAX`, COD refusal settings and return rules
  copied onto the order at commit.
- F1c: new — runtime settings limited to the kill switch and provider
  toggles; `manage_settings` permission; audited changes.
- F1d: new — `STORE_CURRENCY` locked once any order or discount exists.
- F1e: new — new settings ship with behaviour-preserving defaults.
- F2: reworded for core-as-package; points to W2.
- F3: new — core default message templates; deployments override by code only.
- R7: one return policy per deployment in v1, snapshotted; "per market"
  removed. M3a, M11, S8: read snapshotted values. A6a: `manage_settings`.
  W2: theming defined as template overrides.
- Definition of done: tests for all of the above.

**2026-09-18 (section 12 review)**
- D1: review covers `sqlmigrate` output and any `RunPython` / `RunSQL`.
- D2: full expand/contract — `db_default` one-deploy add, drop via
  `SeparateDatabaseAndState` then drop next release, rename as add/backfill/switch/drop.
- D2a: new — migration `lock_timeout` 3 s with retry (`MIGRATION_LOCK_RETRIES`).
- D2b: new — concurrent indexes; `NOT VALID` then `VALIDATE` constraints;
  CI rejects blocking forms on existing tables.
- D2c: new — backfills are batched jobs; `RunPython` only on empty or bounded tables.
- D2d: new — historical models only; migrations and backfills never write
  stock, money, status or committed historical rows.
- D2e: new — snapshot columns never backfilled from current config; `NULL`
  means pre-snapshot.
- D2f: new — model definitions never read settings; `makemigrations --check`
  in core CI; deployments never hold core migrations.
- D2g: new — migrations run once, in a single release step.
- D2h: new — production rollback is code-only.
- D3: "destructive" and "verified backup" defined.
- D4: point-in-time recovery; restore test checks content and restore time.
  D4a: new — `BACKUP_RPO` 1 h, `BACKUP_RTO` 4 h. D4b: new — encrypted,
  access-controlled, residency-bound backups; `BACKUP_RETENTION`. D4c: new —
  erasure log outside the database, replayed after restore.
- D5: full list of required uniqueness constraints.
- D6: new — database roles: migration, web, job, retention.
- D7: new — append-only tables enforced by grants, with the column-level
  `UPDATE` exceptions.
- T4a, C9, F1a, F1b, I1, I9, I10, N4: cross-references to the above.
- Definition of done: upgrade-path migration test and tests for all of the above.

**2026-09-18 (sections 13–18 review)**
- X4, X11: X11a new — a named unique violation may be caught inside a
  savepoint, to retry (O6) or replay (C10, P5, T2b, G1); everything else
  re-raises.
- X5: codes bound to X5a, new — one error-code registry with status, class
  and `details` shape; the buyer error reference is generated from it.
- X7: `fields`, `details` and `request_id` added; `message` translated, `code`
  stable. X8: adding a code is not breaking.
- X9: 401, 403, 404, 413, 429 added; inaccessible objects answer 404; 409 vs
  422 fixed per code.
- X10a: new — server-generated `request_id` in header, error body and logs.
- X12: rows for oversized body, stale timestamp, mode mismatch, ignored and
  undeclared event types; "never retried" removed — the table states what we
  do, not what the provider does.
- X13a: new — no personal data in logs or error reports; log and tracker
  retention and region are settings. X14: Sentry protocol, DSN required in
  production.
- P5b, P7: adapters declare ignored event types (`no_op`); undeclared types
  are `unprocessable` and alert.
- Section 14 intro: dated network thresholds moved to the fraud ADR and
  runbook.
- V1: identities seen before an attempt; device fingerprint is a signal only.
  V1a: new — default failed-attempt limits. V1b: new — initiation limits
  regardless of outcome.
- V2: card-level blocking is a declared adapter capability (P18 means we
  never see the card); we block further attempts on order, email and device
  from event data.
- V3: detection escalates to 3-DS for `CARD_TESTING_ESCALATION_PERIOD`; never
  trips the kill switch. V4: boot fails when 3-DS is configured for a provider
  that cannot enforce it. V5: absent results are never mismatches.
- V7: `FraudAssessment` per payment attempt, append-only. V8: new — COD abuse
  controls: open-order cap, `COD_MAX_ORDER_TOTAL`, refusal-history block.
- N1: kill switch scope table. N2: disabling stops new attempts only; no
  reuse of a disabled provider's session (P13a).
- N3: split into public `/health` and authenticated `/health/detail`.
- N4: missing jobs added. N4a: new — job registry. N5: new — durable `Alert`
  rows; every "alert" in the file means this. N6: new — mandatory external
  uptime monitor.
- I1a: new — issuance trigger declared by the adapter, default on `paid`;
  adjustments before issuance issue no note (O10 amended). I1b: new — B2C
  documents only in v1.
- I3: numbers assigned at issue; rejected documents keep theirs. I5a: new —
  authority submission follows the outbound payment rules. I5b: new — "no
  authority" adapter. I7: notes follow the same states; `cancelled` only via
  the adapter.
- I8a: new — retention per data class. I10: user anonymised in place;
  contact fields and fraud signals on retained orders anonymised. I10a: new —
  deferred erasure for open matters. I11: `Consent` rows replace the boolean.
  I12: staff-started export job.
- L1a: new — jobs in UTC, business-day jobs keyed on store-local date. L3a:
  new — language resolution order; `STORE_DEFAULT_LANGUAGE`. L5: new —
  catalog translation tables, no per-language columns. L6: new — one
  formatter per language.
- W1a: new — private git repo by tag. W2a: new — which ports accept
  deployment adapters. W3: points to `/health/detail`. W4a: new — ports are
  public API. W5a: new — fixes on the latest minor only. W6: pointer to D2.
  W8: new — CI gates. W9: new — license for use, not modification.
- D5: open alerts, fraud assessments, translations. D7: `Consent` and
  `FraudAssessment` append-only; invoice number writable once, at issue.
- A4b, A6, A8, A9, A9a, A10, C2a, G6, O6, O7, P9, P13a, Q3d, T2b, T7: cross-
  references to the above.
- Definition of done: W8 gate and tests for all of the above.

**2026-09-18 (assumptions pass; Definition of done and Enforcement principle review)**
- Owner confirmed the 95 pending assumptions; the changes below come from
  that pass and the final review.
- O6: order numbers fixed at 8 characters, a code constant.
- M6: new `CONFIRMATION_TOKEN_TTL`, default 15 minutes. C10: boot fails if
  `IDEMPOTENCY_KEY_RETENTION` is shorter.
- X10a: a valid inbound `X-Request-ID` is logged as `upstream_request_id`;
  it never replaces the server's `request_id`.
- D4a: a verified point-in-time recovery window meeting `BACKUP_RPO` is
  required before a deployment takes paying customers.
- N3: monitoring token is a secret, scoped to `/health/detail`, and rotates.
- V3: does not ship without threshold defaults. I8a: retention values are
  confirmed per jurisdiction before paying customers.
- S1a: confirmation value `system`; `zero_total` method registered. S1c: new —
  a zero-total order is allocated and paid by the system at commit, with no
  `Payment` row, capped by `ZERO_TOTAL_ORDER_LIMIT` (3 per email, phone and
  IP in 24 hours). P1: fourth path. S1: `unpaid → paid` row for `zero_total`;
  a `zero_total` order exits review to `paid`, not `failed`. S2: the refund
  step does nothing without a successful payment. O11: `zero_total` follows
  the provider-confirmed column. G3, C4b, V7, N1, I1a, X5a: cross-references.
- A6a: new permission `approve_cancellation`; a refund computed by a
  cancellation or return is authorized by that action's permission,
  `request_refund` covers staff-chosen amounts; R1b applies to both. S2,
  R1, R1b: cross-references.
- D7: status transitions on `OrderAdjustment` and documents, and the set-once
  document number, enforced by trigger. O10: cross-reference. D7a: new —
  frozen columns on `Order`, `OrderItem`, `Payment` and `Refund` by grant;
  customer set once by trigger; temporary grant for D2e backfills. O9, P10,
  D2e, D6: cross-references. I7: closed transition table; `rejected` is
  terminal.
- D2b: the migration check also flags destructive operations. D3: the release
  step refuses a flagged migration without a restore-point identifier.
- T1: the shared HTTP client raises inside `atomic()`.
- W8: static checks and a clean-install test added to the CI gates. W8a:
  new — static checks for status and stock assignment, settings reads, import
  boundaries, money field types, bare `except`, and `CASCADE` / `SET_NULL` on
  historical FKs. S3, C9, F1a, T4, X1, X6: cross-references.
- Enforcement principle: applies to every invariant; recovery path and
  enforcement layer added (database, then CI, then code with a stated
  reason); every phase file carries the invariant table.
- Definition of done: split into "Every phase" and rule tests grouped by
  section, every item tagged with its rules; "no contract violated" replaced
  by a verifiable check; deploy verification defined; duplicates merged;
  tests for all of the above, and for T1, T2, P3, P4, P10, A1b, A11, C11, M7,
  S4, R3, G5, I4, I7, I8, S8 with the refusal fee off, and cursor tampering.

**2026-09-20 (pre-phase-plan review)**
- M6a: new — checkout's comparison and its commit are two transactions (T1);
  the commit re-asserts the database-backed inputs (line prices, discount
  validity and value, shipping cost) under the S5 locks, and the tax window is
  stated as accepted where the calculator is a network adapter. M5:
  `reprice_cart()` never runs inside `atomic()`. G4, R6, X5a: cross-references.
- S1: `charged_back → payment_review` on a reinstated chargeback (R5), and
  `charged_back` stated as non-terminal against `uncollected`; "first match
  wins" added to the `payment_review` exit table; the `unpaid → pending`
  trigger carved out for O11 adjustment payments; `uncollected` stated as an
  admin action, with S8 amended to match.
- S1b: `ReviewCase` gains `auto_resolution_attempted_at`, which T2a's sweeper
  reads and C6a writes.
- P10: the expected amount may also be copied from the applied-pending
  `OrderAdjustment` a difference payment pays for (O11).
- R1: `pending_approval` and `rejected` added to the lifecycle table, closing
  the gap between R1's table and R1b. R1a: refunds in `pending_approval` count
  against the refundable balance. R2b: `Refund.amount` is the net the customer
  receives; deductions are recorded alongside and M13's ceiling consumes the
  net.
- C10a: new — idempotency key lifecycle `in_progress → completed | failed`; a
  failed operation's key is retryable with the same key; new
  `IDEMPOTENCY_IN_PROGRESS_TTL` (default 5 minutes) and its sweeper (N4).
- T2a: the sweeper also re-drives orders that reached `paid` with no invoice.
  I1a: issuance happens in the transaction that reaches `paid`, with that
  sweeper as its recovery path.
- I8: retention deletes whole aggregates, children before parents, against
  O7's `PROTECT`; the deletion order is stated. C8a: a movement's cause
  reference is nullable so movements run on their own retention clock.
- A5a: boot warns when a configured CORS origin's registrable domain differs
  from the API's own, because A4d's `SameSite=Strict` cookie is not sent
  cross-site; the API on the client's registrable domain is a setup-guide
  requirement.
- Q3a: cart lines and order items carry a random public id, as C4b's
  `out_of_stock` and S2a, R8 and shipments all address lines from outside.
- W1b: new — the admin ships inside core. W8's clean-install gate checks the
  admin login page responds, and its upgrade-path test is marked not
  applicable to the first release.
- S1c: the zero-total placement cap is counted in the A9 rate-limit store and
  incremented atomically; A9 states that windowed placement caps belong there
  and gauges do not. V8: the refusal limit stated as a query, not a counter.
  **V8's open-COD cap is unchanged and its concurrency boundary is an open
  item in the handoff** — it is a gauge, so the A9 store cannot hold it.
- Definition of done: tests for all of the above; the previous-minor migration
  gate and W8's upgrade-path test marked not applicable to the first release.

**2026-09-20 (correctness pass)**

Sixteen defects found by re-reading the finished file: contradictions, rules
that could not be built as written, and values read by several rules but
declared by none. No scope changed.

- **P13b: new** — an admin-confirmed method (COD) creates its `Payment` row in
  the order-commit transaction, stays `created` while the order is `unpaid`,
  and moves `created → succeeded` with `paid_amount` from the recorded cash in
  the same transaction as `unpaid → paid`. Without a row, S1's aggregates read
  `paid_total == 0` for every COD order, M13's ceilings had no `paid_amount` to
  bound and R1's refunds had no payment to attach to. P13: the two new
  transitions. P10: reworded — no attempt is *committed* before its order,
  which an in-transaction row satisfies. S1, S1a, C2, T6, V7, D5: cross-
  references, and reconciliation never polls a row with no provider session.
- **M13**: `paid_amount` declared — it was read by M13's own ceilings, M14,
  M15, R1a and S1, and defined nowhere.
- **C4b**: a cancellation now reduces the line's consumed reservation, in the
  same transaction as its `cancellation_return` movement. Otherwise cancelling
  one unit of a three-unit line left a consumed reservation for three against a
  required two, and the line never passed the fulfilment guard again. S2:
  cross-reference.
- **M5**: the concurrency boundary was unbuildable — a row lock cannot be held
  outside a transaction, and the computation must be outside one (T1). The
  computation now hashes its inputs; the write locks the cart, recomputes the
  hash and discards a stale result.
- **N3**: `/health` no longer reports job staleness, which moves to a new
  public `/health/jobs`. A platform health check on the old endpoint restarted
  or de-pooled healthy web workers because a cron job ran long. N6: the monitor
  polls both, as separate checks that alert separately.
- **Q2a**: the keyset tiebreaker is the row's public identifier, not `id`. The
  cursor encodes the tiebreaker and is opaque but unsigned, so an `id`
  tiebreaker published internal primary keys on every list response (O6, Q3a).
- **G1a, F1d**: a fixed discount carries `value_currency`. M2 admits no stored
  amount without a currency, and F1d's boot check named a currency no row held.
- **G3a**: the discountable subtotal and `min_order_total` now share one basis.
  The rule said "on the store's price basis" and then "excluding shipping and
  tax", which are two different numbers under `PRICES_INCLUDE_TAX`.
- **V1a**: the per-order failed-attempt limit is a count of the order's
  `failed` payment attempts, not a row in the rate-limit store, whose rows are
  pruned per window. A9: states that a cap with no window does not belong
  there, as gauges do not.
- **A6a**: `create_shipment`, `record_delivery` and `record_receipt` added —
  fulfilment had no named permission at all, though S8 already split who
  records what. `collect_cash` also covers recording an offline refund payout
  (R1).
- **C10**: the `confirmation_token` is cart-scoped, not order-scoped — M6
  issues it precisely because no order exists — and it is a row of its own, as
  D5 already required. D5: scoped per cart.
- **O11**: applying an adjustment never writes payment status itself, but a
  negative delta's refund moves the order `paid → partially_refunded` through
  R1 and S1 like any other refund. The blanket claim was the wrong half.
- **S9**: `partially_refunded` added, placed last so a goodwill refund on a
  delivered order still reads `delivered`. Such an order previously read
  `processing`.
- **D4**: the restore check compares the newest restored order against
  production's newest at backup time, not against the clock, which failed the
  test every month on any store that took no order in the last hour.
- **S5**: "variants are locked last" corrected — `invoice_sequence` follows
  them.
- **X7**: `price_changed` may carry the G6 reason, which G4 already required it
  to carry and the declared `details` shape did not allow.
- **T2b**: recipient and language defined for the guaranteed account messages,
  which have no order (A1c).
- Definition of done: tests for all of the above; six existing tests updated to
  match.

**2026-09-20 (second correctness pass)**

Six defects found by re-reading the finished file for money paths that end
nowhere, rules that two other rules make impossible, and enforcement the ORM
cannot carry; two smaller inconsistencies fixed alongside. Re-reading the
*amended* file then found more, each a consequence of a fix rather than of the
original, and the readings continued until one found nothing. The count per
reading is the only evidence that amendments converge rather than breed:
**8, 4, 4, 3, 1, 1, 0**. Findings are listed under the reading that found them.
No scope changed.

- **S1**: a capture on an attempt that had already ended had nowhere to land.
  P13 sends it to `payment_review`, but the entry rows started only at
  `pending`, `paid`, `partially_refunded` and `refunded` — while S1's own
  `pending → unpaid` row means an expired attempt leaves the order `unpaid`,
  and a later failed attempt leaves it `failed`. `transition_to()` rejected the
  move and S3 logged a line: captured money, no review case, no alert, no
  aggregate. Rows added for `unpaid` and `failed`, with a note that a cancelled
  order enters review too and stays cancelled. S1b: `superseded_capture`
  broadened to any capture on an attempt that had ended.
- **S1**: the `payment_review` exit table tested
  `refunded_total + disputed_total == paid_total`, so the sequence M13's own
  rationale describes — a goodwill refund, then a full chargeback — matched no
  row and could never leave review. The last two rows are now `>=`.
- **C8a, O7, I8**: the stock ledger's cause reference was a nullable foreign
  key that nothing could ever null — O7 forces `PROTECT`, W8a forbids
  `SET_NULL`, and D7 grants no role `UPDATE` on `StockMovement` — so retention
  could never delete an order, on any deployment, years after launch. The cause
  is now a copied type and public identifier, the ledger is retained with its
  variant, and it sits outside the order aggregate. Replaces assumption 98.
- **R1c: new** — refunds are per payment (M13, M15, R1a) while every rule that
  causes one names an order-level amount, and an order may hold several
  successful payments (S1, O11). The split is now stated: most recent capture
  first, one `Refund` per contributing payment, one credit note per event,
  permission and second approval checked once. S2's "no successful payment"
  test no longer reads as "the method is `zero_total`", which kept an O11
  top-up on cancellation. C6a and D5: the system-refund constraint becomes
  (review case, payment).
- **I10b: new** — erasure's inventory covered the user row and the order only,
  leaving the subject's email in `Consent.subject`, `DiscountRedemption
  .scope_key` and `Notification` rows. For `Consent`, D7's append-only grant
  made erasure impossible rather than merely incomplete, and no retention class
  covered it. D7 now grants the retention role `UPDATE` on `Consent.subject`
  alone.
- **D7b: new** — column grants are checked against the `SET` list, and Django's
  `save()` writes every field, so D7 and D7a as written refuse every ordinary
  order save and every admin change form, in a product that ships the admin
  (W1b). Writes now name their columns, those models are admin-read-only, and
  W8a checks both.
- **C4b, X7**: `out_of_stock` named short lines by order-item public id, but at
  checkout the commit rolls back and those ids never existed for the client. It
  now names lines by the identifier the request used.
- **S8**: cash collected at the door on a refused shipment can only be recorded
  after `received_back` applies the adjustment, because S1 requires exact cash.
  The ordering and its delay to the invoice are stated rather than left to be
  discovered at the cash desk.
- **R1c, R2b, O10, T2b, D5** (second reading of the same pass): the split
  needed a home for "the event", or the permission check, the approval, the
  document and the message had no row to hang on. Rows created together now
  share a `refund_group`, and a refund against one payment is a group of one.
  Two duplications fell out of it and are closed: a negative adjustment issued a
  credit note (O10) *and* its refund issued one (R2b) — one document per event,
  issued by the adjustment where one exists — and a split would have sent one
  "refund completed" message per row. A disputed payment contributes nothing to
  a split and answers `dispute_open` rather than `RefundExceedsPaid`.
- **I8, N5, I8a** (third reading): the ledger was not the only row that would
  have blocked the retention delete. `Reservation` references the order and was
  missing from the aggregate altogether, and `Alert` references rows across
  every table — stated now as a typed pair rather than a foreign key, as the
  ledger is. Consent records and resolved alerts had no retention clock at all,
  so a guest's email sat in a consent row forever; both have one now. I8 states
  that every table referencing an order is in the aggregate or in one of the two
  named exceptions, so the next phase that adds one has somewhere to put it. The
same reading found the customer's saved `Address` rows missing from I10b's
erasure inventory — the most identifying table after the user itself; they are
deleted outright, since O3 already copied what the order needs.
- **I8** (fourth reading): the deletion order itself was wrong in three places
  — notes after the adjustments they reference, fraud assessments and
  adjustments after the payments that reference them — each a `PROTECT` failure
  years after launch. Corrected, with the point stated that the list is the
  expected result and the test on a fully exercised order is the proof.
- Definition of done: tests for all of the above; one existing test updated to
  match.

**2026-09-20 (fatal-defect review)**

A pass over the amended file looking only for defects that cost money or take
the service down. Three found and fixed; the readings and what each one found
are recorded in the handoff.

- **C12a: new** — nothing made a cart convert to at most one order. C10's key
  row is committed before the operation and marked `completed` after it, so a
  worker dying in between leaves a key the sweeper marks `failed`, and C10a
  exists to let a `failed` key be retried — placing a second order from the same
  cart, with a second coupon redemption and, for COD, a second allocation and a
  second shipment. Two concurrent checkouts with two different keys did the same
  without any crash. The converted-cart sentence existed only inside C12, which
  is scoped to guests, and D5 had no constraint for it. The order now stores its
  cart under a unique constraint, for every principal.
- **P13a, P10, P13b, O11, D5**: the one-active-attempt constraint was scoped to
  the order, while O11's difference payment is a second attempt on the same
  order. An address change on an order whose own attempt was still live either
  hit the constraint or, through P13a item 2, cancelled the customer's main
  payment page to open the delta page — and cancelled the delta page again on
  the next retry, so neither could be paid and the order died at
  `UNPAID_ORDER_TTL`. The constraint is now per *payable* — the order's own
  total, or one adjustment awaiting payment — as two partial unique indexes,
  with at most one adjustment in `awaiting_payment` per order.
- **P13c: new; S1, O10, S8** — S1 requires recorded COD cash to equal the
  effective total exactly, and nothing handled a courier collecting a different
  amount. Such an order could never reach `paid` (the cash does not match) and
  never reach `uncollected` (cash *was* collected), so it stayed `unpaid` for
  ever with real money off the books and no invoice for a delivered sale. The
  difference is now recorded as a `collection_adjustment` before the cash, which
  keeps the exact-cash invariant true and puts the shortfall where it can be
  counted.
- Definition of done: tests for all of the above.

**2026-09-20 (fatal-defect review, second reading)**

Four of these were created by the first reading's own fixes; the fifth closes
the open item the handoff had already raised.

- **S1, P13, P13a, C4a, S2b**: with the attempt constraint scoped per payable,
  "the order's only active attempt" became ambiguous. An order whose own session
  expired while a difference attempt was live would have stayed `pending` for
  ever — reservations never released (C4a), and outside S2b's reach, so the
  stock was held indefinitely. Every one of those rules now names the attempt
  *for the order's own total*.
- **M11, O10**: a `collection_adjustment` delta had nowhere to live. M11 on
  effective totals gains a `collection_difference` term, outside every line and
  every tax base, so a cash difference at the door does not move a tax base and
  M11 does not fail on the first collected COD order that has one.
- **O10, M1b**: O10 spoke of positive and negative deltas while M1b puts
  `CHECK (amount >= 0)` on every money column and carries direction by record
  type — and an adjustment's type does not fix its direction. The deltas are now
  stated as computed from the before and after snapshots, which are the stored
  values. Left as it was, the first negative-delta adjustment either fails on a
  constraint or the constraint is dropped from a money column, which is a
  migration on money later.
- **C12a**: the cart reference was going in as a foreign key, which would put
  `PROTECT` (O7) between a ten-year order (I8a) and a cart table that has to be
  prunable — the trap C8a and N5 were pulled out of. It is a copied public
  identifier under a unique constraint.
- **V8, S5, D5, I10b**: the open-COD cap had no concurrency boundary, which the
  handoff had raised as open item 9. It is a gauge, so A9's store cannot hold
  it and there was no row to lock — a scripted attacker parallelised past the
  cap and locked stock and courier fees for free. A `PlacementGuard` row per
  normalized identity is now locked before the order in the global lock order,
  and the gauge is counted under it.
- Definition of done: tests for all of the above.

**2026-09-20 (fatal-defect review, third reading)**

- **O11, P13, P13a, S1b**: an `OrderAdjustment` could expire or be cancelled
  while its payment attempt was still live, so the customer could pay a
  difference for a change that can never be applied — the adjustment is
  terminal, and the capture exceeds the order's payable total (P12) with no
  rule saying where it goes. The adjustment and its attempt now end in the same
  transaction, and a capture that still arrives is a `superseded_capture` into
  `payment_review`, the path the file already has for money that arrived late.
- **P13c, R2b, R1c**: the `collection_difference` added by the first reading had
  no place on a refund document. A full refund of a collection-adjusted order
  would have had the credit note's lines summing to one number and the refund to
  another, failing the M9/M11 assertion across the split on an otherwise correct
  refund. The difference now appears as its own line, as a return fee does.
- Definition of done: tests for both.

**2026-09-20 (phase-plan decisions)**

The owner confirmed assumptions 126–131 — the fatal-defect review's judgment
calls — with no change to any rule text, and closed the last open scoping item.
One new rule follows from that decision. No other scope changed.

- **C12b: new** — logging in claims the guest cart; carts are never merged. The
  handoff asserted a cart merge this file never had a rule for, and it touched
  M5 (repricing), C11 and C12 (whose principal the idempotency scope names) and
  C12a (the converted cart). Merge is out of v1: the guest cart is claimed under
  the cart lock, an earlier customer cart is left untouched, a converted cart is
  never claimed, and a claimed cart is repriced before it is next shown. The
  idempotency scope moves from the cart to the authenticated principal with the
  claim, which C12a makes safe. Closes the handoff's open item 10; no new
  uniqueness constraint, so D5 is unchanged.
- Definition of done: tests for C12b.
