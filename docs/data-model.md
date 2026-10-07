# Data Model — Every Table, Constraint and Index

The complete relational schema: **24 tables**, what each one is for, what the database actually
enforces, and — importantly — where the declared model and the provisioned schema **disagree**.

> Written from `backend/app/models/*.py` and `backend/migrations/versions/*.py`. Where the two
> disagree, this document says so explicitly rather than describing the intent.

---

## 0. How to read this

- **§1–2** — the conventions every table follows. Read once.
- **§3** — the entity-relationship map. One screen, the whole system.
- **§4** — the table reference, grouped by domain.
- **§5** — how money is modelled (`Numeric` scales, escrow discipline, signed amounts).
- **§6** — **what the database enforces vs what only the application enforces.** The most
  defensible section in this document.
- **§7–8** — the constraint and index catalogue, with the reason each one exists.
- **§9** — migrations, and a verified drift between models and migrations.
- **§10** — engine, pooling and session management.
- **§11** — the honest gaps, stated before you're asked.

---

## 1. Global conventions

### 1.1 Declaration style: imperative `Column()`, no annotations

Every model uses the **classic imperative mapping** style on a SQLAlchemy 2.0 `DeclarativeBase`:

```python
class User(Base, UUIDMixin, TimestampMixin):
    email = Column(String(255), unique=True, nullable=False, index=True)
```

**There is no `Mapped[]` / `mapped_column` anywhere in `app/models/`.** The Python type is inferred
by SQLAlchemy from the SQL type. If you claim "fully typed models", you are wrong — say
"SQLAlchemy 2.0 `DeclarativeBase` with the imperative `Column()` style".

Note the mixin order is `class X(Base, UUIDMixin, TimestampMixin)` — base class first, mixins after.

### 1.2 The two mixins (`app/models/base.py`)

```python
class Base(DeclarativeBase): ...                    # base.py:9-10

class TimestampMixin:                               # base.py:13-17
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False)
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(UTC),
                        onupdate=lambda: datetime.now(UTC), nullable=False)

class UUIDMixin:                                    # base.py:20-21
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
```

Three consequences worth knowing out loud:

1. **`updated_at` is Python-side only** (`onupdate=`), not a DB trigger. Raw SQL that updates a row
   will not touch `updated_at`.
2. **`id` has no `server_default`.** The UUID is generated in Python, so a raw `INSERT` without an
   id fails.
3. **20 of 24 tables carry `TimestampMixin`.** The four that do **not** are `refresh_tokens`,
   `sessions` (it declares its own `created_at` plus `last_active_at`), `trades` and
   `price_history` — because `executed_at` / `snapshot_at` are the meaningful times for those.

### 1.3 Two facts that surprise people

| Fact | Detail |
|---|---|
| **No database enums exist at all** | Zero `sa.Enum` / `postgresql.ENUM` in the schema. Every "enum" (`status`, `side`, `type`, `event`, `channel`, `condition`) is a plain `String(n)` whose allowed values are enforced **only in the application layer**. `models/market.py:22-23` states this outright: *"`markets.status` is a plain VARCHAR with no DB check constraint, so these values are a contract enforced by the API/service layer."* The single exception is `treasury.singleton` (§7). |
| **No `server_default` anywhere in the models** | Every default is a Python-side `default=`. A raw SQL insert, or any insert path that bypasses the ORM, silently misses them. |

There is **exactly one** Python `enum.Enum` in the whole backend: `LimitType` in
`services/rate_limit_service.py:16-21`, which selects a rate-limit bucket. It has no column.

### 1.4 Constraint naming

There is **no `MetaData(naming_convention=...)`** anywhere in the project. So constraints are either
named explicitly in the model (`ck_…`, `uq_…`) or left to PostgreSQL's auto-naming
(`<table>_<column>_check`, `<table>_<c1>_<c2>_key`). That absence is also why the one naming drift
in §9 exists.

Four tables have **unnamed** constraints: `orders` (3 CHECKs + 1 unique), `lp_shares` (unique),
`positions` (unique), `wallets` (unique).

### 1.5 Relationship loading

Every relationship uses the SQLAlchemy default `lazy="select"` (lazy load on attribute access).
There are **no** `lazy="selectin"`, `lazy="joined"`, `secondary` tables, or `backref`s anywhere.
`overlaps="…"` appears twice — `user.py:41` and `user.py:59` — purely to silence a SQLAlchemy warning
on the self-referential session/token relationship.

**Practical consequence:** touching a relationship attribute outside an explicit `selectinload()`
emits a query. That is exactly why list endpoints batch their enrichment (`positions.py:46-57`,
`market_activity.py:83-99`).

---

## 2. The two mixins, and how tables cluster

```
                          ┌──────────┐
                          │  users   │  identity
                          └────┬─────┘
        ┌──────────────┬───────┼────────┬──────────────┬───────────────┐
        ▼              ▼       ▼        ▼              ▼               ▼
  refresh_tokens   sessions  wallets  comments    notifications      referrals
                                  │     alerts      notification_prefs      (x2 FKs)
                                  ▼
                            transactions
```

```
  markets ──1:N──► outcomes          markets ──1:1──► liquidity_pools ──1:N──► lp_shares
     │  │  │  │                                                                 (to users)
     │  │  │  └──1:N──► price_history
     │  │  └─────1:N──► comments (self-referential via parent_id)
     │  ├────────────1:N──► disputes
     │  ├────────────1:N──► market_flags
     │  ├────────────1:N──► market_faqs
     │  └────────────1:N──► orders / positions / trades

  treasury (singleton) ──1:N──► treasury_logs
  auth_audit_events  (user_id ON DELETE SET NULL — survives user deletion)
```

---

## 3. Table reference

### 3.1 Identity & sessions

#### `users` — `app/models/user.py:10-27`
`UUIDMixin + TimestampMixin`. No FKs, no `__table_args__`.

| Column | Type | Null | Default | Extra |
|---|---|---|---|---|
| `id` | `UUID` | PK | `uuid4` | |
| `email` | `String(255)` | no | — | `unique=True, index=True` |
| `username` | `String(100)` | no | — | `index=True` |
| `password_hash` | `String(255)` | no | — | |
| `is_email_verified` | `Boolean` | no | `False` | |
| `is_active` | `Boolean` | no | `True` | |
| `is_admin` | `Boolean` | no | `False` | |
| `is_system` | `Boolean` | no | `False` | system/treasury account (`user.py:19`) |
| `referral_code` | `String(32)` | **yes** | — | `unique=True` |
| `totp_secret_encrypted` | `String(255)` | yes | — | Fernet ciphertext |
| `is_2fa_enabled` | `Boolean` | no | `False` | |
| `is_2fa_pending` | `Boolean` | no | `False` | setup started, not confirmed |

Relationships: `comments`, `referrals_made` (`foreign_keys="Referral.referrer_id"`),
`referrals_received` (`foreign_keys="Referral.referred_id"`).

#### `refresh_tokens` — `user.py:30-41` (no `TimestampMixin`)
| Column | Type | Null | Extra |
|---|---|---|---|
| `user_id` | `UUID` | no | FK → `users.id` `ON DELETE CASCADE` |
| `token_hash` | `String(255)` | no | `unique=True` — only the hash is stored |
| `expires_at` | `DateTime(tz)` | no | |
| `revoked` | `Boolean` | no | `index=True`, default `False` |
| `device_info` | `Text` | yes | |

#### `sessions` — `user.py:44-59` (no `TimestampMixin`)
| Column | Type | Null | Extra |
|---|---|---|---|
| `user_id` | `UUID` | no | FK CASCADE, `index=True` |
| `refresh_token_id` | `UUID` | no | FK CASCADE |
| `user_agent` / `ip_address` | `Text` / `String(45)` | yes | `ip_address` 45 chars = max IPv6 text length |
| `created_at` | `DateTime(tz)` | no | own declaration |
| `last_active_at` | `DateTime(tz)` | no | |
| `expires_at` | `DateTime(tz)` | no | |
| `revoked` | `Boolean` | no | `index=True` |

The **one-to-one** `sessions ↔ refresh_tokens` is expressed as `RefreshToken.current_session`
(`uselist=False`) plus `Session.refresh_token`.

### 3.2 Markets & outcomes

#### `markets` — `app/models/market.py:45-109`

**`status` is the field to talk about.** Seven module-level string constants, not an enum
(`market.py:24-30`):

| Constant | Value | Meaning |
|---|---|---|
| `STATUS_ACTIVE` | `active` | live and tradable |
| `STATUS_CLOSED` | `closed` | no new orders, awaiting resolution |
| `STATUS_RESOLVING` | `resolving` | resolution proposed, in dispute window |
| `STATUS_RESOLVED` | `resolved` | final |
| `STATUS_DISPUTE_WINDOW` | `dispute_window` | |
| `STATUS_PENDING_REVIEW` | `pending_review` | user-submitted, awaiting moderation |
| `STATUS_REJECTED` | `rejected` | moderation declined |

`PUBLIC_STATUSES = (active, closed, resolving, resolved, dispute_window)` (`market.py:33-39`);
`UNPUBLISHED_STATUSES = (pending_review, rejected)` (`:42`).

Columns (22):

| Column | Type | Null | Default | Extra |
|---|---|---|---|---|
| `slug` | `String(255)` | no | — | `unique=True, index=True` |
| `question` | `String(1000)` | no | — | **GIN expression index** (§8) |
| `description` | `String(5000)` | yes | — | |
| `category` / `subcategory` | `String(100)` | yes | — | `category` indexed |
| `image_url` | `String(500)` | yes | — | |
| `created_by` | `UUID` | yes | — | **no FK** |
| `status` | `String(20)` | no | `"active"` | `index=True` |
| `resolved_at` | `DateTime(tz)` | yes | — | |
| `resolution_criteria` | `String(2000)` | yes | — | |
| `resolution_source` | `String(1000)` | yes | — | |
| `winning_outcome_id` | `UUID` | yes | — | **no FK** — see §10 (gap 2) |
| `proposed_outcome_id` | `UUID` | yes | — | **no FK** |
| `dispute_deadline` | `DateTime(tz)` | yes | — | set to now + 48h |
| `resolution_proposed_at` | `DateTime(tz)` | yes | — | |
| `opens_at` | `DateTime(tz)` | no | `now(UTC)` | |
| `closes_at` | `DateTime(tz)` | no | — | |
| `total_liquidity` | `Numeric(20,8)` | no | `0` | |
| `total_volume` | `Numeric(20,8)` | no | `0` | |
| `num_trades` | `Integer` | no | `0` | |

`__table_args__` (`market.py:94-109`):
```python
CheckConstraint("total_liquidity >= 0", name="ck_markets_liquidity_nonneg"),
CheckConstraint("total_volume >= 0", name="ck_markets_volume_nonneg"),
Index("ix_markets_status_closes_at", "status", "closes_at"),
Index("ix_markets_question_fts", func.to_tsvector(literal_column("'english'"), question),
      postgresql_using="gin"),
```

**Why that FTS index is shaped that way** — the code comments explain it, and it is good viva
material: PostgreSQL has no default GIN opclass for `varchar`/`text`, so a plain GIN index on
`question` cannot be created. The index must be on the **exact expression** the query uses
(`plainto_tsquery('english', q) @@ to_tsvector('english', question)`), and `'english'` is wrapped in
`literal_column` so it renders as a literal the planner can match rather than a bind parameter.

#### `outcomes` — `market.py:112-127`
`__table_args__` is declared *before* the columns here — legal, because it references columns by
string name.
```python
CheckConstraint("outcome_index >= 0"),                              # unnamed
Index("ix_outcomes_market_id", "market_id"),
UniqueConstraint("market_id", "outcome_index", name="uq_outcome_market_index"),
```
Columns: `market_id` (FK CASCADE), `name` `String(100)`, `outcome_index` `Integer`,
`image_url` `String(500)`.

`outcome_index` is the ordering key, and **0 = YES, 1 = NO** for a binary market (`market.py:122`).
`uq_outcome_market_index` guarantees at most one outcome per index per market.

#### The four small market satellites

| Table | File | Purpose | Notable |
|---|---|---|---|
| `market_faqs` | `faq.py:8-16` | Per-market Q&A shown on the detail page | `question`/`answer` `Text`, `display_order` `Integer` nullable. **No index on `market_id`** — the only FK and the only access path. |
| `market_flags` | `flag.py:8-19` | A user reporting a market | `reason` `Text`, `status` `String(20)` default `"open"`, `index=True`. **No uniqueness on `(market_id, user_id)`** — dedup is app-level (`api/flags.py:31-36`). |
| `disputes` | `dispute.py:8-18` | A challenge to a proposed resolution | `evidence` `Text`, `evidence_url` `String(1000)`, `status` default `"open"`, `index=True`. **No uniqueness on `(market_id, user_id)`.** |
| `price_history` | `price_history.py:9-21` | Chart time-series | `price` `Numeric(10,6)`, `total_volume` `Numeric(20,8)` nullable, `snapshot_at` `DateTime(tz)`. **No relationships declared at all.** |

### 3.3 Trading

#### `liquidity_pools` — `app/models/liquidity.py:32-102`
One pool per market (`market_id` is `unique=True`).

| Column | Type | Default | Meaning |
|---|---|---|---|
| `market_id` | `UUID` | — | FK CASCADE, `unique=True` → 1:1 |
| `yes_shares` | `Numeric(20,8)` | `0` | share reserve |
| `no_shares` | `Numeric(20,8)` | `0` | share reserve |
| `collateral` | `Numeric(20,8)` | `0` | **USDC escrow — the single source of truth for payout capacity** |
| `fee_rate` | `Numeric(5,4)` | `0.02` | LP fee |
| `lp_token_supply` | `Numeric(20,8)` | `0` | LP shares outstanding |
| `protocol_fees` | `Numeric(20,8)` | `0` | **a sub-ledger inside `collateral`, not extra money** |

**No CHECK constraint on `collateral`.** The discipline is enforced by two methods:

```python
def credit_collateral(self, amount):        # liquidity.py:61-71
    if amount < 0: raise ValueError(...)    # refuses a negative credit

def debit_collateral(self, amount):         # liquidity.py:73-97
    if amount <= 0: return Decimal(0)       # zero is a no-op, not an error
    if amount > self.collateral:
        raise EscrowShortfallError(f"pool {self.id}: collateral shortfall — "
                                   f"owe {amount}, hold {available}")
    self.collateral -= amount

def can_cover(self, amount): ...            # liquidity.py:99-102 — read-only probe
```

`EscrowShortfallError(RuntimeError)` (`liquidity.py:10-22`) is raised deliberately rather than
absorbed: **there is no "pay what you can" mode.** A partially-paid obligation would stay
claimable forever with nobody tracking it.

Note also `pool.protocol_fees` — moving a fee out requires zeroing the claim *and* debiting the
backing dollars, in that order.

#### `lp_shares` — `liquidity.py:105-115`
`pool_id` + `user_id` (both FK CASCADE, **no indexes**), `lp_tokens` `Numeric(20,8)`,
`collateral_deposited` `Numeric(20,8)`. `UniqueConstraint("pool_id", "user_id")` (unnamed) — one LP
row per user per pool.

#### `orders` — `app/models/order.py:17-63`

`__table_args__` — **three CHECKs, one unique, seven composite indexes**:
```python
CheckConstraint("amount > 0"), CheckConstraint("price >= 0"), CheckConstraint("price <= 1"),
UniqueConstraint("user_id", "client_order_id", name="uq_orders_user_client_order"),
Index("ix_orders_user_created",              "user_id", "created_at"),
Index("ix_orders_market_status",             "market_id", "status"),
Index("ix_orders_market_status_type",        "market_id", "status", "order_type"),
Index("ix_orders_status_expires",            "status", "expires_at"),
Index("ix_orders_type_status_remaining",     "order_type", "status", "remaining_amount"),
Index("ix_orders_market_outcome_side_price", "market_id", "outcome_id", "side", "price"),
Index("ix_orders_market_outcome_price",      "market_id", "outcome_id", "price"),
```

| Column | Type | Null | Allowed values (from code comments) |
|---|---|---|---|
| `user_id` / `market_id` / `outcome_id` | `UUID` | no | all FK CASCADE |
| `side` | `String(10)` | no | `buy`, `sell` |
| `order_type` | `String(20)` | no | `market`, `limit`, `fill_or_kill` |
| `amount` | `Numeric(20,8)` | no | quantity of **shares** |
| `price` | `Numeric(10,6)` | no | per share, 0–1 |
| `remaining_amount` | `Numeric(20,8)` | **yes** | for `buy` this is a **USDC budget** |
| `status` | `String(20)` | no | `pending`, `partial`, `filled`, `cancelled`, `expired` (+ transient `duplicate`), `index=True` |
| `expires_at` | `DateTime(tz)` | yes | |
| `shares_bought` / `shares_sold` / `fees_paid` | `Numeric(20,8)` | yes | |
| `slippage` | `Numeric(10,6)` | yes | |
| `executed_at` | `DateTime(tz)` | yes | |
| `client_order_id` | `String(100)` | yes | `index=True` — **the idempotency key** |

`price <= 1` is the schema's structural statement that this is a prediction market: a share can
never cost more than the $1 it settles at.

#### `positions` — `app/models/position.py:15-38`
```python
UniqueConstraint("user_id", "market_id", "outcome_id"),
Index("ix_positions_user_id", "user_id"),
Index("ix_positions_created_at", "created_at"),
Index("ix_positions_user_market_outcome", "user_id", "market_id", "outcome_id"),
CheckConstraint("shares_held >= 0", name="ck_positions_shares_held_non_negative"),
```

`shares_held` `Numeric(20,8)`, `average_price` `Numeric(10,6)` (cost basis), `realized_pnl`
`Numeric(20,8)`.

> **`settled_at` is a `Numeric(20,8)`, not a timestamp** (`position.py:33-34`). It is a Decimal UTC
> timestamp used as an **idempotency sentinel**: `NULL` = unsettled, any value = settled. It is the
> guard that stops `claim_winnings` paying twice. It is *not* exposed in `PositionResponse`, so a
> client cannot tell a claimed position from a pending one.

`ix_positions_user_id` is redundant — its column is the leading column of both the unique
constraint's index and `ix_positions_user_market_outcome`.

#### `trades` — `app/models/trade.py:10-27` (no `TimestampMixin`)
Indexes: `ix_trades_user_id`, `ix_trades_market_id`, `ix_trades_executed_at`,
`ix_trades_user_executed (user_id, executed_at)`.

| Column | Type | Note |
|---|---|---|
| `user_id` / `market_id` | `UUID` | FK CASCADE |
| `outcome` | `String(100)` | **the outcome *name*, not a FK to `outcomes.id`** |
| `side` | `String(10)` | |
| `price` | **`Numeric(10,8)`** | scale **8**, unlike `orders.price` (6) |
| `amount` | `Numeric(20,8)` | |
| `executed_at` | `DateTime(tz)` | default `now(UTC)` |

`trade.py` declares **no `user` relationship** despite holding `user_id`. `executed_at` is not
unique — which is precisely why the trade tape needs a `(executed_at, id)` keyset cursor
(`api/trades.py:36-45`).

### 3.4 Money

#### `wallets` — `app/models/wallet.py:18-33`
```python
UniqueConstraint("user_id", "currency"),
CheckConstraint("balance >= 0",        name="ck_wallets_balance_nonneg"),
CheckConstraint("locked_balance >= 0", name="ck_wallets_locked_nonneg"),
CheckConstraint("locked_balance <= balance", name="ck_wallets_locked_lte_balance"),
```
`user_id` is *also* `unique=True`, so one wallet per user; the composite unique is therefore
unreachable but harmless.

Two balances, and the distinction matters: `balance` is spendable; `locked_balance` is reserved
money sitting inside `balance` for a resting limit order. Available = `balance - locked_balance`,
and every buy path checks that expression rather than `balance` alone — otherwise locked funds
would be spendable twice.

> **All three CHECK constraints are absent from the migrations** — see §9.2. This is the single most
> important honest gap in the data model.

#### `transactions` — `wallet.py:36-78`
The append-only money ledger. Every balance change writes one row.

| Column | Type | Note |
|---|---|---|
| `user_id` / `wallet_id` | `UUID` | FK CASCADE; **no `user` relationship declared** |
| `type` | `String(30)` | `deposit, withdrawal, trade_buy, trade_sell, fee, liquidity_add, liquidity_remove, settlement_win, settlement_loss, refund, split, merge` |
| `amount` | `Numeric(20,8)` | **signed: positive = credit, negative = debit** |
| `balance_after` | `Numeric(20,8)` | running balance snapshot — makes the ledger self-auditing |
| `reference_id` | `String(255)` | the idempotency key |
| `reference_type` | `String(50)` | `order`, `withdrawal`, `liquidity_pool` |
| `status` | `String(20)` | `pending`, `completed`, `failed` |
| `blockchain_tx_hash` | `String(66)` | `index=True`, 0x + 64 |
| `confirmations` | `Integer` | default `0` |
| `extra_data` | `postgresql.JSONB` | default `{}` |

Two **partial unique indexes** that are the database-level idempotency guarantee
(`wallet.py:45-56`):
```python
Index("uq_transactions_withdrawal_ref", "reference_id", unique=True,
      postgresql_where=text("type = 'withdrawal' AND reference_id IS NOT NULL")),
Index("uq_transactions_deposit_ref", "reference_id", unique=True,
      postgresql_where=text("type = 'deposit' AND reference_id IS NOT NULL")),
```
One withdrawal per idempotency key (safe under a concurrent double-submit); one deposit per Stripe
`payment_intent_id` (safe under webhook double-delivery). `NULL` reference ids are excluded by the
predicate, so ordinary rows are unaffected. Despite the `uq_` prefix these are **indexes, not
constraints** — worth saying so.

### 3.5 Platform & social

#### `comments` — `app/models/comment.py:8-38`
```python
Index("ix_comments_market_id", "market_id"),
Index("ix_comments_parent_id", "parent_id"),
Index("ix_comments_market_parent", "market_id", "parent_id"),
```
Columns: `market_id`, `user_id`, `parent_id` (self-FK CASCADE, nullable), `content` `Text`,
`depth` `Integer` nullable default `0`, `is_deleted` `Boolean` nullable default `False`.

The thread is **soft-deleted** (`is_deleted`) so replies keep their parent. The self-referential
`parent` / `replies` pair is assigned *after* the class body (`comment.py:27-38`) with
`remote_side=Comment.__table__.c.id` — the standard way to disambiguate a one-to-many self-reference.

`depth` exists to bound nesting (the API caps it at 3) but has **no CHECK constraint** — a raw
insert can nest arbitrarily deep.

#### `alerts` — `app/models/alert.py:17-34`
Two **partial indexes** with the predicate `triggered = false`:
```python
Index("ix_alerts_market_pending", "market_id", postgresql_where=text("triggered = false")),
Index("ix_alerts_user_pending",  "user_id",     postgresql_where=text("triggered = false")),
```
`outcome` `String(10)` nullable — `"yes"`, `"no"`, or **NULL meaning either**; `condition`
`String(10)` = `above`/`below`; `trigger_price` **`Numeric(10,8)`**; `triggered` default `False`;
`triggered_at` nullable. No `Market.alerts` relationship exists.

#### `notifications` / `notification_preferences` — `app/models/notification.py`
`notifications`: `user_id` (indexed), `type` `String(50)` (indexed), `title` `String(500)`,
`body` `Text`, `data` `sqlalchemy.JSON` — **generic JSON, not JSONB**, unlike
`transactions.extra_data`; `read_at` nullable (NULL = unread); `channel` `String(20)` default
`"in_app"` (`in_app, email, push`).

`notification_preferences`: `user_id` `unique=True`, and **eight nullable** boolean flags —
`email_alerts`, `email_order_fills`, `email_market_resolution`, `email_weekly_digest` (default
`False`), `push_alerts`, `push_order_fills`, `push_market_resolution`. One row per user.

#### `referrals` — `app/models/referral.py:10-21`
**Two FKs to `users`**: `referrer_id` and `referred_id`, both CASCADE. `referral_code` `String(32)`
indexed, `status` nullable default `"pending"`, `reward_amount` `Numeric(20,8)` nullable default
`Decimal(0)` — the only model default that constructs an explicit `Decimal`.

**No uniqueness on `referred_id`** — one user being referred more than once is prevented in the
application, not the database. The two `User` relationships disambiguate with
`foreign_keys=[referrer_id]` / `foreign_keys=[referred_id]`.

### 3.6 Governance & money-ops

#### `treasury` (singular table) — `app/models/treasury.py:16-29`
`balance`, `total_fees_collected`, `total_fees_distributed` all `Numeric(20,8)` default `0`, plus
a `singleton` `Boolean` default `True`.

**The singleton is enforced by three constraints working together** — the only place a "value" is
DB-enforced in this schema:
```python
CheckConstraint("balance >= 0",        name="ck_treasury_balance_nonneg"),
UniqueConstraint("singleton",          name="uq_treasury_singleton"),
CheckConstraint("singleton = true",    name="ck_treasury_singleton_true"),
```
`singleton = true` forces every row to the constant; `UNIQUE(singleton)` allows at most one row
holding it. Together the table is structurally **0-or-1 rows**. A second row is a unique
violation; a row with `singleton = false` is a check violation.

The code comment at `treasury.py:24-25` records a real hazard: *"`unique=True` here as well makes
autogenerate emit a second, unnamed one"* — hence the named constraint in `__table_args__` only.

`treasury_logs`: `treasury_id` (FK CASCADE), `event` `String(50)` **indexed**
(`fee_collected`, `distribution`), `amount` `Numeric(20,8)`, `reference_type`, `reference_id`.

#### `auth_audit_events` — `app/models/audit.py:9-41`
Docstring: *"Immutable audit log of authentication events. Used for forensics, anomaly detection,
and compliance."*

| Column | Type | Note |
|---|---|---|
| `user_id` | `UUID` | **FK `ON DELETE SET NULL`** — the only non-CASCADE FK in the schema |
| `email` | `String(255)` | `index=True` — survives user deletion |
| `ip_address` | `String(45)` | `index=True` |
| `user_agent` | `Text` | |
| `event` | `String(64)` | `index=True`, 15 values |
| `metadata_` | `Text` → DB column **`metadata`** | attribute renamed to dodge SQLAlchemy's reserved word; holds a **JSON string** in a TEXT column |
| `success` | `String(10)` | `"success"` / `"failure"` — a string, not a boolean, so partial states are representable |
| `failure_reason` | `String(128)` | |

`ON DELETE SET NULL` is the right call: a failed login on an unknown email has `user_id = NULL`, and
a forensic row must outlive the account it describes.

The 15 event values are listed in `audit.py:23-27`:
`login_success, login_fail, logout, register, email_verified, password_change,
password_reset_request, password_reset_success, 2fa_enabled, 2fa_disabled,
2fa_setup_requested, account_banned, account_unbanned, account_locked, suspicious_activity`.

Two mismatches worth admitting: `suspicious_activity` is **never written** by any code, while
`auth.py:1104` writes `"session_revoked"`, which isn't in the list. The `Literal` type hint has no
runtime enforcement, so both pass silently.

---

## 4. How money is modelled

### 4.1 `Numeric` scale is not uniform — this trips people up

| Column | Type |
|---|---|
| `orders.price`, `positions.average_price`, `price_history.price`, `orders.slippage` | `Numeric(10,6)` |
| `trades.price`, `alerts.trigger_price` | **`Numeric(10,8)`** |
| all share/amount/collateral/balance columns | `Numeric(20,8)` |
| `liquidity_pools.fee_rate` | `Numeric(5,4)` |
| `positions.settled_at` | `Numeric(20,8)` (a timestamp, §3.3) |

### 4.2 The four escrow rules

The single ledger is `liquidity_pools.collateral`. Every rule in the codebase is an expression of
one idea: **never create a claim you cannot pay.**

1. **Credit only from a real source.** Splitting `$1` credits $1 and mints a YES/NO pair; a buy
   credits what the buyer paid.
2. **`debit_collateral` is strict** — it raises `EscrowShortfallError` rather than partially paying.
3. **Settlement pre-flights before touching a wallet** (`tasks.py:834-873`): compute
   `winner_total + protocol_fees`, and if that exceeds `collateral`, abort the *entire* settlement
   and leave every position claimable. It never pays a winner partially and stamps the rest settled.
4. **A nightly audit re-checks the arithmetic** (`escrow_audit.py`, beat 04:00) so a broken ledger
   surfaces overnight rather than at resolution.

### 4.3 `positions.settled_at` and `transactions.reference_id` are the two idempotency columns

Both are "has this already happened?" flags, and both are backed by an index that makes the
guarantee structural rather than procedural.

---

## 5. What the database enforces vs what only the application enforces

**This is the section to rehearse.** The honest answer is: the database enforces less than the
model files claim.

| Invariant | Enforced by | Where |
|---|---|---|
| Order price in 0–1, amount > 0 | ✅ **DB CHECK** | `orders` (`migrations:374-376`) |
| Positions can't go negative | ✅ **DB CHECK** | `ck_positions_shares_held_non_negative` |
| `outcome_index >= 0`, unique per market | ✅ **DB** | `outcomes` |
| Wallet `balance >= 0` | ⚠️ **model only** — missing from migrations | `wallet.py:22` |
| Wallet `locked_balance >= 0` | ⚠️ **model only** | `wallet.py:23` |
| `locked_balance <= balance` | ⚠️ **model only** | `wallet.py:24` |
| `markets.total_liquidity >= 0` | ⚠️ **model only** | `market.py:95` |
| `markets.total_volume >= 0` | ⚠️ **model only** | `market.py:96` |
| Treasury `balance >= 0` | ⚠️ present but **unnamed** in migration (`treasury_balance_check`) | `treasury.py:19` |
| Treasury singleton | ✅ **DB, triple** | `treasury.py:18-22` |
| One withdrawal / deposit per reference | ✅ **DB partial unique index** | `wallet.py:45-56` |
| One order per `(user_id, client_order_id)` | ✅ **DB unique** | `orders` |
| One LP row per `(pool_id, user_id)` | ✅ **DB unique** | `liquidity.py:107` |
| One position per `(user, market, outcome)` | ✅ **DB unique** | `position.py:17` |
| **Pool collateral never negative** | ❌ **application only** — `debit_collateral` | `liquidity.py:73-97` |
| **Escrow always covers open claims** | ❌ **application only** — settlement pre-flight + nightly audit | `tasks.py:834-873`, `escrow_audit.py` |
| **A position is claimed at most once** | ❌ **application only** — `settled_at IS NULL` re-check | `tasks.py:877-879` |
| `markets.status` ∈ the 7 values | ❌ **application only**, by explicit design | `market.py:22-23` |
| Every other enum-like `String` | ❌ **application only** | §1.3 |
| Comment depth ≤ 3 | ❌ **application only** — `MAX_DEPTH` | `api/comments.py:20` |
| One flag per `(user, market)` | ❌ **application only** | `api/flags.py:31-36` |
| One referral per referred user | ❌ **application only** | `api/referrals.py` |
| `updated_at` maintenance | ❌ **ORM-only** (`onupdate=`) | `base.py:16-17` |

**The one-sentence answer:** *"The database enforces identity, uniqueness, ranges and idempotency
keys; money conservation is enforced by the service layer, and the escrow arithmetic is
re-verified by a nightly audit."* That is a defensible position — but you must know about the five
missing CHECK constraints rather than claiming the DB prevents negative balances.

---

## 6. Constraint catalogue

| Constraint | Table | Expression |
|---|---|---|
| `amount > 0` | `orders` | unnamed |
| `price >= 0` | `orders` | unnamed |
| `price <= 1` | `orders` | unnamed |
| `uq_orders_user_client_order` | `orders` | `(user_id, client_order_id)` |
| `outcome_index >= 0` | `outcomes` | unnamed |
| `uq_outcome_market_index` | `outcomes` | `(market_id, outcome_index)` |
| `ck_positions_shares_held_non_negative` | `positions` | `shares_held >= 0` |
| — | `positions` | `(user_id, market_id, outcome_id)` unnamed |
| `ck_wallets_balance_nonneg` ⚠️ | `wallets` | `balance >= 0` |
| `ck_wallets_locked_nonneg` ⚠️ | `wallets` | `locked_balance >= 0` |
| `ck_wallets_locked_lte_balance` ⚠️ | `wallets` | `locked_balance <= balance` |
| — | `wallets` | `(user_id, currency)` unnamed |
| — | `lp_shares` | `(pool_id, user_id)` unnamed |
| `ck_markets_liquidity_nonneg` ⚠️ | `markets` | `total_liquidity >= 0` |
| `ck_markets_volume_nonneg` ⚠️ | `markets` | `total_volume >= 0` |
| `ck_treasury_balance_nonneg` | `treasury` | `balance >= 0` (name drifts, §9.3) |
| `uq_treasury_singleton` | `treasury` | `(singleton)` |
| `ck_treasury_singleton_true` | `treasury` | `singleton = true` |

⚠️ = declared in the model, **absent from the provisioned schema**.

---

## 7. Index catalogue — and *why* each exists

### 7.1 The order-book index

`ix_orders_market_outcome_side_price (market_id, outcome_id, side, price)` is the workhorse. The
book query filters by market + outcome + side and orders by price — so a 4-column index whose
leading three columns are equality predicates and whose last is the sort key serves it without a
sort. `ix_orders_market_outcome_price (market_id, outcome_id, price)` is the 3-column variant for
queries that don't filter by side.

### 7.2 The sweeper indexes

Two support the 30-second background tasks:
- `ix_orders_status_expires (status, expires_at)` — `expire_stale_orders` scans
  `status IN ('pending','partial') AND expires_at <= now()`.
- `ix_orders_type_status_remaining (order_type, status, remaining_amount)` — `check_limit_order_execution`
  finds candidate resting orders.

### 7.3 Composite indexes matching real access patterns

`ix_markets_status_closes_at (status, closes_at)` serves `check_markets_ready_to_resolve`
(`status = 'active' AND closes_at <= now()`). `ix_positions_user_market_outcome`,
`ix_trades_user_executed`, `ix_transactions_user_created`, `ix_price_history_market_snapshot`,
`ix_comments_market_parent` each mirror one specific query.

### 7.4 Partial indexes — where "the interesting rows" is a predicate

- `alerts`: both indexes are `WHERE triggered = false`. The sweeper only ever wants un-triggered
  alerts, and once triggered a row is dead weight in the index.
- `transactions`: both uniqueness indexes are partial on `type` **and** `reference_id IS NOT NULL`.

### 7.5 Full-text search

`ix_markets_question_fts` — GIN on `to_tsvector('english', question)`, backing
`plainto_tsquery('english', q) @@ to_tsvector('english', question)`. See §3.2 for why the index must
carry the expression.

### 7.6 Analytics indexes on the audit log

`ix_auth_audit_user_event (user_id, event)`, `ix_auth_audit_email_event (email, event)`,
`ix_auth_audit_created_at (created_at)` — "under comment: Derived for analytics" (`audit.py:34`).

---

## 8. Migrations — and a verified drift

### 8.1 The chain

`backend/migrations/versions/` is a single **linear** history of five revisions:

```
763d787eabf1  initial schema
      ↓
25165f81480b  add withdrawal/deposit idempotency partial unique indexes
      ↓
3c95a685f3f9  add alert pending partial indexes
      ↓
9b4f2a71c3d8  add missing model indexes
      ↓
0ccfc38683a8  add blockchain tx fields + treasury constraints          ← head
```

`migrations/` is excluded from ruff entirely (`pyproject.toml:58`).

### 8.2 Drift #1 — five CHECK constraints exist only in the models

This is verifiable in about thirty seconds:

```bash
cd backend
grep -rn "CheckConstraint" migrations/versions/*.py
grep -rn "ck_wallets\|ck_markets" migrations/ app/models/
```

The migrations contain only four CHECKs: `treasury.balance >= 0` (`763d787eabf1:30`),
`outcome_index >= 0` (`:282`), the three order ones (`:374-376`), and
`shares_held >= 0` (`:401`). The `markets` `create_table` block (`:74-100`) and the `wallets` block
(`:177-189`) contain **no `CheckConstraint` line at all**, and `ck_wallets` / `ck_markets` appear
**only** in `app/models/`.

**Impact:** a database built by `alembic upgrade head` does **not** prevent a negative wallet
balance, a negative `locked_balance`, `locked_balance > balance`, or negative market liquidity /
volume. In a migrated database that safety is enforced by application code only.

### 8.3 Drift #2 and #3 — smaller, but name them

- **`ck_treasury_balance_nonneg` name mismatch.** The model names it; the migration declares
  `sa.CheckConstraint('balance >= 0')` unnamed (`763d787eabf1:30`), so PostgreSQL names it
  `treasury_balance_check`. Same expression, different name — autogenerate would forever want to
  drop and recreate it.
- **Leftover `server_default`.** `0ccfc38683a8:25` adds `transactions.confirmations` with
  `server_default='0'` and never removes it, while the *same file* explicitly adds **and then
  removes** `server_default='true'` on `treasury.singleton` (`:27,31`) to match the ORM. Because
  `migrations/env.py` sets no `compare_server_default=True`, autogenerate will never surface this.

### 8.4 Drift #4 — the "initial" migration was hand-edited

`763d787eabf1` already contains indexes that the *later* `9b4f2a71c3d8` describes as never having
existed — which is consistent — but it also contains `__table_args__` indexes of the *current*
models (`ix_markets_status_closes_at`, `ix_liquidity_pools_market_id`, `ix_outcomes_market_id`,
`ix_trades_*`, `ix_transactions_wallet_id`, `ix_auth_audit_*_event`). Those are exactly the things a
first autogenerate of an older model set would omit, so the file has been reconciled by hand. The
CHECK constraints were evidently **not** included in that reconciliation.

The practical consequence: the migration history is not a faithful record of the original schema,
and because `9b4f2a71c3d8` guards every `create_index` with `if_not_exists=True`, the two drift in
opposite directions without either raising.

### 8.5 What *is* fully in sync

All 24 tables and their columns, types (including every `Numeric` precision/scale) and nullability;
every `index=True` column; the unique-index behaviour of `users.email` / `markets.slug`; all five
partial indexes (predicates match character-for-character); the FTS expression index; the named
constraints `uq_outcome_market_index`, `uq_orders_user_client_order`,
`ck_positions_shares_held_non_negative`, `uq_treasury_singleton`, `ck_treasury_singleton_true`;
every FK target and every `ondelete` value — including the lone `SET NULL`; and the correct absence
of `created_at`/`updated_at` on the four `UUIDMixin`-only tables.

### 8.6 "Which is the source of truth?"

**Migrations — and it is deliberate.** `Base.metadata.create_all()` is never invoked anywhere in
`app/` or `tests/`. Startup only inspects and warns (`app/app.py:189-194`: *"migrations own the
schema (no auto create_all)"*). Tests `DROP DATABASE … WITH (FORCE)`, recreate, then run
`alembic upgrade head` on every run (`tests/conftest.py:80-135`) — with the stated rationale that a
stale schema must never mask a failure.

So the net position is: **the provisioned schema is the models minus the five CHECK constraints
above, plus one renamed constraint and one extra server default.** Interesting irony: a database
built by `create_all` would be *stronger* on CHECKs but would lack the partial unique indexes, so
neither path alone is correct.

---

## 9. Engine, pooling and sessions — `app/database.py` (98 lines)

### 9.1 Two engines

```python
@lru_cache
def _get_engine():                    # database.py:9-20
    return create_async_engine(
        settings.database_url, echo=settings.debug,
        poolclass=AsyncAdaptedQueuePool,
        pool_size=settings.db_pool_size, max_overflow=settings.db_max_overflow,
        pool_timeout=settings.db_pool_timeout,
        pool_pre_ping=True, pool_recycle=3600)

@lru_cache
def _get_replica_engine():            # database.py:23-34
    replica_url = settings.database_replica_url or settings.database_url   # falls back to primary
    ... pool_pre_ping=True, echo=False, NO pool_recycle
```

`@lru_cache` gives exactly one engine per process; `app.py:208-209` disposes both on shutdown.

- `pool_pre_ping=True` recycles connections broken by an idle proxy or firewall — essential behind
  a load balancer.
- `pool_recycle=3600` bounds absolute connection age (primary only).
- `AsyncAdaptedQueuePool` is SQLAlchemy's async-aware wrapper around `QueuePool`.

### 9.2 The pool arithmetic — know these numbers

| Setting | Default | Note |
|---|---|---|
| `db_pool_size` | `5` | `config.py:34` comments: *"per worker; 5*8 workers=40 < postgres max 100"* |
| `db_max_overflow` | `5` | |
| `db_pool_timeout` | `30` | seconds to wait for a connection |

With gunicorn's 8 workers that's 40 steady connections + up to 40 overflow = 80, under PostgreSQL's
100 default. **This is the answer to "how did you avoid exhausting connections?"** — the pool is
sized *per worker*, deliberately, and the comment in the config shows the multiplication.

### 9.3 Two session factories

Both `@lru_cache`d `async_sessionmaker`s with the same two options (`database.py:37-54`):
```python
async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False, autoflush=False)
```
- **`expire_on_commit=False`** — attributes stay usable after `commit()` without a re-SELECT. Task
  code reads fields after committing; without this it would trigger lazy loads on a dead session.
- **`autoflush=False`** — pending changes are *not* flushed before a query, so flush points are
  explicit rather than implicit.

### 9.4 The test seam

`database.py:57-79` keeps mutable module globals `_async_session_maker` /
`_replica_session_maker` plus `_ensure_session_makers()`, commented *"Mutable refs so tests can
patch these directly"*. `conftest.py:140-148` assigns them a `NullPool` factory and clears all four
`lru_cache`d getters.

That indirection exists because of a real trap, called out in `tasks.get_session()`'s docstring:
`async_session()` is a **function that returns a session** (calling it is correct), while
`async_session_maker` is exposed separately as the **getter**. `tasks.py` calls the function; calling
the maker directly would hand you a sessionmaker.

### 9.5 The two FastAPI dependencies

```python
async def get_db():           # database.py:82-88           — primary
async def get_db_replica():   # database.py:91-98           — read replica
```
Both are async generators: `_ensure_session_makers()`, `async with ... as session: yield`, and an
explicit `await session.close()` in `finally`. **Neither commits or rolls back** — transaction
boundaries belong to the route or service.

Read endpoints are meant to depend on `get_db_replica` (docstring: *"Read-only replica session — use
for list/get endpoints that don't modify data"*). When `database_replica_url` is empty it silently
serves the primary, so the architecture is already correct with zero extra infrastructure.

---

## 10. Gaps to admit before you're asked

1. **Five CHECK constraints are in the models but not in the schema** (§8.2). Verify it yourself
   before claiming it.
2. **`markets.winning_outcome_id` and `proposed_outcome_id` are not foreign keys** — plain `UUID`
   columns with no referential integrity on the two most safety-critical fields in the system.
   A bad write is not caught by the database; `settle_market` catches it by re-reading and
   refusing on mismatch (`tasks.py:766-775`).
3. **No database enums** — all 15+ enum-like columns are unconstrained strings (§1.3).
4. **Every relationship is lazy** — N+1 is a live risk, which is why list endpoints batch.
5. **No index on `lp_shares.pool_id`/`user_id`, `market_faqs.market_id`, or `comments.depth`**;
   `ix_positions_user_id` is redundant.
6. **`created_by` on `markets` is not a FK** either.
7. **Depth limits and dedup for comments/flags/referrals are application-only** (§5).
8. **`metadata` is a JSON string in a TEXT column** (`AuthAuditEvent`) while `extra_data` is proper
   JSONB — two representations of the same idea.
9. **Five tables are missing indexes on their only FK**, which is the classic N+1 setup.

---

## 11. Where to look in the code

| Thing | File:line |
|---|---|
| `Base`, `TimestampMixin`, `UUIDMixin` | `app/models/base.py:9-21` |
| `Market` status constants + groupings | `app/models/market.py:24-42` |
| FTS index + its explanatory comment | `app/models/market.py:104-108` |
| `EscrowShortfallError` | `app/models/liquidity.py:10-22` |
| `credit_collateral` / `debit_collateral` / `can_cover` | `app/models/liquidity.py:61` / `:73` / `:99` |
| Order CHECKs + 7 indexes | `app/models/order.py:19-31` |
| Idempotency partial unique indexes | `app/models/wallet.py:45-56` |
| Wallet CHECKs (missing in DB) | `app/models/wallet.py:20-24` |
| `AuthAuditEvent` `SET NULL` + `metadata_` rename | `app/models/audit.py:16,29` |
| Treasury singleton triple constraint | `app/models/treasury.py:18-22` |
| Alert partial indexes | `app/models/alert.py:19-23` |
| Comment self-reference | `app/models/comment.py:27-38` |
| Engines, pool settings | `app/database.py:9-34` |
| Session factories + test seam | `app/database.py:37-79` |
| `get_db` / `get_db_replica` | `app/database.py:82-98` |
| Missing CHECKs, verified absent | `migrations/versions/763d787eabf1_initial_schema.py:74-100, 177-189` |
| Leftover `server_default` | `migrations/versions/0ccfc38683a8_...py:25` |
| "migrations own the schema" | `app/app.py:189-194` |
| Test DB rebuilt from migrations | `tests/conftest.py:80-135` |

**Tests that pin this behaviour:** `test_ledger.py` (escrow in/out, settlement payout table, the
refusal to pay a winner partially), `test_escrow_audit.py` (every invariant in `escrow_audit.py`,
including "a healthy pool reports no violations"), `test_orders.py` (price/amount boundaries),
`test_admin.py` (treasury singleton behaviour).