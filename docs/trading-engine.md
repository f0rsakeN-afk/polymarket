# Trading Engine — Order Matching, AMM, Split/Merge … and Why It Isn't 1xBet

> Scope: `backend/app/services/{order_service,matching_engine,liquidity_service}.py`,
> `backend/app/amm/engine.py`, `backend/app/api/split_merge.py`,
> `backend/app/workers/tasks.py` (settlement), `docs/architecture.md`.

---

## 0. The one-sentence version

Every order is routed **through the limit-order book first and the AMM second**: whatever other
traders are willing to sell at or below your price fills immediately at *their* price, and the
unfilled remainder is taken from the liquidity pool at the pool's current price (with price
impact charged) — all inside one database transaction guarded by a fixed lock order.

---

## 1. Units — read this first, it trips everyone up

| Side | `amount` means | `Order.remaining_amount` means |
|---|---|---|
| **BUY** | USDC budget (dollars you want to spend) | USDC still unspent |
| **SELL** | share count (shares you want to sell) | shares still unsold |

A buy of `amount = 10` means "spend up to $10", not "buy 10 shares". A sell of `amount = 10`
means "sell 10 shares". Every comparison in the engine converts explicitly — for instance, when
a taker *sells* against a resting *buy* maker, the maker's `remaining_amount` is a dollar budget,
so the fillable share quantity is `maker.remaining_amount / maker.price`
(`matching_engine.py:325`). Mixing these two units is the classic bug here; the FOK check
(`order_service.py`) now compares dollars against dollars and shares against shares.

---

## 2. The routing algorithm (`OrderService.execute_order`)

```
 1. LOCK      market → pool → wallet          (fixed order, deadlock-free; see docker doc §B1)
 2. IDEMPOT   client_order_id already seen?  → return the original result, no second effect
 3. GUARD     buy: wallet.balance − locked ≥ amount
              sell: position.shares_held ≥ amount
 4. BOOK      MatchingEngine.match_order_against_book(...)
 5. REMAINDER whatever is left → BinaryAMM (price-impact-aware)
 6. CHECKS    post_only / max_slippage / fill-or-kill atomicity
 7. PERSIST   order + positions + trades (book legs AND the AMM leg) + wallets + market volume
 8. PUBLISH   trade + price_update over Redis pub/sub → every server instance
```

Steps 4 and 5 are the heart of it.

### 2.1 Step 4 — the book (`matching_engine.py`)

`find_matches()` selects resting orders on the **opposite** side with:

```sql
WHERE market_id = ? AND outcome_id = ? AND side = opposite
  AND status IN ('pending','partial') AND remaining_amount > 0
  AND price <= :limit          -- price filter for a buy; >= for a sell
ORDER BY price DESC/ASC, created_at ASC      -- price–time priority
FOR UPDATE SKIP LOCKED
```

* **Price–time priority**: best price first, ties broken by who got there first — the same rule
  a real exchange uses.
* **`SKIP LOCKED`**: if another request already holds a maker order's row, we silently take the
  *next* one instead of blocking — no deadlock, no wasted connection. The taker's own wallet is
  taken with plain `FOR UPDATE` (it must be held, not skipped).
* **Execution price = the maker's price.** The taker gets price improvement: if you market-buy
  at $0.60 and the resting order is $0.55, you pay $0.55. Makers never get a worse price than
  they posted.

Then, per maker, `execute_match()` does the money and share movement with **four guards**:

1. Wallets locked in `sorted(user_id)` order → two simultaneous matches can't deadlock.
2. **Buyer guard**: `balance − locked_balance ≥ usdc_value`, else `InsufficientBalanceError`.
3. **Seller guard**: re-read `Position.shares_held` under lock; if the seller no longer holds
   enough (a concurrent fill consumed them), the match is **skipped**, not silently allowed —
   otherwise shares would be "minted from thin air".
4. Maker's `remaining_amount` decremented by dollars (for a buy maker) or shares (sell maker);
   `filled` when it hits zero, `partial` otherwise, and `locked_balance` released pro-rata.

Two `Trade` rows are written per match — one for each side — so the trade feed and PnL history
agree for both users.

### 2.2 Step 5 — the AMM (`amm/engine.py`)

**Price:**

```
p(YES) = yes_shares / (yes_shares + no_shares)      p(NO) = 1 − p(YES)
```

**The fee** has two independent parts:

* **Pool fee (2%)** — `pool.fee_rate`, a per-pool column seeded with `settings.trading_fee_rate = 0.02`.
  It only exists on the **AMM leg**: a buy takes it out of the deposited collateral before shares are
  priced (`C_net = C − fee`), a sell takes it out of the proceeds. A pure **book** match (two users)
  charges no pool fee — the taker simply gets the maker's price.
* **Protocol fee (1%)** — `settings.protocol_fee_rate`, recorded into `pool.protocol_fees` and swept to
  the treasury at settlement. On the **AMM leg** it is added to the ledger on top of the trade value
  (nothing extra leaves a wallet — see §6.6). On the **book leg** it is *deducted from the seller's
  proceeds* (`seller += usdc_value − fee` while `buyer -= usdc_value`) and credited to the same ledger.
  Until recently that book fee was credited nowhere and simply left circulation; it is now recorded,
  with a regression test.

So the configured "effective take rate" is 3% (2% pool + 1% protocol) on AMM fills and 1% on
peer-to-peer book fills, and **nothing** is taken at settlement.

**Buying `C` USDC of an outcome** with reserve `R` and total `T`:

```
fee     = C * f                (f = 0.02)
C_net   = C − fee
shares  = ( C_net − R + sqrt( (R − C_net)² + 4 · C_net · T ) ) / 2
R      += shares
```

This is the positive root of `shares² + shares·(R − C_net) − C_net·T = 0`, i.e. the `shares`
that make

```
C_net = shares × price_after          where price_after = (R + shares)/(T + shares)
```

so **every share is paid for at the post-trade price** — the price your own order pushed the
pool to. That is what "price impact" means, and it is the difference between an AMM and a
counterfeiting machine.

**Selling `S` shares:**

```
collateral_out = S × (R / T) × (1 − f)      (pre-trade price)
R             -= S
```

**The invariant:** buy charged at the *post*-trade price, sell credited at the *pre*-trade
price — both are the side adverse to the trader — so a round trip returns exactly `(1 − f)²`:

| | fee | you put in | you get back |
|---|---|---|---|
| buy → sell | 2% | $10.00 | **$9.604** = 10 × 0.98² |
| buy → sell | 0% | $10.00 | **$10.00** (break-even to dust) |
| sell → buy | 2% | 100 shares | fewer shares than you started with |

Enforced by `tests/test_amm.py::test_round_trip_returns_only_fees` and
`..._large_size_never_profitable`. **The only thing trading can cost is the fee.**

### 2.3 Worked example (50/50 pool, `yes = no = 50`, fee 2%)

Buy $10:

```
C_net = 9.80
shares = (9.80 − 50 + sqrt((50 − 9.80)² + 4·9.80·100)) / 2
       = (−40.20 + 74.4046) / 2 = 17.1023
pool: yes = 67.10, no = 50, T = 117.10
p(YES): 0.5000 → 0.5730            (impact = +0.073)
```

Sell those 17.1023 shares: `17.1023 × 0.5730 × 0.98 = $9.604` — exactly `10 × 0.98²`.

### 2.4 The bug this replaced (great viva material)

The original formula charged the **pre-trade** spot price: `shares = C_net / price_before`.
Impact was zero, so the buy raised the price *after* the buyer had already paid the old price:

```
old: shares = 9.80 / 0.50 = 19.60
sell back: 19.60 × (69.6/119.6) × 0.98 = $11.18   →  +11.8% risk-free
```

A loop of buy→sell **made money and drained the pool**. It is now fixed, the ~31 AMM tests were
updated (the one test that hard-coded the impact-free `20.0 shares for $10` now asserts
`17.4166`), and the no-arbitrage property is a pinned regression test.

### 2.5 Why it is *not* an `x·y = k` constant-product pool

With `price = x/(x+y)`, a buy only grows `x`; for `x·y` to stay constant the pool would have to
shrink `y`, which the operation does not do. So `yes·no` **rises** on a buy and falls on a sell —
there is no such invariant here, and the old docstring claiming one was wrong. The invariant that
matters (round trips cost only fees) is stronger and is what the code actually defends.

---

## 3. Order types, and what happens to your money while you wait

| Type | Behaviour |
|---|---|
| `market` | Book → AMM remainder → `status = filled` |
| `limit` | Book (only if it already crosses) → AMM (only if AMM price ≤ limit) → otherwise **rests** at `pending` with the full budget as `remaining_amount` |
| `fill_or_kill` | All or nothing: if `total_usdc_spent < amount` (buy) or `total_shares < amount` (sell) after both legs → `ORDER_NOT_FILLABLE`, nothing created |
| `post_only` | If the AMM/book price already crosses your limit, reject rather than take liquidity |
| `max_slippage` | `effective_price = usdc_spent / shares` vs `price_before`; worse than the 0–10% tolerance → `SLIPPAGE_EXCEEDED` |

Resting orders are serviced by Celery beat:

* `check-limit-order-execution` (30 s) — re-tests resting orders against the current AMM price,
  scanning only the **dirty set** `SPOP dirty:markets 10000`, with `SKIP LOCKED`.
* `expire-stale-orders` (30 s) — frees `locked_balance` and cancels orders on closed markets.

The dirty set is written by `websocket.manager.publish_price_update` in the same Redis pipeline as
the WS broadcast, so a trade marks its market dirty for free. A fill additionally **enqueues the
sweeper directly** (`OrderService._enqueue_limit_sweep_now`), throttled to one enqueue per second
by a Redis `NX` key — an order whose price just got crossed waits milliseconds instead of the rest
of the 30 s beat cycle, and a burst of fills collapses into a single sweep rather than one message
per trade. If Redis or the broker is down, the beat run is the fallback and nothing is lost.
**Test:** `tests/test_safety_limits.py::test_a_fill_enqueues_the_limit_order_sweep_immediately`.

While an order rests, its budget sits in `wallet.locked_balance` — locked, not spent. It is
released on fill, cancel, or expiry.

---

## 4. Split and merge — the other way to get shares

The AMM is not the only way into a position. `POST /split-merge/split` and `/merge` implement the
**mint/burn primitives** every binary market needs.

### 4.1 Split: USDC → equal YES + NO pair

```
amount = 100 USDC,  fee = amount × split_merge_fee_rate (2%)  →  98 after fee
wallet.balance            -= 100
pool.protocol_fees        += 2
position[YES].shares_held += 98
position[NO].shares_held  += 98        (each at average_price = the pool's current price)
Transaction(type="split", amount=-100)
```

Why this is the natural primitive: `p(YES) + p(NO) = 1` always, so a YES+NO pair is worth
exactly $1 no matter where the price sits — one side loses, the other wins, and the pair is
always worth $1. Splitting is therefore **price-independent**: you are not making a bet, you are
creating a claim that pays $1 either way. (That is also exactly how the settlement pays out —
$1 per winning share.)

The `average_price` is set to the *current AMM price* purely so unrealized PnL displays sensibly;
it does not change what you hold.

### 4.2 Merge: equal pair → USDC

```
require position[YES] ≥ amount AND position[NO] ≥ amount   (else ValidationError)
fee = amount × fee_rate; amount_after_fee = amount − fee
pool.protocol_fees   += fee
shares              -= amount on BOTH sides
wallet.balance       += amount_after_fee
realized PnL updated per side, positions kept at 0 (history survives)
Transaction(type="merge", amount=+amount_after_fee)
```

### 4.3 Invariants to quote

* **Split → merge round trip costs exactly the fee**: `100 → 98 pairs → 96.04 USDC`, i.e. again
  `(1 − 0.02)²`. Same structure as the AMM round trip: no path through the system is
  money-generating.
* Split/merge **do not touch `pool.yes_shares`/`no_shares`** — they mint/burn *user* shares — so
  they cannot move the market price. Only AMM trades do that.
* Both endpoints run under the same market → pool → wallet → position lock order as trading, and
  update positions with an atomic `INSERT … ON CONFLICT DO UPDATE` (no read-then-insert race).
* Both publish `price_update` + a `split`/`merge` market event over the same pub/sub channel as
  trades, so charts and order books stay in sync without a second code path.

---

## 5. Resolution and who actually gets paid

1. An admin resolves the market (`winning_outcome_id`), a Redis `SET NX` lock plus the
   `resolving → resolved` status flip make double-settlement impossible, and the Celery task does
   the rest under `FOR UPDATE` on unsettled positions.
2. **Winners**: `wallet.balance += shares_held` ($1 per winning share) **paid out of
   `pool.collateral`**, `Transaction type="settlement_win"`, `position.settled_at` set — and
   `claim_winnings` re-checks `settled_at IS NULL` under the same row lock, so a claim racing the
   worker can't pay twice.

   Settlement is **all-or-nothing on the escrow**. Before it pays a single wallet it adds up the
   entire obligation — every winning share plus the recorded protocol fees — and compares it to
   `pool.collateral`. If the escrow cannot cover it, it raises `EscrowShortfallError` and the whole
   transaction rolls back: nobody is paid, no position is stamped settled, and the market stays
   `resolving` rather than `resolved`. `debit_collateral()` has no "pay what you can" mode at all,
   because a partial payment that then marks the obligation satisfied destroys the remainder —
   nothing records it as still owed and nothing retries it. A shortfall can only mean the ledger
   upstream is broken, so the honest response is to stop, alert (`settlement_escrow_shortfall`, one
   structured `logger.error`) and let Celery retry.

   A winner is never locked out by that: `claim_winnings` accepts a `resolving` market as well as a
   `resolved` one, because both callers that record a winning outcome commit it together with the
   move out of `active`. Claim stays all-or-nothing (`ESCROW_INSUFFICIENT`, 422, position left
   untouched), takes the same Pool → Position → Wallet locks, so it cannot double-pay a
   concurrent settle.
3. **Losers**: `settlement_loss` transaction for the history, payout 0.
4. **Protocol fees**: the treasury takes `pool.protocol_fees` — a sub-ledger *inside* the escrow —
   debited strictly, and only after the pre-flight has proved it is covered. Order is fixed and
   deliberate: **winners → fees → LPs**.
5. **LPs**: `lp_payout = lp_tokens / lp_token_supply × (escrow left after winners and fees)` — a
   pro-rata slice of *collateral*, so an LP carries the pool's trading P&L and the fees, not the
   outcome. The same formula governs an LP exit mid-market, and `remove_liquidity` refuses any
   withdrawal that would leave less than the open claims behind (§6.6). If the LP share rows ever
   total more than `lp_token_supply`, settlement refuses too rather than redeeming tokens against
   an inconsistent supply.
6. Positions are zeroed and the market becomes `resolved`; the frontend shows the claim button.

The creator's first LP position is a real `LPShare` row minted when the market is seeded (with
`total_liquidity` set at the same moment), so the pool starts with a holder rather than with
unowned supply.

---

## 6. Known limitations to admit before you're asked

These are real, and naming them unprompted scores more marks than hoping they don't come up.
The first group was real six weeks ago and has been closed since — know the story, because
"how did you fix it" is a better question to be asked than "what's broken".

### Fixed — know what was wrong and how it was closed

1. **The ledger used to be single-entry: nothing was ever debited.** A $100 pool seeded 70/30 and
   then a $100 YES buy (2% fee) yielded 113.98 shares against 183.98 YES of claims — if YES won,
   $297.96 was owed out of the $200 that ever existed. **Now:** every pool flow goes through one
   choke point, `LiquidityPool.credit_collateral()` / `debit_collateral()` in
   `app/models/liquidity.py`. Buys, splits and deposits credit; sells, merges, LP exits, fee
   sweeps, claims and settlement debit. `debit_collateral` refuses to drive the escrow negative —
   `debit_collateral()` raises `EscrowShortfallError` rather than let a balance go below zero, and
   settlement pre-flights the whole obligation before touching a wallet, so an underfunded escrow
   aborts the run instead of quietly underpaying anyone). **Tests:**
   `tests/test_ledger.py` (15 cases: split/merge symmetry, wallet-delta == collateral-delta, the
   full settlement payout table, underfunded escrow paying capped/zero, claim-time refusal).
2. **LPs used to be exposed to the outcome** — redeemed from the winning side's reserve, so an LP
   on the losing side got nothing even though the pool held dollars. **Now** an LP exit pays a
   pro-rata slice of *collateral*, and settlement pays winners → protocol fees → LPs (residual).
   LPs still carry the pool's trading P&L, which is what an LP signs up for; what changed is they
   are no longer short the outcome as well.
3. **`pool.collateral` used to be decorative** — analytics read a number that meant nothing.
   **Now** it *is* the escrow: settlement, LP payouts, the claim endpoint and the floor below all
   treat it as the single source of truth.
4. **The 1% protocol fee used to be bookkeeping without escrow** — recorded against money no ledger
   row was ever taken from, so the treasury sweep claimed funds that were never debited. **Now**
   `pool.protocol_fees` is a sub-ledger *inside* `pool.collateral`: every leg that owes a fee
   credits it (book fee in `MatchingEngine.execute_match`, AMM legs in `order_service` and the
   beat task, both split and merge), the sweep in `LiquidityService.distribute_protocol_fees`
   debits it, and settlement pays it after winners and before LPs. **Test:**
   `tests/test_orders.py::test_book_match_protocol_fee_is_credited`.
5. **`initial_probability` was inverted** when seeding a pool (a market created at 0.70 opened at
   0.30). Fixed, with a regression test.

### The guards that keep it honest

6. **LP-exit escrow floor.** `LiquidityService.remove_liquidity` refuses any withdrawal that would
   leave less than *worst-case open claims + protocol fees owed* behind. Only one side is ever
   paid at resolution, so the worst case is the **larger** side's unsettled shares — read from
   `position` rows (authoritative), not from AMM reserves (pricing state). Without it an LP could
   empty the pool while traders still hold shares, and settlement would have to short-change them.
   The refusal names the withdrawable amount. **Test:**
   `tests/test_safety_limits.py::test_lp_exit_cannot_take_escrow_away_from_open_positions`.
7. **Split and merge move the AMM reserves with the shares they mint and burn.** A split used to
   hand out real shares without touching `pool.yes_shares`/`pool.no_shares`, so those shares could
   not be sold back into the AMM (`amm.sell` refuses to pay out more than the reserve holds) even
   though the owner legitimately held them. Both sides now move by the same amount, so the quoted
   price is unchanged. **Test:**
   `tests/test_safety_limits.py::test_split_and_merge_move_amm_reserves_with_the_shares`.

### Still true — admit these unprompted

8. **The AMM is thin and linear-impact.** One $10 order in a $100 pool moves the price 7 points.
   Real venues have deeper liquidity, partial fills and a mid-price from the book.
9. **The invariant audit is nightly, not continuous.** `app/services/escrow_audit.py` re-checks
   every pool at 4am (Celery beat, after the fee sweep) and
   `./scripts/audit_escrow.py --market <uuid>` runs the same check on demand, exiting non-zero
   when it finds something. It checks `collateral >= max(open YES shares, open NO shares) +
   protocol_fees` — the exact pre-flight from §5 — plus fees-backing, LP supply drift, negative
   collateral, and positions owed with no pool at all. So an imbalance surfaces overnight instead
   of at resolution. **What it doesn't do:** repair anything (a repair written by something that
   doesn't understand the drift is how a rounding bug becomes a loss), alert anyone — it logs
   structured `ERROR`s that nothing watches yet — or run more than once a day, so drift that
   develops and resolves inside a day is still only caught if it persists.
10. **`pool.yes_shares`/`no_shares` are AMM pricing state, not the claim ledger.** Settlement reads
    position rows. They agree by construction now (7 closed the known divergence), but they are
    still two representations of the same fact.

---

## 7. "How is this not gambling like 1xBet?"

This is the question most likely to be asked by someone who doesn't care about locks. Answer it
in layers.

### 7.1 The mechanical differences

| Axis | 1xBet-style bookmaker | This system (prediction market) |
|---|---|---|
| **Your counterparty** | The bookmaker. You bet *against the house*, which sets odds to guarantee its own margin. | The other side: other traders and the AMM pool. You buy a share, not a wager. |
| **What a win pays** | Fixed odds set at bet time (`$2.37 × stake`), capped by the bookmaker's pricing. | **$1 per share**, always — the share *is* a claim. |
| **Where the price comes from** | Bookmaker's model + balancing to equalise liability. Opaque, adjusted to steer your bet. | Supply and demand on an open book + pool reserves. Public, observable, auditable. |
| **Meaning of the number** | Implied probability *after* margin (overround typically 5–15%). | `0.65` means the market says 65%. It sums to 1 with the other side. |
| **Can you exit?** | No — your stake is locked until settlement; "cash out" is a fresh, worse offer from the house. | Any time: sell at the current market price into the book or pool. |
| **The house's edge** | Built into the odds *and* it wins in aggregate by construction. | An explicit, disclosed **2% trading fee**. Nothing is taken at settlement: a winning share pays $1 flat. |
| **Who profits when you win** | The bookmaker pays you, and its pricing ensured it still profits overall. | The losing side/pool pays you. Zero-sum between participants, minus fees. |
| **Repetition mechanics** | Accumulators/parlays, odds boosts, VIP loss-back — engineered churn. | No parlays, no bonuses, no loss-rebates. Round-tripping is *always* −4% (see §2.2), so churning is punished, not rewarded. |
| **Risk disclosure** | Odds presented as a price of a bet. | Price presented as a probability, plus order book depth, so you can see what you'd get out at. |

### 7.2 The argument in one paragraph (say it out loud)

> A bookmaker sells you a *bet*: the house decides the odds, keeps a margin inside them, takes
> your stake when you're wrong, and won't let you leave early. Here you buy a *share* that pays
> exactly $1 if the event happens and nothing if it doesn't — you can hold it or sell it at any
> moment at a price the market sets, the platform's take is a disclosed fee on trading (2% pool
> fee, plus a 1% protocol fee routed to the treasury) and **nothing at settlement**, and the money a winner receives comes from the losing side rather
> than from a house that was guaranteed to win anyway. The price is also information: 0.62 is the
> crowd's probability, not a marketing number.

### 7.3 The honest caveats (they will respect you for these)

* **Frequent trading here is negative-EV, deliberately.** Every round trip loses `(1−f)²`, i.e.
  ~4% at a 2% fee. That is exchange-commission behaviour, not a casino's — but it means the
  product is only sensible if you hold a view or provide liquidity, not if you churn.
* **The line between "prediction market" and "betting" is a legal question, not a technical
  one.** Depending on jurisdiction, event contracts have been treated as derivatives, as gaming,
  or as somewhere in between — and sports-event contracts specifically are contested. The honest
  answer: *this codebase implements an exchange with transparent pricing and no house edge at
  settlement; whether it may be offered somewhere is a regulatory determination.*
* **Behavioural risk is real either way.** The mitigations present here are structural rather
  than paternal: no leverage (you can't lose more than you put in), no liquidation engine, no
  deposit bonuses or "VIP" loss mechanics, rate limits and friction on money movement, and
  single-use idempotency keys so a double-click can't double-spend.
* **And one you fixed:** before the price-impact fix, *our* AMM was worse than a casino —
  a buy/sell loop extracted money from the pool risk-free. That's the kind of defect that
  separates "a platform with a house edge" from "a platform with a bug".

### 7.4 Three questions to answer *before* they're asked

1. **"So the platform always wins?"** — No. It earns a flat 2% fee on volume and a protocol fee
   routed to the treasury; it takes no position in any market and is indifferent to who wins.
   (The treasury/system wallet exists only for fees and LP settlement.)
2. **"Where does a winner's money come from?"** — The losing side: whoever sold you the share,
   and the pool's collateral. Honest follow-up: in this codebase that flow is not yet enforced by
   a double-entry ledger (§6.1), which is the top item on the to-do list.
3. **"Isn't 0.62 just odds?"** — It's a price on a $1 claim, so it *is* the probability, and the
   two sides sum to exactly 1 because the same collateral mints both — the odds are never
   inflated to hide a margin.

---

## 8. 60-second recap, for reading aloud

> Orders are routed book-first, pool-second, under a fixed lock order in a single transaction.
> The book fills by price–time priority at the *maker's* price with `SKIP LOCKED`, so two users
> buying at the same instant serialize on the market/pool/wallet rows instead of racing. The
> remainder goes to the AMM, whose price is the share ratio of its two reserves and whose buy
> formula charges the post-trade price on every share — which is why a round trip can only ever
> cost the fee and can never extract value. Split and merge are the mint/burn primitives
> (1 USDC ↔ one YES+NO pair, priced at $1 by construction, again fee-only to reverse), and
> settlement pays winners $1 per share from the losing side while sweeping fees to the treasury.
> Compared with a bookmaker, you own a tradeable claim instead of betting against a house that
> has already priced its margin into your odds.

---

## 9. Where to look in the code

| Question | File |
|---|---|
| How is one order executed? | `app/services/order_service.py` |
| How are two orders matched, and what stops overselling? | `app/services/matching_engine.py` |
| What is the AMM formula and the no-arbitrage proof? | `app/amm/engine.py` + `tests/test_amm.py` |
| What does split/merge do to wallets/positions/pool? | `app/api/split_merge.py` |
| Who gets paid at resolution? | `app/workers/tasks.py` (`settle_market`), `app/api/markets.py` (`claim_winnings`) |
| Lock order and race handling | `docs/docker-concurrency-realtime.md` §B |
| Regression tests for all of the above | `tests/test_security_fixes.py`, `tests/test_orders.py`, `tests/test_concurrency.py` |
