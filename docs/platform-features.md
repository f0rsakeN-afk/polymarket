# Platform Features • Everything That Isn't Trading

The subsystems that make this a *product* rather than just an exchange: threaded comments, price
alerts, notifications, referrals, market flagging, the dispute process, moderation, the treasury,
the activity feed, the trade tape, positions, the audit trail, and the shared error contract.

> Written from `backend/app/api/{comments,alerts,notifications,referrals,flags,disputes,admin,treasury,market_activity,trades,positions,handlers,exceptions,responses}.py`
> and `backend/app/services/{alert_engine,notification_service,audit_service}.py`.
>
> **The pattern to notice throughout: almost nothing here moves money, so almost nothing here locks
> rows.** Where a lock *is* taken, it is because two writers could otherwise disagree about state.

---

## 0. Map of the surface

| Subsystem | Router / prefix | Tables | Auth |
|---|---|---|---|
| Comments | `comments` → `/markets` | `comments` | write: user · read: public |
| Alerts | `alerts` → `/alerts` | `alerts` | user |
| Notifications | `notifications` → `/notifications` | `notifications`, `notification_preferences` | user |
| Referrals | `referrals` → `/referrals` | `referrals` | user |
| Flags | `flags` → `/flags` | `market_flags` | create: user · review: admin |
| Disputes | `disputes` → `/disputes` | `disputes` | file: user · propose/adjudicate: admin |
| Moderation | `admin` → `/admin` | `markets`, `users` | admin |
| Treasury | `treasury` → `/treasury` | `treasury`, `treasury_logs` | admin |
| Activity feed | `market_activity` → `/markets` | many | public |
| Trade tape | `trades` → (none) | `trades` | public |
| Positions | `positions` → `/positions` | `positions` | user |
| Audit trail | via `admin` | `auth_audit_events` | admin |

---

## 1. Comments • threaded discussion (`api/comments.py`)

### 1.1 The model is a self-referencing tree

`comments` has `parent_id` → `comments.id` (CASCADE) and a `depth` integer, plus `is_deleted` for
soft deletion. The ORM pair is assigned after the class body (`models/comment.py:27-38`) with
`remote_side=Comment.__table__.c.id` • the standard disambiguation for a one-to-many self-reference.

**Soft delete, not hard delete** is the important design choice: deleting a comment keeps the row so
its replies keep a valid parent and the thread doesn't collapse into orphans.

### 1.2 Depth is capped at 3

```python
MAX_DEPTH = 3                                    # comments.py:20
...
depth = parent.depth + 1
if depth > MAX_DEPTH:
    raise ValidationError(f"Max reply depth is {MAX_DEPTH}")   # :47-48
```

Depths 0–3: a top-level comment, then three levels of reply. **`depth` has no CHECK constraint** •
it's application-enforced only, so a raw insert can nest arbitrarily.

### 1.3 The anti-N+1 pattern • this is the bit to quote

Listing comments would naively be: fetch 50 top-level comments, then one reply-count query per
comment. Instead, reply counts come from **one batched aggregate**:

```python
# Fetch all reply counts in a single batch query • avoids N queries
comment_ids = [c.id for c, _ in rows]
if comment_ids:
    reply_result = await db.execute(
        select(Comment.parent_id, func.count(Comment.id))
        .where(Comment.parent_id.in_(comment_ids))
        .group_by(Comment.parent_id)
    )
    reply_counts = {str(parent_id): count for parent_id, count in reply_result.all()}
```

50 comments → **2 queries**, not 51. The index that makes it cheap is
`ix_comments_parent_id (parent_id)`. The same batching idea appears in `positions.py:46-57` (3
queries instead of 3×N) and `market_activity.py` (§8.3).

### 1.4 Endpoints and guards

| Endpoint | Auth | Notes |
|---|---|---|
| `POST /markets/{slug}/comments` | user | body 1–2000 chars (`schemas/comment.py:7`) |
| `GET /markets/{slug}/comments` | public | `page` ≥1, `page_size` 1–**200** default 50; **top-level only** (`parent_id.is_(None)`) |
| `GET /markets/{slug}/comments/{id}/replies` | public | `page_size` 1–100; filters `depth <= MAX_DEPTH` **and** `is_deleted IS FALSE` |
| `PATCH /markets/{slug}/comments/{id}` | owner | |
| `DELETE /markets/{slug}/comments/{id}` | owner or admin | soft delete |

Two inconsistencies worth naming:
- The **top-level list omits `is_deleted` filtering**; the replies query filters it. So a deleted
  top-level comment still appears in the list.
- The list response nests `reply_count` but **not** the replies themselves • the client makes a
  second call per comment with replies. A reasonable trade (bounded page size), but it's two round
  trips per expanded thread.

### 1.5 A nice validation detail

The parent lookup is scoped to the market: `select(Comment).where(Comment.id == data.parent_id,
Comment.market_id == market.id)` (`:42-43`). Without that scope, you could reply to a comment on
market A while posting "on" market B • a genuine cross-market injection. There's a test
(`test_trades_comments_alerts.py`) covering "cross-market parent".

---

## 2. Price alerts (`api/alerts.py` + `services/alert_engine.py`)

### 2.1 What an alert is

`alerts` rows: `(user, market, outcome, condition ∈ {above, below}, trigger_price, triggered)`.
`outcome` is nullable • `NULL` means **either side**, so a legacy alert tracks YES
(`alert_engine.py:42-44`):

```python
def _tracked_side(outcome: str | None) -> str:
    """Which price series this alert follows. None tracks YES (legacy behavior)."""
    return "no" if outcome == "no" else "yes"
```

### 2.2 The trigger index • Redis sorted sets

Key shape: `alerts:{market_id}:{yes|no}:{above|below}` → a ZSET of `{alert_id: trigger_price}`.

Because the condition is baked into the key, "alerts due at price P" is a single range scan with
no filtering. And the claim is **atomic** • a Lua script does fetch-and-remove together:

```lua
if ARGV[2] == 'above' then
    members = redis.call('ZRANGEBYSCORE', KEYS[1], '-inf', ARGV[1])
else
    members = redis.call('ZRANGEBYSCORE', KEYS[1], ARGV[1], '+inf')
end
if #members > 0 then
    redis.call('ZREM', KEYS[1], unpack(members))     -- claim by removing
end
return members
```

**Because the removal happens inside the script, exactly one worker can win a given alert** even
with N workers running. The file's docstring states the two-layer design precisely: *"...concurrent
workers can't double-claim"*, plus *"a guarded UPDATE … WHERE triggered=false, and only flipped rows
notify."*

So there are **two** independent guards:
1. The Lua claim (fast, at scale, in Redis).
2. `UPDATE Alert SET triggered = true WHERE id IN (...) AND triggered = false RETURNING Alert`
   (`alert_engine.py:147-161`) • the rows that actually flipped are the only ones that notify.

Even if Redis lost the claim, the DB still can't notify twice.

### 2.3 The ZSET is a pure *index*, not the source of truth

Every Redis interaction is wrapped so failures can't break price evaluation, and there's explicit
self-repair:

- `index_alert` is **write-through on create** (best-effort), with a **7-day TTL** (`EXPIRE
  86400*7`) so abandoned alerts clean themselves up.
- `reindex_market_alerts` rebuilds a market's index from Postgres.
- `check_price_alerts` (`tasks.py:1094-1194`) does: claim → if empty, **reindex and retry once** →
  mark triggered. A cold index repairs itself on the first miss.
- Crash recovery: on exception it `rollback()`s, **reindexes, commits, then re-raises**
  (`tasks.py:1172-1182`) • because a crash between the Lua `ZREM` and the DB commit would
  otherwise orphan alerts out of the index while still un-triggered in Postgres.

The docstring says it best: *"the ZSET is a pure index: Postgres remains the source of truth."*

### 2.4 `pop_dirty_markets` • and the important detail about its error path

The 30-second limit-order sweeper avoids scanning every market by consulting a Redis set. Popping
returns `None` **on error**, distinct from an empty list (`alert_engine.py:164-177`) • and the caller
treats `None` as *"Redis is gone, do a full scan"* while `[]` means *"no market moved, skip
everything"*.

That distinction is the difference between a degraded run and a silently skipped one, and
`test_task_integration.py` covers the "falls back to a full scan when Redis is gone" case.

---

## 3. Notifications (`api/notifications.py` + `services/notification_service.py`)

### 3.1 Two tables, one flow

- `notifications` • the in-app feed. `read_at IS NULL` means unread; `channel` is
  `in_app | email | push`.
- `notification_preferences` • **one row per user** (`user_id` `unique=True`) with eight nullable
  booleans gating each channel.

Six notification types (`notification_service.py:15-22`): `alert_triggered`, `order_filled`,
`order_cancelled`, `market_resolved`, `market_closing_soon`, `weekly_digest`.

### 3.2 `dispatch()` • order of operations

1. Persist `Notification(channel="in_app")` and **commit**.
2. Publish to the user's WebSocket channel via Redis pub/sub • **non-fatal** on failure.
3. Load-or-create the user's preferences.
4. Map the type to an email flag: `alert_triggered → email_alerts`, `order_filled →
   email_order_fills`, `market_resolved → email_market_resolution`.
5. If enabled **and** `settings.resend_api_key` is set, enqueue `send_email.delay(...)`.

Two deliberate choices: **the in-app row is committed before the WS push**, so a dead socket can
never lose a notification (the bell picks it up on next fetch); and **email is conditional on the API
key**, so a dev environment with no key logs instead of erroring.

### 3.3 Authorisation is scoped, not global

`mark_read` / `mark_all_read` filter by `user_id` in the `WHERE` clause
(`notification_service.py:109-131`), not by checking afterwards. Scoping in the query means one user
structurally cannot touch another's notification.

---

## 4. Referrals (`api/referrals.py`)

### 4.1 Code generation and the race

```python
def _generate_code() -> str:
    return str(uuid.uuid4())[:12].upper()
```

12 characters from a UUID4 • ~60 bits of entropy, so collisions are theoretical. But "theoretical"
isn't "impossible", and the column is `unique=True`. So generation retries:

```python
for _ in range(5):
    code = _generate_code()
    user.referral_code = code
    try:
        await db.commit(); await db.refresh(user); break
    except IntegrityError:
        await db.rollback(); user.referral_code = None; continue
else:
    raise Exception("Unable to generate unique referral code after retries")
```

**This is optimistic concurrency against a unique constraint** • it relies on the database to
arbitrate, and handles the collision rather than pre-checking (which would itself race). Two gaps
to name: five retries then a bare `Exception` → **500** (it should be a typed error), and a
`SELECT`-then-`UPDATE` gap remains • but the unique index is what actually guarantees correctness.

### 4.2 The reward

A flat `referral_reward_amount` (default `Decimal("1.0")` USDC, `config.py:96`), credited in the
order path (`order_service.py:671`) • i.e. **on the referred user's first real activity, not at
signup**. That's the right trigger: signup-only rewards attract fraud, and a reward paid from
trading activity means the reward only happens when the platform is actually being used.

`referrals.status` is nullable with default `"pending"`, and `reward_amount` is `Decimal` (the only
model default that constructs one explicitly) • both nullable, so the "pending → completed"
transition is app-driven.

---

## 5. Market flags (`api/flags.py`)

The lightweight moderation signal: a user reports a market as problematic.

- `POST /flags` • creates `MarketFlag(market_id, user_id, reason)`. `reason` must be 5–1000 chars.
- **Dedup is app-level**: `if existing: raise ValidationError("You have already flagged this
  market")` (`:36`). There is **no unique constraint** on `(market_id, user_id)`, so a
  concurrent double-submit can create two flags. Say this yourself.
- `GET /flags/market/{market_id}` • **admin only**, and **completely unpaginated**: it loads every
  flag for a market (`:74-79`). Fine at a few flags; not fine at scale.
- `PATCH /flags/{id}/resolve` • admin only; `status` must be `open` (`:109`), then set to
  `resolved` or `escalated`.

**Flags do not hide or take down a market.** They are a queue for a human. And nothing notifies an
admin that a flag exists • the reviewer has to go looking.

---

## 6. Disputes (`api/disputes.py`) • the integrity mechanism

This is the most important non-trading subsystem, because it's the answer to *"what stops an admin
from rigging a resolution?"*

### 6.1 The lifecycle

```
active ──(admin proposes resolution)──► dispute_window  [48h timer running]
   │                                            │
   │                                            ├──(window closes, no dispute)──► resolved
   │                                            │
   │                                            └──(user disputes)──► Dispute(status=open)
   │                                                              │
   │                            admin adjudicates: upheld ────────┤──► market resolved + settlement
   │                                              dismissed ─────┘──► dispute closed, market untouched
   │
   └──(closes_at passes, no outcome)──► closed ──(resolve endpoint)──► resolved + settlement
```

### 6.2 The 48-hour window

```python
DISPUTE_WINDOW_HOURS = 48                                        # disputes.py:31
market.dispute_deadline = datetime.now(UTC) + timedelta(hours=DISPUTE_WINDOW_HOURS)
market.status = "dispute_window"                                  # :116-117
```

### 6.3 Who may dispute, and when

```python
# `resolving` counts: the outcome is proposed and settlement is pending •
# that is exactly the window users must be able to dispute in.
if market.status not in ("resolving", "resolved", "dispute_window"):
    raise ValidationError("Market is not in a resolvable state")
if market.dispute_deadline and datetime.now(UTC) > market.dispute_deadline:
    raise ValidationError("Dispute window has closed")
```

Two details worth the airtime:
- **`resolving` and `resolved` both count.** Otherwise there'd be a gap: an admin could resolve and
  settle so fast that nobody could ever dispute. The comment says exactly this.
- **`dispute_deadline IS NULL` means unbounded**, not "expired". The `and` guard is load-bearing.

The market row is read `with_for_update()` • so two simultaneous dispute filings serialise.

### 6.4 Adjudication and the settlement hand-off

`POST /disputes/{id}/adjudicate` • admin only, `ruling ∈ {upheld, dismissed}`, and the dispute is
locked `FOR UPDATE` plus guarded `status != "open"` (`:181-182`), so a dispute can be ruled on
**exactly once**.

On `upheld`, and only then, it sets `winning_outcome_id = proposed_outcome_id`, marks the market
resolved, and enqueues settlement. The ordering is the interesting part:

```python
# Queue settlement BEFORE commit • if broker is down we fail before
# the market is marked resolved in the DB, preventing orphaned resolution
try:
    resolve_market.apply_async(args=(...), task_id=request_id, priority=5)
except Exception as e:
    raise HTTPException(status_code=503, detail="Settlement service unavailable, please retry")
await db.commit()
```

**Enqueue before commit, deliberately inverted from the usual order.** The usual advice is "commit,
then dispatch the side effect". Here the reasoning is the opposite: if the broker is down, we must
fail *before* the DB records the market as resolved • otherwise we'd have a resolved market with no
settlement ever queued, and nobody would ever retry. A 503 is recoverable by the client; an orphaned
resolution is not.

### 6.5 Gaps

- **No uniqueness on `(market_id, user_id)`** • one user may file many disputes on one market.
- **`GET /disputes/market/{id}` accepts `page` without validation** and **returns a bare list with no
  pagination metadata** (`:129-130, 145`).
- **`admin_note` is accepted on adjudication and discarded.** A ruling with no recorded reasoning is
  a weak governance story • and it's the field where the reasoning would have gone.

---

## 7. Moderation (`api/admin.py`)

### 7.1 The market-submission pipeline

New markets arrive as `status = "pending_review"` • **invisible publicly**, but readable by the
author (`UNPUBLISHED_STATUSES = (pending_review, rejected)`).

- `POST /admin/markets/{id}/approve` • refuses if `closes_at` has already passed:
  *"reject it so the author can resubmit"*. Note this is a **soft block** with no edit path, so the
  submission is effectively dead-ended unless rejected and resubmitted.
- `POST /admin/markets/{id}/reject` • the author keeps read access to their own submission.

Both use a **compare-and-set** status change (`_set_market_status`), which returns **409** if another
admin got there first. That's optimistic concurrency on a moderation queue.

### 7.2 The capabilities that are *not* in `admin.py`

Knowing this table is worth a lot of marks, because several of these are assumed to be admin
features and actually live elsewhere • or don't exist.

| Capability | Where it actually is |
|---|---|
| Resolve a market / trigger settlement | `POST /markets/{slug}/resolve` (`markets.py:569-659`), admin-gated at `:577-578` |
| Claim winnings | `POST /markets/{slug}/claim` • **any user**, own winnings |
| Propose a resolution | `POST /disputes/propose-resolution` (`disputes.py:89`) |
| Adjudicate a dispute | `POST /disputes/{id}/adjudicate` (`disputes.py:160`) |
| Review/resolve flags | `PATCH /flags/{id}/resolve` (`flags.py:93`) |
| Treasury read + manual distribute | `GET /treasury`, `GET /treasury/logs`, `POST /treasury/distribute` |
| Escrow audit | Celery beat, daily 04:00 • **not an endpoint** |
| **Grant/revoke admin** | **Nowhere** • DB only |
| **Global pause / kill switch** | **Nowhere** |
| **Force-close or force-resolve a stuck market** | **Nowhere** • moderation only touches `pending_review` |
| **Audit of admin actions** | **Only ban/unban**, and the actor is buried in JSON metadata |

**There are no emergency controls in the API.** The closest things to operational levers are
`POST /admin/users/{id}/ban` (individual takedown), `POST /markets/{slug}/resolve` (forces
settlement behind two Redis locks), and `POST /admin/distribute-protocol-fees`. That is a real gap •
a prediction market should be able to halt trading.

### 7.3 Moderation decisions are unlogged

Approving and rejecting a market write **no audit event** and send **no notification** to the
author. The only record is the market's own `status` column changing.

---

## 8. The treasury (`api/treasury.py`)

### 8.1 What it is

A singleton administrative ledger of protocol-fee money: `balance`, `total_fees_collected`,
`total_fees_distributed`, plus an indexed `treasury_logs` movement log. The **singleton is enforced
by three constraints working together** • see `data-model.md` §3.6.

### 8.2 Race-free get-or-create

```python
from sqlalchemy.dialects.postgresql import insert
await db.execute(
    insert(Treasury).values(singleton=True).on_conflict_do_nothing(index_elements=["singleton"])
)
result = await db.execute(select(Treasury).limit(1))
```
> *"Uses INSERT … ON CONFLICT DO NOTHING to eliminate the race condition between SELECT and INSERT
> that existed in the previous implementation."*

`SELECT`-then-`INSERT`-if-missing is not safe under concurrency; this is. And the dialect import is
**function-local on purpose** • `on_conflict_do_nothing` is PostgreSQL-specific, so importing
`insert` from plain `sqlalchemy` gives a generic `Insert` without that method: an `AttributeError`
at runtime, i.e. a 500 on the distribute path. The comment documents it (`treasury.py:26-28`).

The unconditional re-`SELECT` is deliberate: *"either we just inserted it or it already existed."*

### 8.3 Reads are side-effect free by design

```python
# Read must be side-effect free. The singleton row is created by the write path
# (distribute), so a fresh install simply reports zeros here instead of INSERTing on a GET.
```
`GET /treasury` returns zeros if the row doesn't exist, admin-only. Nice detail: a `GET` should never
mutate, and someone thought about it.

### 8.4 `POST /treasury/distribute` • three real gaps

Amount is a **query parameter** (`:133`), max 100M, must be positive. Then:
`if treasury.balance < amount: raise ValidationError("Insufficient treasury balance")` (422),
otherwise decrement, increment `total_fees_distributed`, append a `TreasuryLog(event="distribution")`,
commit.

1. **No row lock.** Two concurrent distributions can both pass the balance check. The
   `ck_treasury_balance_nonneg` CHECK is then the last line of defence (the transaction rolls back →
   409). Compare `LiquidityService.distribute_protocol_fees`, which *does* take `FOR UPDATE`.
2. **No idempotency key.** A client retry after a lost response **double-distributes**.
3. **No actor recorded.** `TreasuryLog` gets `reference_type="manual"` but not *which admin*.

### 8.5 Where fees actually go • the part most people get wrong

**Fees accrue per pool, not in the treasury table.** On each fill:
```python
protocol_fee = trade_value * settings.protocol_fee_rate      # 0.01
pool.protocol_fees += protocol_fee
```
Two rates apply to a taker buy (`config.py:98-104`): `trading_fee_rate = 0.02` (stays in the pool
for LPs) and `protocol_fee_rate = 0.01` (accrues in `pool.protocol_fees`) • **effective take rate
3%**.

**`pool.protocol_fees` is a sub-ledger *inside* `pool.collateral`, not extra money.** Moving a fee out
requires zeroing the claim *and* debiting the backing dollars, in that order.

**And the real destination is a `Wallet` row for the `is_system` user, not the `treasury` table:**

1. **At settlement** (`tasks.py:929-948`): `pool.debit_collateral(owed_fees)` → `protocol_fees = 0`
   → credit the system wallet → write a `Transaction(type="protocol_fee")`.
2. **The daily sweep** (`liquidity_service.py:296-404`, beat 03:30): locks all pools with
   `protocol_fees > 0`, then per pool:
   ```python
   amount = min(owed, available)          # pay what the escrow actually holds
   if amount < owed:
       logger.error("Protocol fee sweep shortfall: ... carried_forward=...")
   pool.protocol_fees = owed - amount      # keep the unpaid remainder recorded
   ```
   > *"A shortfall means recorded fees exceed backing collateral • an invariant violation. Pay what
   > the escrow actually holds and keep the rest recorded, so the next sweep retries it; never zero
   > the record while handing the treasury less than it claims."*

   That's a beautiful principle: **the record and the cash are moved independently, and the record
   is never zeroed while cash is short.**

The system account gets a cryptographically unguessable password hash
(`settings.jwt_secret + secrets.token_hex(32)`, `tasks.py:782-784`) so it cannot be logged into by a
human.

### 8.6 The gap to state plainly

**Nothing in the application ever *increases* `treasury.balance` or `total_fees_collected`.** A
grep for `total_fees_collected` finds only the model, the schema, the read path, and
`scripts/seed.py:490` (which seeds `25000.00`). Likewise the documented `fee_collected` log event is
**never written** • `TreasuryLog` rows are written in exactly one place, on manual distribution. So
`GET /treasury/logs?event=fee_collected` would always return empty.

**Precise statement:** *the `treasury` table is a manual/administrative accounting record, seeded by
the seeder and decremented by the distribute endpoint; the real fee flow runs entirely through
`wallets.balance` for the `is_system` user and never touches it.* And on a fresh install with no
seed, `POST /treasury/distribute` correctly 422s • which is why the test accepts `status_code in
(200, 422)`.

---

## 9. Market activity feed (`api/market_activity.py`)

`GET /markets/{slug}/activity` • public, `limit` 1–100 default 20, **no caching at all** (it never
touches Redis), and un-rate-limited because all GETs bypass the limiter.

Returns four things in one round trip: `market_stats`, `top_holders_by_outcome`, `recent_trades`,
`recent_comments`.

### 9.1 `market_stats` computed in Python

```python
total     = float(pool.yes_shares) + float(pool.no_shares)
yes_price = float(pool.yes_shares) / total if total > 0 else 0.5
no_price  = float(pool.no_shares)  / total if total > 0 else 0.5
```

Same formula as the AMM's implied price. **`spread = abs(yes_price - no_price)`** • for a two-sided
pool this is always `2·|yes − 0.5|`. It is *not* the bid/ask spread of a book; describe it as
"how far from even". (This is a naming problem, not a maths problem.)

### 9.2 Top holders • the window-function answer to N+1

Getting the top 10 holders **per outcome** naively is one query per outcome. Instead:

```sql
WITH ranked AS (
  SELECT positions.*,
         row_number() OVER (PARTITION BY outcome_id ORDER BY shares_held DESC) AS rank
  FROM positions
  WHERE market_id = :mid AND outcome_id IN (:outcome_ids)
)
SELECT positions.*, users.username, ranked.rank
FROM positions
JOIN users ON positions.user_id = users.id
JOIN ranked  ON positions.id = ranked.id
WHERE ranked.rank <= 10
ORDER BY positions.outcome_id, ranked.rank
```

`PARTITION BY outcome_id` computes every outcome's leaderboard **in a single pass**. The in-code
comment: *"Batch-fetch all top holders across all outcomes in two queries: 1. Windowed rank per
outcome, 2. Join back to get usernames."*

**When to reach for a window function:** whenever you'd otherwise write "the top N *per group*".
`GROUP BY` + `MAX()` gives you one row per group; a window function gives you N rows per group
*without* a correlated subquery. That's the whole idea.

Three honest notes: **top 10 is hardcoded** (`ranked.c.rank <= 10`, `:96`) and is *not* derived from
the `limit` parameter; the backing index `ix_positions_user_market_outcome` is in the **wrong column
order** for this predicate (which filters `market_id` first), so the query is index-assisted only on
`market_id`; and there's **no `shares_held > 0` filter** here, unlike `GET /positions/`.

### 9.3 Price history and bucketing • and where `date_bin` is *not*

**`date_bin` appears nowhere in the codebase.** The only grep hit is `TODO.md`, proposing it as a
*future* fix. Bucketing is **pure Python**:

```python
interval_seconds = {"1m":60, "5m":300, "15m":900, "1h":3600, "4h":14400, "1d":86400}.get(interval, 300)
ts = int(r.snapshot_at.timestamp()); bucket = ts - (ts % interval_seconds)
```

The integer-modulo floor-division trick • cheap, and correct for any interval. An unknown interval
**silently falls back to 300s** rather than 422ing.

**Carry-forward** (`markets.py:504-522`): a `last_prices` dict remembers each outcome's most recent
price, and an outcome with no row in a bucket inherits it • so multi-outcome series are gap-free and
aligned.

Three things to flag:
- **The `LIMIT 5000` is applied *before* bucketing**, so a long window silently drops the *oldest*
  rows. A chart usually wants the opposite.
- **`total_volume` is summed across all rows in a bucket**, so a bucket holding both outcomes'
  snapshots reports 2× the market volume. That looks like a bug • describe it as observed, not intent.
- `from_date`/`to_date` are ISO strings parsed with `datetime.fromisoformat`; an unparseable value
  raises `ValueError` → the generic handler → **500, not 422**.

### 9.4 The snapshot producer

`snapshot_price_history` (beat every 300s, `tasks.py:589-684`):
- Only `Market.status == 'active'`.
- **Minute-window dedup** so retries are safe: compute `minute_floor`, `SELECT DISTINCT
  market_id, outcome_id FROM price_history WHERE snapshot_at >= floor AND < floor + 1min`, skip those
  pairs. That's what makes an at-least-once task effectively exactly-once.
- Binary markets get real `yes`/`no` prices from the pool shares; **multi-outcome markets get a
  uniform `1/len(outcomes)`** • i.e. the multi-outcome chart is **synthetic and flat by
  construction**. Own this one; it's a real limitation.

Related: `sync_amm_prices` (beat 60s) mirrors prices into `market:{id}:price` with a 300s TTL and
publishes a WS update **only if the price moved more than `1e-4`** (`tasks.py:552-571`) • a
deliberate anti-fan-out measure.

---

## 10. The trade tape (`api/trades.py`)

Two public endpoints: `GET /api/v1/trades` (global) and `GET /api/v1/markets/{slug}/trades`.

### 10.1 Keyset (cursor) pagination • and why the key is composite

The cursor is opaque base64url of `"{executed_at}|{trade_id}"`. The reason for the composite key is
written in the code (`trades.py:36-45`):

> *"Keyset filter for stable desc pagination. `executed_at` alone is not unique (same-ms trades), so
> `(executed_at, id)` is the tiebreak pair."*

```sql
WHERE (executed_at < :ts) OR (executed_at = :ts AND id < :uuid)
ORDER BY executed_at DESC, id DESC
```

**Why keyset beats `OFFSET`:** `OFFSET 100000` makes the database *walk and discard* 100,000 rows.
Keyset seeks straight to the position, so page 1000 costs the same as page 1 • and the result set
can't shift underneath you as new trades arrive.

The `+1` probe is also worth naming: `LIMIT page_size + 1` and `has_more = len(rows) > page_size`.
That answers "is there another page?" **without a `COUNT(*)`** over the whole feed • `COUNT` on a
high-write table is expensive, and the extra row costs nothing.

### 10.2 The offset guard • and the bug it replaced

```python
# Enforce keyset pagination when offset would exceed 1000.
# Previously the check was dead code (use_cursor was already True when offset > 1000),
# so deep offsets silently returned the first page.
if cursor is None and offset > 1000:
    raise ValidationError("Pagination offset exceeds 1000. Use cursor pagination instead.",
                          error_code="PAGINATION_LIMIT")
```

The comment describes a **dead-code bug**: the condition could never be true because of how
`use_cursor` was computed. So `?page=500` silently returned page 1. This is a nice example of a
"limit" that looks like it's working • read the boolean logic, don't trust the guard's presence.

### 10.3 The asymmetry to admit

The global feed has the offset guard; **the per-market feed does not** (`trades.py:137-138`) • it
applies `offset` unconditionally when no cursor is given. So `?page=1000000` on a per-market tape
forces a large sequential scan. Clear inconsistency between two nearly identical handlers.

### 10.4 Privacy

Both feeds return `username` for every trade. A public tape is correct for a prediction market, but
be aware it links a pseudonymous identity to market, side, size and price on every single trade.

---

## 11. Positions (`api/positions.py`)

`GET /positions/` • auth required, replica session.

```sql
SELECT * FROM positions WHERE user_id = :uid AND shares_held > 0
ORDER BY created_at DESC OFFSET (page-1)*page_size LIMIT page_size
```

- **Only non-zero positions.** A fully closed position disappears entirely • there's no "closed
  positions" view.
- **Batch enrichment**: markets, outcomes and pools are fetched in **3 queries** with `IN (...)`,
  not 3 per position (`positions.py:46-57`).
- **PnL** marks the holding to the current AMM price and subtracts cost basis:
  `unrealized = shares × (current_price − average_price)`, with `0.5` as the fallback for a missing
  or empty pool.

**The limitation to state:** `current_yes = yes_shares / (yes_shares + no_shares)`, and the `else`
branch prices **every non-`"yes"` outcome as `1 − yes_price`**. That is **only correct for binary
markets**. For an N-outcome market it mis-prices everything. The same binary assumption appears in
`alert_engine._tracked_side` and `market_activity.market_stats` • it's a *consistent* simplification
(the AMM itself is `BinaryAMM`), but it's a simplification, and multi-outcome positions are not
correctly valued.

Also note `page`/`page_size` have **no validation** here (unlike nearly every other paginated
endpoint) • `page=0` produces a negative offset → PostgreSQL error → 422 via `data_error_handler`,
and `page_size` is unbounded. And `settled_at` isn't exposed, so a client can't tell a claimed
position from a pending one.

---

## 12. The shared error contract (`api/exceptions.py`, `responses.py`, `handlers.py`)

### 12.1 The envelope

```python
def success_response(data, message=None):
    resp = {"success": True, "data": data}
    if message: resp["message"] = message

def error_response(message, error_code=None, details=None):
    resp = {"success": False, "error": message}
    if error_code: resp["error_code"] = error_code
    if details:    resp["details"] = details
```

Every client only has to parse **one shape**: `{success, data | error, error_code?, details?}`.
That is what makes the frontend's `extractMessage()` possible (`frontend.md` §4.2).

### 12.2 Custom exceptions

All extend `AppException(HTTPException)` and pack `message`/`error_code`/`details` into `detail` as
a **dict** • which is why `http_exception_handler` has to branch on `isinstance(detail, dict)`.

| Exception | HTTP | `error_code` |
|---|---|---|
| `NotFoundError` | 404 | `NOT_FOUND` |
| `ConflictError` | 409 | `CONFLICT` |
| `UnauthorizedError` | 401 | `UNAUTHORIZED` |
| `ForbiddenError` | 403 | `FORBIDDEN` |
| `ValidationError` | 422 | `VALIDATION_ERROR`, **overridable** |
| `InsufficientBalanceError` | 400 | `INSUFFICIENT_BALANCE` |
| `MarketClosedError` | 400 | `MARKET_CLOSED` |
| `IdempotencyError` | 409 | `IDEMPOTENCY_CONFLICT` |
| `SlippageExceededError` | 400 | `SLIPPAGE_EXCEEDED` |

The overridable `error_code` exists so a caller can name an *exact* condition • `MARKET_NOT_PENDING`,
`PAGINATION_LIMIT`, `NOTHING_TO_CLAIM`, `QUOTE_EXPIRED`, `POST_ONLY_WOULD_CROSS`. That's what makes
the frontend able to `switch` on `error_code` and say something specific instead of "request
failed".

### 12.3 The six handlers

| Handler | For | Client sees |
|---|---|---|
| `http_exception_handler` | any `HTTPException` | unwraps a dict `detail`; **preserves `exc.headers`** • that's how `Retry-After` on a 429 survives envelope conversion |
| `app_exception_handler` | `AppException` | same unwrapping via attributes |
| `validation_exception_handler` | `RequestValidationError` | **422** with `details.errors = [{field, message}]`, `field = "body.trigger_price"` style |
| `integrity_error_handler` | `IntegrityError` | **409 `DB_CONSTRAINT_ERROR`** • the constraint name and table go to the **log only**, never the client |
| `data_error_handler` | `DataError` | **422**, *"Invalid ID format"* when the asyncpg message mentions `uuid` |
| `generic_exception_handler` | anything else | **500**; production gets a bare `INTERNAL_ERROR`, dev gets a sanitised `hint` |

**`data_error_handler` deserves its own explanation** • its docstring is the best argument for
thoughtful error mapping in the repo:

> *"A bad identifier/literal reached the database (e.g. `GET /orders/not-a-uuid` sends an
> unparseable value into a `WHERE id = ...::uuid` clause). Without this handler the asyncpg error
> escapes to `generic_exception_handler` and the client sees a 500. **It's a caller input problem, so
> it belongs at 422.**"*

That is the right instinct: don't let a *caller's* bad input produce a 500 that reads like a server
fault.

### 12.4 Production output hardening

`_sanitise_for_client` (`handlers.py:20-29`) rewrites two patterns before anything reaches the client
in non-production:
```python
re.sub(r'Key \([^)]+\)=\([^)]+\)', "[key]", message)   # "Key (user_id)=(x) already exists"
re.sub(r'(?:\S*/){2,}\S*', "[internal]", message)     # /app/app/models/...
```
And `_APP_ENV` is read **once at import** with an explicit warning: *"Never use for security
decisions; only for information exposure."*

### 12.5 The one envelope violation

The origin check returns `{"error_code": "ORIGIN_NOT_ALLOWED", "message": ...}` • **no `success:
false`, no `error` key**, message under `message` instead of `error` (`middleware.py:199-203`). Every
other error path conforms. A client with a single error parser will mis-read this one. (The 429 path
in the same file *does* conform, and its comment states the goal explicitly: *"so clients only ever
have to parse one shape"*.)

---

## 13. The audit trail (`services/audit_service.py`)

### 13.1 15 event types

`login_success`, `login_fail`, `logout`, `logout_all`, `register`, `email_verified`,
`password_change`, `password_reset_request`, `password_reset_success`, `2fa_setup_requested`,
`2fa_enabled`, `2fa_disabled`, `account_banned`, `account_unbanned`, `suspicious_activity`.

### 13.2 `log()` never raises • on purpose

```python
try:
    db.add(AuthAuditEvent(...)); await db.commit()
except Exception as e:
    logger.error(f"Failed to write audit event {event}: {e}")
```
> *"Never let audit logging failures affect the auth flow."*

A failing audit write must not turn a valid login into a 500. And because it **commits on the shared
session**, the audit write is a **separate transaction** from the auth operation • so a failed
attempt is recorded even when the success it precedes rolls back. For forensics that's exactly right.

### 13.3 Four distinct `login_fail` reasons

`"user_not_found"`, `"wrong_password"`, `"2fa_code_missing"`, `"wrong_2fa_code"`
(`auth.py:948, 953, 968, 973`). Recording *why* a login failed is what makes brute-force detection
and account-enumeration forensics possible, instead of just "3 failures".

### 13.4 What the audit trail does **not** cover • say this before you're asked

No audit event is written for: comments, alerts, notification preferences, **market flags (including
who resolved them)**, **disputes (filing, proposal, adjudication, and the discarded `admin_note`)**,
**treasury distributions**, **market moderation (approve/reject)**, or **any admin action beyond
ban/unban**.

And for ban/unban, the *actor* only exists inside the JSON `metadata`
(`metadata={"admin_user_id": ...}`) • while `GET /admin/audit-events` **doesn't return `metadata`**.
So *"who banned whom" is not recoverable from the API.* That's the single most useful thing to admit
about this subsystem.

Also: the service's two read methods (`get_events_for_user`, `get_recent_events`) are **never
called** • `admin.py` re-implements the query inline, adding a `user_id` filter the service method
lacks. Dead code plus a duplicate.

---

## 14. Everything a panel could reasonably ask

| Question | Where the answer is |
|---|---|
| How do you avoid N+1 queries on a list endpoint? | Batch `IN (...)` enrichment • `positions.py:46-57`; window function • `market_activity.py:83-99`; batched count • `comments.py:105-115` |
| How do you stop two workers double-processing a job? | Atomic claim in Lua • `alert_engine.CLAIM_SCRIPT`; plus a guarded `UPDATE … WHERE triggered=false` |
| Why is a Redis index safe to lose? | It's a *pure index*; Postgres is the source of truth, and it self-repairs (`reindex_market_alerts`) |
| Why not `OFFSET` for pagination? | Keyset `(executed_at, id)`; deep offsets get worse linearly • `trades.py:36-45` |
| How do you know there's another page without `COUNT(*)`? | `LIMIT n+1` probe |
| What stops an admin from rigging a resolution? | A 48h dispute window before settlement, adjudicable exactly once • `disputes.py` |
| Why enqueue settlement *before* commit? | A broker outage must 503 before the DB records `resolved`, else the resolution is orphaned forever • `disputes.py:200-213` |
| Why is `disputed_at IS NULL` checked inside the payout loop? | Defence in depth against `claim_winnings` • `tasks.py:877-879` |
| How is a singleton row created safely? | `INSERT … ON CONFLICT DO NOTHING`, not select-then-insert • `treasury.py:20-41` |
| How do you stop a soft-deleted comment orphaning replies? | Soft delete keeps the row; replies filter `is_deleted IS FALSE` |
| What happens when Redis is down? | Each site differs deliberately: alerts degrade, the limit sweeper falls back to a **full scan**, `pop_dirty_markets` returns `None` to signal it |
| What's your weakest point here? | No admin audit trail beyond ban/unban, no kill switch, no pagination on the flag list, and per-market trades missing the offset guard |