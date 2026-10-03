# Viva Question Bank — Polymarket Clone

> **Every question below has a full, spoken-word answer.** You do not need to be a programmer to
> deliver any of these: read the **Answer** paragraph out loud and you have said the right thing.
> The `→` at the end points to the doc/file with the deep version, if the examiner pushes.
>
> Companion docs: `docs/concepts.md` (plain English, start here) · `docs/architecture.md` ·
> `docs/trading-engine.md` · `docs/auth-and-security.md` · `docs/docker-concurrency-realtime.md`.

---

## How to use this list

1. Cover the answer with your hand. Read the question. Say your answer out loud in one breath.
2. Uncover it. If you missed a fact, that fact is the one to remember.
3. Questions marked **★** are the ones most likely to be asked first — learn those cold.
4. If you want the maths or the code, follow the `→` pointer at the end of an answer.

---

## 60-second glossary (read this first)

| Word | What it means here, in plain English |
|---|---|
| **Market** | One question being traded, e.g. "Will it rain on Tuesday?", with a YES side and a NO side. |
| **Share** | One claim on the answer. A YES share pays $1 if YES is true, $0 if not. Price = what people think the chance is. |
| **Order book** | The notice board of everyone saying "I'll buy at $0.60" / "I'll sell at $0.65". Trades happen when two posts agree. |
| **AMM / the jar / the pool** | A pot of YES and NO shares run by a formula, so you can trade instantly even when nobody else is posting. |
| **Liquidity** | How much money/shares are in the jar. Deep liquidity = big trades barely move the price. |
| **Price impact** | Your own trade moving the price against you. Big order → you pay the worse price you created. |
| **Slippage** | Difference between the price you hoped for and the price you actually got. We let you cap it. |
| **Fee** | 2% taken by the pool on AMM trades + 1% recorded as protocol fee. Nothing is taken when you're paid out. |
| **Transaction / commit** | A bundle of database changes that all happen together or none of them do. |
| **Lock (`FOR UPDATE`)** | A "this row is mine until I finish" marker the database enforces. Others queue behind it. |
| **Deadlock** | Two jobs each waiting for a lock the other holds, forever. Prevented by always locking in the same order. |
| **Idempotency** | Doing the same request twice has the effect of doing it once. |
| **Worker / Celery / beat** | Separate background program that does scheduled jobs (settle markets, expire orders, send email). |
| **Pub/sub, Redis** | A broadcast system: one process announces "price is now 0.62", every server relays it to its browsers. |
| **WebSocket** | A permanent line between browser and server so updates can be pushed without asking. |
| **Settlement** | The end of the market: winners get $1 per share, losers get $0. |

---

## A. Architecture & design decisions

**★ A1. Give me the shape of the system in 60 seconds.**
**Answer:** There are two programs. The **back end** is FastAPI (Python) with a Postgres database,
Redis for caching/broadcasting, and Celery for background jobs — all containerised with Docker. The
**front end** is Next.js (React) talking to it over a JSON API and a WebSocket for live prices. Both
have nginx in front, and `docker compose` starts the whole thing with one command.
→ `docs/architecture.md`, `docs/docker-concurrency-realtime.md` §A.

**★ A2. Why FastAPI and not Django/Nest?**
**Answer:** Because everything is *async*: thousands of open WebSockets, Redis calls and database
round-trips have to share one thread per worker without blocking each other. FastAPI is built for
that, and it also gives us free request validation and automatic API documentation from the same
schema definitions.
→ `backend/app/app.py`.

**A3. Why async ORM instead of synchronous SQLAlchemy?**
**Answer:** The slow part of every request is waiting — for the database, for a lock, for Redis.
With async, one worker can start request A, and while A waits it starts request B. With synchronous
code, waiting means a whole thread per request, and threads are expensive.
→ `backend/app/database.py`.

**A4. Why is `decimal.Decimal` used everywhere and not `float`?**
**Answer:** Because computers can't represent most decimals exactly — 0.1 + 0.2 is 0.30000000000000004 in
floating point. Money must never drift, so we use exact decimal arithmetic end to end, and the
database columns are fixed-precision decimals. Floats only appear at the last moment when we send
JSON to the browser.
→ `docs/architecture.md`.

**A5. Why cookie-based auth instead of a token in localStorage?**
**Answer:** An HttpOnly cookie can't be read by JavaScript, so if an attacker injects a script into
the page, they still can't steal your login token. Cookies are also sent automatically and marked
`SameSite=Lax`, which blocks most cross-site request forgery for free. The cost is that we must
configure CORS carefully to allow our own origins with credentials.
→ `docs/auth-and-security.md` §1, §9.

**A6. Why a monorepo?**
**Answer:** The front end and back end are started, versioned and deployed together, so keeping them
in one repository means one `docker compose up`, shared type definitions, and a change that touches
both sides lands as a single commit. Turborepo caches builds so only what changed gets rebuilt.
→ `frontend/README.md`.

**A7. What does each Redis use-case look like? Name five.**
**Answer:** Five distinct jobs: (1) rate-limit counters, (2) one-time codes and session scratch data,
(3) the pub/sub broadcast that fans price updates out to every server, (4) "have I already seen this
payment?" locks, and (5) the "dirty markets" set that tells the background job which markets to
re-check. Redis is never the source of truth for money — Postgres is.
→ `docs/architecture.md` (Redis usage).

**A8. Where is the single most important invariant enforced?**
**Answer:** In the database, not in Python. Two things: locks taken in a fixed order, and hard
constraints such as unique indexes that make duplicate rows impossible even if the code had a bug.
Application code is a convenience; the database is the guarantee — it can't be skipped by a race.
→ `docs/docker-concurrency-realtime.md` §B5.

**A9. What happens end-to-end when someone places a market buy?**
**Answer:** Six steps: validate the request; lock the market, the pool and your wallet; check this
isn't a duplicate request; check you can afford it; fill what the order book can fill, then let the
jar take the rest (charging the price your own order pushed it to); then write the order, your
shares, the trade records and your new balance in **one** database transaction, and finally broadcast
the new price to every connected browser.
→ `docs/trading-engine.md` §2.

**A10. Why is there both an order book and an AMM?**
**Answer:** They cover each other's weakness. The book gives you a *better* price because you're
trading directly with another person, but only if someone is there. The jar always has a price, so
your trade fills instantly even at 3am — at the cost of a fee and price impact. We route to the book
first (free, better price) and the jar second.
→ `docs/trading-engine.md` §2.

**A11. Why is the status machine `draft → pending_review → active → closed → resolving → resolved`?**
**Answer:** Each step exists for a reason: review is moderation, `closed` stops trading at the
deadline, and the separate `resolving → resolved` steps mean a background job that runs twice can
never pay people twice — the second run sees the status already moved and stops.
→ `backend/app/models/market.py`.

**A12. What is "system design" showing up as in this codebase?**
**Answer:** Five concrete mechanisms: broadcasting through Redis so all 8 workers can reach every
browser, a dirty-set so we don't scan the whole database every 30 seconds, `SKIP LOCKED` so jobs
claim work without waiting on each other, idempotency keys so retries are safe, and rate limiting as
middleware so it protects every route automatically.
→ `docs/docker-concurrency-realtime.md`.

**A13. Why not just use WebSockets for everything, including reads?**
**Answer:** Because normal reads can be cached, retried and re-run — sockets are for *pushing*
changes you didn't ask for. Every socket also costs a permanent connection, so we cap them (5 per
user, 50 per IP) rather than let a page open hundreds.
→ `backend/app/websocket/manager.py`.

**A14. Where does the front end get its data?**
**Answer:** From two places: normal HTTP requests through a wrapper that automatically refreshes the
login on a 401 and avoids duplicate GETs, and two WebSocket hooks — one shared per-market connection
and one per-user connection — that patch React Query's cache in place, so the page updates without
refetching. (The backend exposes a third endpoint, `/ws/trades`, for a global feed.)
→ `frontend/apps/web/hooks/`, `frontend/apps/web/lib/api/client.ts`.

**★ A15. If I killed Redis right now, what breaks? What still works?**
**Answer:** Trading still works — money and shares live in Postgres, and locks and constraints don't
need Redis. What stops: live price pushes, one-time codes, and (in production) rate limiting, which
fails *closed* — meaning we refuse requests rather than accept them unprotected. The session check
also survives because the session row is in the database.
→ `docs/auth-and-security.md` §11.

---

## B. Backend / FastAPI

**B1. How are dependencies injected?**
**Answer:** FastAPI's `Depends()`: each route declares what it needs — a database session, the
logged-in user — and the framework builds it. Handlers never read cookies or open connections
themselves, which means auth and logging can't be forgotten on a new route.
→ `backend/app/deps.py`.

**B2. What's the difference between `get_current_user` and `get_optional_user`?**
**Answer:** The first one refuses the request with a 401 if you're not properly logged in; the
second returns "nobody" and carries on, so public pages like the market list work for logged-out
visitors. Same token check, different consequence.
→ `backend/app/deps.py`.

**B3. Where is the middleware stack ordered?**
**Answer:** Security headers first, then request logging, then rate limiting, the origin check and
the body-size cap — those are deliberately *outermost*, so a request that's too big or from a banned
origin is rejected before any handler ever runs.
→ `backend/app/app.py`.

**B4. Why is the body-size cap checked on `Content-Length` before reading?**
**Answer:** Because Pydantic validation only happens after the whole request is in memory. If we
waited for validation, someone could send a 10GB body and exhaust the process first. So we look at
the declared size header and reject anything over 256 KiB immediately.
→ `backend/app/api/middleware.py`.

**B5. How are errors shaped?**
**Answer:** One shape everywhere: `{success: false, error, error_code, details?}`. The front end has
a single code path for failures instead of special-casing each endpoint, and each error type
(insufficient balance, slippage exceeded…) has its own code the UI can translate into a message.
→ `backend/app/api/exceptions.py`.

**B6. What does `success_response()` do?**
**Answer:** It wraps every successful payload in `{success: true, data, message}` so the client
never has to guess whether a response is a raw object or a result — consistency is the whole point.
→ `backend/app/api/responses.py`.

**B7. How are schemas validated?**
**Answer:** Pydantic v2 models with constrained types — money fields with a max of 2 decimals, a
slug pattern of lowercase letters and dashes, order types matched by a regular expression, and
min/max bounds. Anything invalid is rejected with a 422 before a single database query runs.
→ `backend/app/schemas/`.

**B8. Why `async` on every route?**
**Answer:** Because the database driver is async, and async means one shared event loop per worker.
If one route blocked on, say, a slow query, it would freeze every other request *and every open
WebSocket* on that worker — so no handler is allowed to block.
→ `backend/app/app.py`.

**B9. What does `await db.flush()` vs `await db.commit()` mean here?**
**Answer:** `flush` sends the SQL and keeps the transaction open — you need it to get generated IDs
and to keep holding row locks. `commit` finishes the transaction and releases the locks. We keep
"don't re-fetch after commit" on, so objects stay usable without extra queries.
→ `backend/app/database.py`.

**B10. How are background tasks triggered — Celery or `BackgroundTasks`?**
**Answer:** Celery for anything that can fail and needs retrying, or that runs on a schedule —
resolving markets, expiring orders, sending email. Those jobs use a Redis "only one of me" lock plus
a status change, so a retry after a crash can't pay people twice. FastAPI's `BackgroundTasks` would
die with the request.
→ `backend/app/workers/tasks.py`.

**B11. Why `.with_for_update()` on some queries and not others?**
**Answer:** Only on rows we're about to change and must not lose — locking them serialises
concurrent writers. Read-only queries never take it, because database reads under MVCC never block
anyone, and read-heavy routes go to a replica.
→ `docs/docker-concurrency-realtime.md` §B.

**B12. What is `redis_cb.call(...)`?**
**Answer:** A thin wrapper around every Redis call that adds a timeout, error handling and metrics —
so a hung Redis degrades one feature instead of hanging the whole request.
→ `backend/app/services/redis_client.py`.

**B13. How does the API version?**
**Answer:** Everything lives under `/api/v1/...`, with routers grouped by domain (markets, orders,
wallet, auth, admin, split-merge). A v2 can be added alongside without breaking existing clients.
→ `backend/app/app.py`.

**B14. What's the startup fail-fast check?**
**Answer:** The service refuses to boot if a secret is still set to its placeholder value
(`change-me-in-production`). Better to crash visibly at startup than to run in production signing
tokens with a publicly known key.
→ `backend/app/config.py`.

**B15. How would you add a new endpoint safely?**
**Answer:** Five steps: define the request/response schema, add a router that depends on the session
and the logged-in user, put the write inside a service function with the transaction and the lock
order, publish any resulting event, and add a test. The schema gives you documentation for free.
→ `docs/architecture.md`.

---

## C. Database

**★ C1. What are the tables?**
**Answer:** In four groups: **people** (`users`, `sessions`, `refresh_tokens`, `auth_audit_events`),
**trading** (`markets`, `outcomes`, `orders`, `trades`, `positions`, `price_history`), **money**
(`wallets`, `transactions`, `liquidity_pools`, `lp_shares`) and **social** (`comments`,
`notifications`, `referrals`, `alerts`).
→ `backend/app/models/`.

**★ C2. Why is `Order.remaining_amount` allowed to be USDC *or* shares?**
**Answer:** Because it mirrors what the order was placed in: a buy is placed in dollars, so its
remainder is dollars of unspent budget; a sell is placed in shares, so its remainder is shares.
Every comparison converts first — that conversion is exactly where a bug once compared dollars
against shares.
→ `docs/trading-engine.md` §1.

**★ C3. Which indexes actually matter?**
**Answer:** The book sweep needs `(market_id, outcome_id, status, price)` so matching an order is a
seek, not a table scan. Positions have a unique key on `(user, market, outcome)` so two orders can
never create two rows for you. Transactions have partial unique indexes on deposit and withdrawal
references so a payment webhook can't be applied twice. And `refresh_tokens(token_hash)` is unique
for the same reason.
→ `backend/app/models/`.

**C4. How is `Decimal` persisted?**
**Answer:** As fixed-precision `Numeric(p,s)` columns that come back as Python `Decimal`. No float
ever touches the database — that's what keeps balances exact.
→ `docs/architecture.md`.

**C5. How are positions created without a read-then-insert race?**
**Answer:** With `INSERT … ON CONFLICT … DO UPDATE`: one statement that either inserts a new position
or updates the existing one. Two requests doing this at the same time are resolved by the database,
not by our code — the classic "check then insert" race simply doesn't exist.
→ `backend/app/services/order_service.py`.

**C6. What does `settled_at` protect?**
**Answer:** It's the "have I already been paid?" flag. Both the background settlement job and the
manual claim button read it with a row lock and only proceed if it's still empty, then set it. So a
retried job or a double-click on "claim winnings" can't pay twice.
→ `docs/trading-engine.md` §5.

**C7. What are migrations? Why not `create_all`?**
**Answer:** Alembic migrations are a versioned list of schema changes, so test and production
databases are built from the exact same history. `create_all` only creates tables and misses
partial unique indexes, check constraints and database-default UUIDs — and it never *changes* an
existing table. Our tests rebuild the schema from migrations every run.
→ `backend/migrations/versions/`.

**C8. Explain the money columns: `balance` vs `locked_balance`.**
**Answer:** `balance` is everything you have; `locked_balance` is the part reserved for orders still
waiting on the book. What you can actually spend is `balance − locked_balance`, and every check uses
that difference — so a $100 resting buy can't also be spent on a $100 market buy.
→ `backend/app/models/wallet.py`.

**C9. What is `average_price` and how is it updated?**
**Answer:** It's your cost per share, blended across all your buys: new average = (old average ×
shares held + what you paid) ÷ new total. It's what makes profit/loss correct after buying at three
different prices. `realized_pnl` separately accumulates profit from trades you've already closed.
→ `backend/app/services/order_service.py`.

**C10. Why keep zero-share position rows after a full sell/merge?**
**Answer:** So your history and realised profit survive — deleting the row would erase the record.
The API just filters to `shares_held > 0` when showing what you currently hold.
→ `backend/app/models/position.py`.

**C11. How do you avoid a lost update on `wallet.balance`?**
**Answer:** You read the wallet row *with a lock* in the same transaction as the change. The
database then makes a second request that wants to update the same wallet wait until the first one
commits, so the second reads the updated value instead of overwriting it.
→ `docs/docker-concurrency-realtime.md` §B2.

**C12. What is `pool.protocol_fees`?**
**Answer:** A running total of the platform's 1% fee for that market's pool. It's topped up on every
AMM trade, on every book trade (the fee comes out of the seller's proceeds) and on every split/merge,
then swept to the treasury account at settlement.
→ `docs/trading-engine.md` §2.

**C13. Why does `price_history` exist if Redis has prices?**
**Answer:** Because charts need ordered history and Redis only holds the latest value with a short
life. A background task writes a snapshot per minute with de-duplication, so a retry can't create
double points.
→ `backend/app/workers/tasks.py`.

**C14. What happens if two servers both write a market price?**
**Answer:** They don't. The price is always recomputed from the database row inside the transaction
that moved the shares, so there's exactly one writer per market at a time. Redis only carries the
*announcement* afterwards — it never decides the price.
→ `docs/trading-engine.md` §2.

**C15. How would you partition this if volume grew 100×?**
**Answer:** Split the append-only tables (`trades`, `price_history`) by month, shard the hot tables
by market, read from replicas for the public feed, and replace Redis pub/sub with Kafka/NATS once
you're cross-region — pub/sub assumes servers are close together.
→ `docs/architecture.md`.

**C16. What's a query you'd optimise?**
**Answer:** The resting-order sweep — it looks up orders by market, outcome, status and price in
that order, and only for markets marked dirty, and it claims rows with `SKIP LOCKED` so parallel
workers never queue behind each other.
→ `backend/app/services/matching_engine.py`.

**C17. Where could you get a deadlock?**
**Answer:** Only by taking locks in different orders — one job locking the wallet then the pool,
another locking the pool then the wallet. We prevent it by a global order (market → pool → wallet →
position → order) and, inside a match between two users, by sorting the two user IDs before locking
either wallet.
→ `docs/docker-concurrency-realtime.md` §B3.

**C18. Why `SKIP LOCKED` on makers but plain `FOR UPDATE` on the taker's wallet?**
**Answer:** The taker *must* have its wallet locked because its money is moving — there's no
alternative. The makers are optional: if someone else is already working on that resting order,
we simply take the next one instead of waiting.
→ `backend/app/services/matching_engine.py`.

**C19. What is `TRUNCATE … CASCADE` used for?**
**Answer:** Test isolation. Every test starts from an empty database by truncating all tables, so no
test can be affected by what another test left behind.
→ `backend/tests/conftest.py`.

**C20. How do you prove the schema in tests matches production?**
**Answer:** Because the test database is built by running the same Alembic migrations production
uses, from empty to head, on every run. If a migration is broken or missing, the tests fail — they
can't quietly run against an older schema.
→ `backend/tests/conftest.py`.

---

## D. Concurrency — "two users buy the same market at the same instant"

**★ D1. Walk me through the race.**
**Answer:** Both requests arrive and both want to change the same market's pool. The first gets
there and takes a row lock; the second **blocks inside the database** until the first commits. When
it unblocks it reads the *new* pool state and the *new* balance, so it sees the effect of the first
trade instead of overwriting it. No application mutex, no sleep-and-retry, no lost update — the
database does the serialising.
→ `docs/docker-concurrency-realtime.md` §B1–B2.

**★ D2. What exactly does `FOR UPDATE` do?**
**Answer:** It marks the row as locked by this transaction until the transaction ends. Any other
transaction trying to update or lock the same row waits. It's released automatically on commit or
rollback — it is not an application lock you can forget to release.
→ PostgreSQL docs, `SELECT … FOR UPDATE`.

**★ D3. Why `SKIP LOCKED` in the matching engine?**
**Answer:** When matching an order we walk down the list of resting orders. If another worker is
already processing one of them, we don't want to wait — waiting on a queue of locks is how deadlocks
and stalls happen. `SKIP LOCKED` says "take the next one you can have", so the taker never queues
behind another taker.
→ `backend/app/services/matching_engine.py`.

**★ D4. How do you stop someone selling shares they don't own?**
**Answer:** Two guards plus a hard constraint: we check your holdings up front, and — crucially — we
re-read your position **under a lock** immediately before deducting. If you hold less than the match
needs (because a parallel fill consumed them), that match is skipped and logged rather than allowed
to create shares from nothing. A database CHECK constraint is the last line of defence.
→ `backend/app/services/matching_engine.py` (the "seller guard").

**★ D5. What stops overspending?**
**Answer:** `balance − locked_balance ≥ cost`, evaluated **while both wallets are locked**, raising
`InsufficientBalanceError`. Because the two wallets in a match are locked in a sorted order by user
ID, two simultaneous matches can never deadlock against each other.
→ `docs/docker-concurrency-realtime.md` §B3.

**★ D6. Deadlock: how would you get one, and how is it prevented?**
**Answer:** Job A locks wallet 1 then wants wallet 2; job B locks wallet 2 then wants wallet 1 —
both wait forever. We prevent it twice over: a global lock order (market → pool → wallet →
position → order), and inside every match, sorting the two user IDs so both jobs lock the wallets in
the same sequence. Postgres would detect a deadlock and abort one transaction anyway, as a backstop.
→ `docs/docker-concurrency-realtime.md` §B3.

**D7. What's the difference between `FOR UPDATE`, `FOR UPDATE NOWAIT`, `FOR UPDATE SKIP LOCKED`?**
**Answer:** Plain `FOR UPDATE` waits for the lock. `NOWAIT` gives up immediately with an error.
`SKIP LOCKED` silently moves to a different row. Same clause, three behaviours: correctness
(waiting is required), fast failure, or availability (never wait at all).
→ `backend/app/services/matching_engine.py`.

**D8. Where is serialisation actually *needed* vs merely convenient?**
**Answer:** Needed wherever money or share counts change: wallet balances, position holdings, pool
reserves, market status. Convenient-but-optional on the book sweep, where `SKIP LOCKED` is good
enough because the rows are interchangeable.
→ `docs/docker-concurrency-realtime.md` §B.

**D9. What if two Celery workers settle the same market?**
**Answer:** Three independent gates stop them: a Redis "only one of me" lock, flipping the status to
`resolving` before any write (the second worker sees it and bails), and a per-position
`settled_at IS NULL` check under a row lock. Any one of the three is enough to prevent a double pay.
→ `docs/trading-engine.md` §5.

**D10. What's the difference between atomicity and isolation here?**
**Answer:** Atomicity means all-or-nothing: the wallet, position, order and trade rows commit
together or none of them do. Isolation means nobody sees your half-finished work: row locks plus
MVCC ensure a concurrent transaction reads either the state before you started or after you
committed, never in between.
→ `docs/docker-concurrency-realtime.md` §B.

**D11. Read the isolation level: what could still go wrong?**
**Answer:** We run at the default READ COMMITTED, which on its own would let two transactions read
stale rows and both act on them. That's fine because every contested row is explicitly locked — the
lock, not the isolation level, is what serialises them. Without the locks you'd get non-repeatable
reads and phantom rows on the book sweep.
→ `backend/app/database.py`.

**D12. How do you test concurrency?**
**Answer:** `test_concurrency.py` fires parallel order placements at the same market and then asserts
the *invariants*: total wallet balances equal the sum of reported effects, and no balance ever goes
negative. Asserting invariants rather than exact messages is what catches this class of bug.
→ `backend/tests/test_concurrency.py`.

**D13. What happens if the process crashes mid-transaction?**
**Answer:** Postgres rolls the transaction back automatically, so there's no half-applied trade —
no shares moved without money moving. The client retries with the same idempotency key, and because
the key is checked inside the lock, the retry returns the original result instead of duplicating it.
→ `docs/docker-concurrency-realtime.md` §C.

**D14. Why not just use Redis `SETNX` for all of this?**
**Answer:** Because Redis and Postgres don't share a transaction: you could crash between writing to
each and end up in a state neither system agrees on. Locks must live where the data lives, in the
same transaction as the change. We do use `SET NX` in Redis — but only for things that are safe to
lose, like a payment webhook dedupe.
→ `docs/docker-concurrency-realtime.md` §C.

**D15. Is there any optimistic concurrency in here?**
**Answer:** Yes, in two places: idempotency keys (if we've seen this request, return the earlier
result) and the `ON CONFLICT` upserts (let the database merge the two versions atomically).
Everything else is pessimistic — lock first, then work.
→ `docs/docker-concurrency-realtime.md` §C.

**D16. Two users cancel the same order — what happens?**
**Answer:** Both take a lock on the same order row; the first sets it to `cancelled`, the second
then reads `status != pending` and returns "already cancelled" instead of releasing the locked
funds a second time. The lock makes the check-and-change atomic.
→ `backend/app/api/orders.py`.

**D17. What is the cost of all these locks?**
**Answer:** Throughput on a single market: trades in the same market serialise behind each other.
That's an acceptable trade because the lock is held for milliseconds inside one transaction, and the
contention unit — one market — is narrow; different markets never wait on each other.
→ `docs/docker-concurrency-realtime.md` §B.

**D18. How would you scale this beyond one Postgres?**
**Answer:** Shard by market, since each market is an independent lock domain; move the order book
into an in-memory matching service with a write-ahead log for recovery; keep the money ledger on a
single transactional database. Settlement and balances must stay strongly consistent.
→ `docs/architecture.md`.

**D19. What would you change first?**
**Answer:** Batch wallet updates — one `UPDATE … CASE` statement per transaction instead of N row
locks — and turn background work into a claim queue with `SKIP LOCKED` so workers never block each
other. Both are small changes with the biggest contention payoff.
→ `docs/docker-concurrency-realtime.md` §B.

**D20. Did you ever see a real deadlock or race in testing?**
**Answer:** Yes — and each one is marked in the code with a comment tag (`C1`…`C9`, "seller guard",
"stale book"), each with a regression test. The two most instructive were a wallet deadlock fixed by
sorting user IDs, and a stale-book race where a seller's shares were consumed twice, fixed by the
re-read-under-lock guard.
→ `backend/tests/test_concurrency.py`.

---

## E. Idempotency / "how do you prevent duplication?"

**★ E1. Six ways duplication is prevented.**
**Answer:** (1) Orders carry a `client_order_id` that's checked *inside* the lock and enforced by a
unique index — a retried POST returns the original order. (2) Quotes are user-bound, short-lived and
single-use. (3) Stripe deposits verify the signature, then take a Redis lock and a unique
`deposit_ref` constraint. (4) Withdrawals use a client key plus a unique reference. (5) Settlement
proceeds only where `settled_at IS NULL`. (6) Positions use `INSERT … ON CONFLICT` so two inserts
become one update. Rate limits, one-time codes and market resolution all use atomic Redis `SET NX`.
→ `docs/docker-concurrency-realtime.md` §C9 (table).

**★ E2. Why check `client_order_id` *inside* the lock?**
**Answer:** If you check before locking, two identical requests can both pass the check before
either inserts — and you've duplicated. Inside the lock the two requests are forced into a queue, so
the second one sees the first one's row and returns its result.
→ `backend/app/services/order_service.py`.

**★ E3. What does the front end do to stop double submits?**
**Answer:** The button is disabled as soon as it's pressed, GET requests are de-duplicated so the
same URL isn't fetched twice in one tick, and the token refresh is "single-flight" — if four
requests hit a 401 at once, only one refresh runs and the rest wait for it.
→ `frontend/apps/web/lib/api/client.ts`.

**E4. What's the difference between idempotency and deduplication?**
**Answer:** Idempotency means "doing it twice has the effect of doing it once" — correct even if the
caller retries blindly. Deduplication means "don't fire it twice in the first place" — a UI
convenience. Idempotency is the guarantee; deduplication is an optimisation.
→ `docs/docker-concurrency-realtime.md` §C.

**E5. How do you make retries safe across services?**
**Answer:** Give every externally visible effect a key — order id, webhook event id, withdrawal
reference — and enforce that key with a *database constraint*, not just application logic. Then a
retry from any service hits the constraint and is rejected or returned as the original result.
→ `docs/docker-concurrency-realtime.md` §C9.

**E6. What if the *response* is lost after a successful commit?**
**Answer:** The client retries with the same key; the server finds the row created by the first
attempt and replays that response. That's exactly why the duplicate check has to be inside the lock
— outside it, the retry could beat the insert.
→ `backend/app/services/order_service.py`.

**E7. How is settlement idempotent for a Celery retry?**
**Answer:** Three gates: the status is flipped to `resolving` before any writes, a Redis `SET NX`
lock names one worker as the owner, and each position is settled only while `settled_at IS NULL`
under a row lock. A retry after a crash hits the status or the flag and stops.
→ `docs/trading-engine.md` §5.

**E8. Why not just disable retries?**
**Answer:** Because retries are how you survive networks — a dropped response is normal. The right
fix is to make the operation keyed so retrying is harmless, not to make the client never try again.
→ `docs/docker-concurrency-realtime.md` §C.

**E9. Are OTPs idempotent?**
**Answer:** They're single-use: the code is deleted the moment it verifies, and asking for a new code
invalidates the previous one. Sending and verifying are both rate-limited with atomic Lua scripts, so
you can't re-roll the target or hammer the check.
→ `backend/app/services/otp_service.py`.

**E10. Is a websocket publish idempotent?**
**Answer:** It's deliberately *at-least-once* — pub/sub has no acknowledgement. Clients treat events
as "the price **is now** 0.62" rather than "+0.01", so receiving the same message twice is harmless.
State-carrying payloads are what make no-ack delivery safe.
→ `docs/docker-concurrency-realtime.md` §D.

---

## F. Realtime

**★ F1. How does a price update get to a browser?**
**Answer:** Six hops: a trade commits in one worker → that worker publishes `price_update` to the
Redis channel for that market → **every** server instance's listener task receives it → each looks up
which of *its own* sockets are subscribed to that market → it sends the message down those sockets →
the browser patches React Query and the number animates.
→ `docs/docker-concurrency-realtime.md` §D2.

**★ F2. Why pub/sub instead of pushing straight from the request handler?**
**Answer:** Because there are 8 worker processes and each one has its own sockets — a handler can only
reach the sockets connected to *it*. If Alice's browser is connected to worker 3 and the trade
happened on worker 7, a direct push would never reach her. Redis is the only component that can talk
to all 8.
→ `docs/docker-concurrency-realtime.md` §D2.

**★ F3. How does one server know which sockets are its own?**
**Answer:** An in-memory `ConnectionManager` keeps two maps: which markets each socket wants, and
which sockets want each market. The Redis listener is the bridge — message in, local lookup, send.
Nothing about subscriptions needs to be shared between servers.
→ `backend/app/websocket/manager.py`.

**★ F4. Why does `sync-amm-prices` only publish when |Δ| > 0.0001?**
**Answer:** It's a 60-second safety-net job that re-announces prices. Without a threshold it would
push identical frames to every browser forever, wasting bandwidth and re-rendering charts for no
change. The tiny threshold is hysteresis: announce real moves, stay quiet otherwise.
→ `backend/app/workers/tasks.py`.

**★ F5. What is the dirty-market set for?**
**Answer:** Every time a market's price moves, its id is added to a Redis set. The background job
drains that set instead of scanning every market in the database. If nothing traded, the set is
empty and the job does zero queries.
→ `backend/app/workers/tasks.py`.

**F6. Name the channels.**
**Answer:** `market:{id}` carries prices, order books and trades for one market; `global_trades` is
the cross-market trade ticker; `user:{id}` carries your notifications. Separately, each server keeps
its own subscription registry in memory.
→ `backend/app/websocket/`.

**F7. What stops one client flooding the server?**
**Answer:** Hard caps at every layer: 64 KB maximum message, 50 subscriptions per socket, 50
connections per IP, 5 per user, plus a ping/pong heartbeat that evicts dead sockets. Each limit has a
comment explaining the number it chose.
→ `backend/app/websocket/manager.py`.

**F8. How is auth done on the upgrade?**
**Answer:** The WebSocket handshake looks for the login cookie (it only accepts `?token=` if
`WS_ALLOW_QUERY_TOKEN=true` is set, which is **off** by default — a token in a URL ends up in
proxy logs, history and `Referer`), then runs the *same* check as the REST API: valid signature, correct token type, not blacklisted,
user still active, and bound to a live session. It fails **closed** — no valid session, no socket.
→ `docs/auth-and-security.md` §10.

**F9. Why does the front end reconnect with backoff?**
**Answer:** Server restarts drop every socket at once. Reconnecting instantly would create a
thundering herd, so the delay grows exponentially with random jitter, and React Query refetches REST
state on reconnect so nothing on screen is stale.
→ `frontend/apps/web/hooks/use-market-socket.tsx`.

**F10. What happens to a message published while a client is disconnected?**
**Answer:** It's lost — a socket is a stream, not a queue, and we don't buffer for absent clients.
That's fine because the client re-fetches the current state over REST on reconnect; the socket only
carries changes you're already up to date for.
→ `docs/docker-concurrency-realtime.md` §D.

**F11. Poll vs SSE vs WebSocket — why WS?**
**Answer:** We need both directions — the client subscribes and unsubscribes as you move between
pages — and we need many markets multiplexed over one connection. Polling wastes requests on empty
responses; SSE is one-way and still needs a separate request to subscribe.
→ `docs/docker-concurrency-realtime.md` §D.

**F12. How would you test the realtime path?**
**Answer:** `tests/test_websocket.py` uses FastAPI's test client to connect, ping, subscribe,
unsubscribe, and — importantly — assert that an unauthenticated socket is rejected and that the
connection caps are enforced. Those are the tests that would catch a broken auth check.
→ `backend/tests/test_websocket.py`.

**F13. What are the scale constants and why those numbers?**
**Answer:** 50 connections per IP (many real users share a NAT address, so we can't be too strict),
5 per user (a person doesn't need more), 50 subscriptions per socket (a page needs a handful of
markets). Each is a deliberate denial-of-service bound with a comment justifying it.
→ `backend/app/websocket/manager.py`.

**F14. How does this survive a deploy?**
**Answer:** Gunicorn's `graceful_timeout` is 30s and `timeout` is 120s — longer than the WebSocket
keepalive — so live connections aren't killed mid-frame while workers restart. Clients then
reconnect with backoff and re-sync from REST, so users see at most a brief pause.
→ `backend/gunicorn.conf.py`.

**F15. Why not push directly from Postgres (LISTEN/NOTIFY or logical replication)?**
**Answer:** `LISTEN/NOTIFY` doesn't scale to many channels and many clients, and it ties the schema
to the transport. Redis pub/sub is already in the stack for rate limiting and caching, and it gives
us the same fan-out across processes without extra infrastructure.
→ `docs/docker-concurrency-realtime.md` §D.

**F16. Where is backpressure handled?**
**Answer:** If a socket can't keep up (a send fails), we drop that connection rather than buffer
frames without limit — the client reconnects and refetches. Globally, the connection caps bound the
worst case. There is no unbounded per-socket queue anywhere.
→ `backend/app/websocket/manager.py`.

**F17. What would you change for 50k concurrent sockets?**
**Answer:** Move subscriptions out of per-process dictionaries into a shared store keyed by instance
(or use sticky routing so a user always lands on the same server), and shard the channels. Today the
honest answer is "8 workers × bounded connections per IP/user".
→ `docs/docker-concurrency-realtime.md` §D.

**F18. Is delivery guaranteed?**
**Answer:** No — per subscriber it's at-most-once, globally at-least-once. That's acceptable only
because every payload carries the complete new value ("price is now 0.62"), so a duplicate or a
missing intermediate message can't corrupt state once the client resyncs.
→ `docs/docker-concurrency-realtime.md` §D.

---

## G. Docker, CI/CD, operations

**★ G1. Describe the Docker setup.**
**Answer:** Each tier has its own multi-stage Dockerfile and its own Compose files: the backend
builds with `uv` then runs on a slim image, the frontend builds with bun/Next then runs standalone,
and each folder has a `docker-compose.dev.yml` (hot reload) and a `docker-compose.prod.yml`
(hardened, with nginx, Postgres, Redis and the Celery worker and beat scheduler wired in).
→ `docs/docker-concurrency-realtime.md` §A.

**★ G2. Why multi-stage?**
**Answer:** Compilers, package-manager caches and source code are needed to *build* but not to
*run*. Splitting them means the final image contains only the runtime — smaller to pull, faster to
start, and a much smaller attack surface.
→ `backend/Dockerfile`.

**★ G3. Why gunicorn with 8 `UvicornWorker`s?**
**Answer:** Each worker is a separate OS process with its own event loop, so they use all the CPUs
and one crash doesn't take down the app. `preload_app=False` means each worker builds its own
connection pools instead of sharing forks of one.
→ `backend/gunicorn.conf.py`.

**★ G4. Why `timeout = 120`?**
**Answer:** Because gunicorn kills a worker that hasn't reported back within the timeout, and open
WebSockets are *supposed* to sit idle between messages. 120s is longer than the keepalive, so long
live connections aren't reaped. The code comment calls this the "M4 fix".
→ `backend/gunicorn.conf.py`.

**★ G5. What does nginx do here?**
**Answer:** It terminates TLS, serves and compresses the frontend's static files, proxies API calls
to the backend, turns off response buffering for WebSockets so frames flow immediately, and forwards
the client's real IP — which the app only trusts if that proxy's IP is in `TRUSTED_PROXY_IPS`.
→ `deploy/nginx/`.

**G6. What's in the images and what isn't?**
**Answer:** In: runtime dependencies, built assets, a non-root user. Out: the other build stage's
source, secrets (they come from the environment at runtime), development tooling and any shell
utility we don't actually need.
→ `backend/Dockerfile`, `frontend/Dockerfile`.

**G7. How are secrets handled?**
**Answer:** From an `.env` file at runtime, never baked into an image — a built image is
distributable, a running container's env is not. The app refuses to start if a placeholder secret is
still set, and the TOTP encryption key is separate from the JWT secret so rotating one doesn't break
the other.
→ `backend/app/config.py`.

**G8. What does CI run?**
**Answer:** The backend runs `ruff` plus the full pytest suite with a coverage floor
(`--cov-fail-under=65`), rebuilding the database from migrations — so a broken migration fails CI.
The frontend runs `bun run lint` (0 errors allowed; the four heuristic `react-hooks` rules are
`warn` because of ~65 pre-existing chart-package hits) and `bun run typecheck` in `apps/web`. A
third job runs Trivy filesystem/config scans and uploads SARIF **report-only**, so findings are
visible without blocking anything. Two things to name unprompted: the workflows used to sit under
`backend/.github/workflows/` where GitHub never executes them (now at the repository root), and
there is deliberately **no deploy workflow** — deploys are manual until there's something to
deploy to.
→ `.github/workflows/ci.yml`.

**G9. How do you roll out without dropping requests?**
**Answer:** Rebuild the images, then restart services one at a time with `docker compose up -d
--no-deps`, so healthchecks bring each one back before the next goes. Gunicorn's graceful timeout
finishes in-flight requests, and WebSockets reconnect with backoff on the client side.
→ `docs/docker-concurrency-realtime.md` §A.

**G10. What's the healthcheck story?**
**Answer:** `/health` says "the process is alive", `/health/ready` says "I can reach the database and
Redis". The orchestrator uses the first to restart a hung process and the second to decide whether
to send traffic. Both are exempt from rate limiting so monitoring never gets throttled.
→ `backend/app/app.py`.

**G11. Why Compose and not Kubernetes?**
**Answer:** One host and a handful of services don't justify a cluster's operational overhead.
Compose gives reproducibility — the same file starts it on any machine — and because everything runs
as standard images, we could move to Kubernetes unchanged if we ever needed it.
→ `backend/docker-compose.prod.yml`, `frontend/docker-compose.prod.yml`.

**G12. What happens on `docker compose down` mid-trade?**
**Answer:** Every open database transaction rolls back, so nothing is half-applied — no shares moved
without money moving. Clients retry with their idempotency key, and the retry returns or recreates
the original result.
→ `docs/docker-concurrency-realtime.md` §C.

**G13. How would you back up Postgres?**
**Answer:** Nightly `pg_dump` plus write-ahead-log archiving so you can restore to any point in time.
Redis needs no backup: it holds caches, counters and short-lived codes — losing it costs rate-limit
counts and pending one-time codes, not money.
→ `docs/docker-concurrency-realtime.md` §A.

**G14. How do logs get out of containers?**
**Answer:** One structured JSON line per request with `request_id`, user, method, path, status,
latency and client IP — read with `docker logs` or shipped to a log system. Headers are scrubbed so
cookies and authorization values are never written to disk.
→ `backend/app/api/middleware.py`.

**G15. Why pin base images / lockfile installs?**
**Answer:** So a build today produces the same artefact as a build last month. `uv.lock` and
`bun.lockb` are installed verbatim, meaning no floating dependency can silently change behaviour
between deploys.
→ `backend/Dockerfile`, `frontend/Dockerfile`.

**G16. Resource limits?**
**Answer:** Compose can set memory and CPU limits per container, but the limits that actually matter
are in the application: 256 KiB body cap, 64 KB WebSocket frames, connection caps and rate limits —
those stop a single client from starving the host even without container quotas.
→ `backend/app/api/middleware.py`.

**G17. What would you add next?**
**Answer:** CI at the repository root so it actually runs, image vulnerability scanning (trivy), an
SBOM for each release, and a staging environment that mirrors production.
→ `docs/viva-questions.md` §M.

**G18. Dev vs prod compose differences?**
**Answer:** Dev mounts the source with hot-reload and exposes debug ports; prod uses pre-built
images, nginx, healthchecks, and no secrets in the repository. Same services, different wiring — and
there's one pair of these files per tier (backend and frontend).
→ `backend/docker-compose.dev.yml`, `backend/docker-compose.prod.yml`.

**G19. Why non-root in the container?**
**Answer:** Container-escape mitigation. If an attacker breaks out of the process, they shouldn't be
root inside the container either — a non-root user limits what they can read or change.
→ `backend/Dockerfile`.

**G20. How do you scale the API?**
**Answer:** `docker compose up --scale api=4` behind nginx — and it's *correct* because of the
design: every worker already listens to Redis pub/sub, so any instance can serve any user and push
to them. That's the payoff of F2.
→ `docs/docker-concurrency-realtime.md` §D.

---

## H. Security (auth, SQLi, XSS, CSRF, and friends)

**★ H1. Explain the auth model in 30 seconds.**
**Answer:** You get a short-lived access token (15 minutes) and a long-lived refresh token (30 days),
both stored in HttpOnly cookies the page's JavaScript can't read. The access token carries a session
id that must match a live session row in the database — so logging out, logging out everywhere, or
revoking one device takes effect *immediately*, instead of waiting for a token to expire.
→ `docs/auth-and-security.md` §1–§3.

**★ H2. Why is refresh-token reuse treated as theft?**
**Answer:** Each refresh mints a new token and invalidates the old one. If a *revoked* token comes
back, two different parties hold the same secret — one of them is an attacker. So we treat that as a
breach: revoke every refresh token and session for that user, and log a warning.
→ `docs/auth-and-security.md` §2.

**★ H3. What is SQL injection and why can't it happen here?**
**Answer:** SQL injection is when a user types `'; DROP TABLE users; --` into a field and the server
glues it into a query. It can't happen here because we never build SQL by pasting strings: the ORM
sends every value separately as a bound parameter, and the four places that write raw SQL use named
binds (`:name`). The one clause that *can't* be parameterised — `ORDER BY` — is a whitelist of
allowed column names.
→ `docs/auth-and-security.md` §7.

**★ H4. What's the difference between parameterisation and escaping?**
**Answer:** Parameterisation sends the value out of band, so the SQL parser never confuses your data
with the command — safe against any payload. Escaping rewrites dangerous characters inside the
string, which is pattern-based and depends on context. We do both: bound parameters everywhere, plus
escaping for `ILIKE` wildcards so a search for `100%` works.
→ `docs/auth-and-security.md` §7.

**★ H5. What is XSS, and why is React enough?**
**Answer:** Cross-site scripting is an attacker's script running in *your* session on *our* site.
React escapes everything it renders by default, and this codebase has no `dangerouslySetInnerHTML`,
`eval` or `innerHTML` anywhere for that script to hide in. On top of that we send a Content Security
Policy, `nosniff`, and HttpOnly cookies — React is layer one, not the only layer.
→ `docs/auth-and-security.md` §8.

**★ H6. What is CSRF and how is it blocked without a token?**
**Answer:** Cross-site request forgery is another site making your browser send a request to us,
reusing your cookies. Four independent gates stop it: cookies are `SameSite=Lax` so browsers don't
attach them to cross-site POSTs; we only accept `application/json`, which isn't a "simple" content
type so the browser must ask permission first (CORS preflight); CORS is a strict allowlist of origins
with no wildcards; and the app itself rejects any request whose `Origin` header isn't on that
allowlist — in **every** environment, not just production.
→ `docs/auth-and-security.md` §9.

**★ H7. Why no anti-CSRF token?**
**Answer:** Tokens are the classic fix, but with `SameSite`, a JSON-only API and an enforced Origin
allowlist we already have four independent layers, and a token would add a stateful round trip. The
residual threat — an attacker on the same site or a subdomain — is exactly what the Origin check
covers. We can state that trade-off honestly.
→ `docs/auth-and-security.md` §9.

**H8. Explain bcrypt cost and why a slow hash.**
**Answer:** bcrypt deliberately takes about 100ms per check (cost factor 12), which means a stolen
table of password hashes is expensive to crack — thousands of guesses per hour instead of millions.
The same slowness is why we run a *dummy* hash when the email doesn't exist: otherwise a fast
response would reveal which accounts are registered.
→ `backend/app/deps.py`.

**H9. What is 2FA here?**
**Answer:** Standard TOTP (the thing Google Authenticator does): a 160-bit secret shown as a QR
code, stored encrypted with a separate key, valid for 30 seconds with a ±1 step drift window.
Enabling it requires a *valid* code — proof your authenticator actually works — and disabling it
requires both your password and the current code. The setup session expires in 15 minutes.
→ `backend/app/api/auth.py`.

**H10. What are the rate limits?**
**Answer:** 60 requests per minute per IP for general traffic; 5 per minute per email+IP for
login/verify/reset; 3 per minute for resends and registration; 10 per minute for strict endpoints.
They're sliding windows computed in Lua on Redis, so counts are exact. After 5 failed attempts
there's progressive friction — 1s, 2s, 4s, 8s, 16s — then a 15-minute lockout that clears on a
successful login.
→ `backend/app/api/middleware.py`.

**H11. Why is the rate-limit key `email@ip` and not just IP?**
**Answer:** Both are used, for different attacks: IP alone stops one host hammering many accounts;
email+IP stops one account being brute-forced from a botnet *without* locking out every colleague
behind the same office IP. IPv6 addresses are normalised to their /64 block so one machine can't
rotate itself into fresh buckets.
→ `backend/app/api/middleware.py`.

**H12. How is the client IP determined, and what's the trap?**
**Answer:** Only from `X-Forwarded-For`, and only when the direct peer is a proxy we've listed in
`TRUSTED_PROXY_IPS` — otherwise the header is ignored entirely. The trap is that anyone can send a
fake `X-Forwarded-For`, and if we trusted it, an attacker could rotate through thousands of fake IPs
to bypass every rate limit and poison the audit log. Operational consequence: set
`TRUSTED_PROXY_IPS` in production.
→ `backend/app/api/middleware.py`.

**H13. Where is OTP stored and what's in Redis?**
**Answer:** Redis holds only a keyed hash of the code, never the code itself, with a 10-minute
expiry — so a dump of Redis can't be used to log in. The plaintext exists only in the API response
and the email. Sending is limited to 5 per 5 minutes and verifying to 5 per 5 minutes, both with
atomic Lua counters, and the code is deleted on success.
→ `backend/app/services/otp_service.py`.

**H14. What's the OTP brute-force math?**
**Answer:** An 8-digit code has 100 million combinations, but you only get 5 tries per 5-minute
window and each code dies on success — and the send cap stops you re-rolling the target. You'd need
on the order of 100,000 windows (months) with no chance of ever trying a fresh code. Effectively
infeasible.
→ `docs/auth-and-security.md` §3.

**H15. What does logout actually do?**
**Answer:** Three things at once: the access token's id is blacklisted in Redis for its remaining
life, the refresh token is revoked, and the session row is revoked. So the current token dies
immediately rather than in 15 minutes. The blacklist write fails *closed* — if we can't record the
logout, we refuse the request rather than let the token keep working.
→ `docs/auth-and-security.md` §5.

**H16. How do you prevent account takeover via password reset?**
**Answer:** The one-time code is verified *before* the new password is even checked against the
strength policy, so an attacker can't probe the policy without a valid code; everything is
rate-limited; and a successful reset revokes every refresh token and session, so any session the
attacker already had is killed too.
→ `backend/app/api/auth.py`.

**H17. What is enumeration and where does it remain?**
**Answer:** Enumeration is discovering which emails are registered. Login, forgot-password and
resend all return identical messages and take identical time (the dummy hash), so they leak nothing.
Registration used to be the exception — it returned "account already exists" for a verified
address. It now answers the same 200 with the same body and message in all three cases (new,
verified, awaiting verification); a verified address triggers a *throttled* "you already have an
account" email instead. So nothing in the auth surface tells you whether an address is registered.
→ `docs/auth-and-security.md` §12.

**H18. How are webhooks verified?**
**Answer:** Stripe's signature header is checked against our secret with a timestamp tolerance, so a
forged or replayed body fails. Then a Redis `SET NX` on the webhook id rejects duplicates, a unique
`deposit_ref` index rejects concurrent deliveries, and the wallet is locked while the credit is
applied.
→ `docs/auth-and-security.md` §6.

**H19. What is IDOR and where was it guarded?**
**Answer:** Insecure direct object reference: changing `?id=123` to `?id=124` to see someone else's
data. Every ownership-scoped query filters by the logged-in user's id (sessions, comments,
positions, orders), and the personal notifications WebSocket refuses to deliver unless the token's
user id equals the id in the URL.
→ `docs/auth-and-security.md` §4.

**H20. Why does the Origin check live in the app and not only in CORS middleware?**
**Answer:** Because CORS is enforced by the *browser*, not by us — a curl request or a misconfigured
proxy doesn't care about CORS. An in-app check means a non-browser client with a forged or foreign
`Origin` still gets a 403. Defence in depth: we don't rely on the client's cooperation.
→ `backend/app/api/middleware.py`.

**H21. What security headers do you send?**
**Answer:** `nosniff` (never guess a content type), `X-Frame-Options: DENY` (no clickjacking),
`Referrer-Policy` (don't leak URLs), `Permissions-Policy` (camera, mic, geolocation, payments all
off), a Content-Security-Policy — `default-src 'none'` on the API since it only returns JSON, and a
full one on the site including `frame-ancestors 'none'` — plus HSTS in production.
→ `backend/app/api/middleware.py`.

**H22. What would you do first with more time?**
**Answer:** Frontend tests — that layer is empty and it's where a user meets everything else.
Then a nightly invariant audit (compare each pool's escrow against its open claims), then depth:
deeper liquidity and an LP position that isn't just a number in a dropdown. Accounting and the
refresh-chain cap are done, which is why they're not on this list.
→ `docs/trading-engine.md` §6.

**H23. What's your threat model in one line?**
**Answer:** Protect user funds and accounts from remote attackers across the web, API and network;
assume the database and logs are semi-trusted; assume the client is completely hostile — it's the
attacker's machine, not ours.
→ `docs/auth-and-security.md` §12.

**H24. How do you handle a leaked JWT_SECRET?**
**Answer:** Rotate it — that invalidates every access token, so everyone re-authenticates within 15
minutes anyway. Rotate the TOTP encryption key separately if it was affected, and audit the
authentication log. Refresh tokens are stored hashed in the database, so leaking the signing key
doesn't let anyone mint one.
→ `docs/auth-and-security.md` §5.

**H25. Is storing refresh tokens as SHA-256 enough?**
**Answer:** Yes — and bcrypt would be the wrong tool here. SHA-256 is fast, which is correct for a
high-entropy random token: there's no dictionary to precompute against, so speed costs nothing. Slow
hashes exist to defend low-entropy *passwords*.
→ `docs/auth-and-security.md` §2.

**H26. Why `Secure` cookies only in production?**
**Answer:** Because `Secure` means "only over HTTPS", and local development runs on plain http — the
cookie would never be sent and login would break. In production the flag is on, so tokens can never
travel in cleartext.
→ `backend/app/api/auth.py`.

**H27. What could an attacker still do today?**
**Answer:** Three things, all documented: a logged-out token stays usable outside production while
Redis is down (the blacklist fails open below `APP_ENV=production` — and the app says so at
startup), a non-browser client can be given `WS_ALLOW_QUERY_TOKEN=true` which puts a live token in
a URL, and — if `TRUSTED_PROXY_IPS` isn't configured — everyone behind that proxy shares one
rate-limit bucket. Enumeration is no longer one of them: registration answers uniformly.
Naming these before you're asked is the answer.
→ `docs/auth-and-security.md` §12.

**H28. Denial of service: what stops one client taking the API down?**
**Answer:** Layered caps: 256 KiB request bodies, 64 KB WebSocket frames, connection and
subscription caps, sliding-window rate limits, progressive friction on auth, `SKIP LOCKED` so nobody
ever waits on another request's lock, and per-market fault isolation so one broken market's
background job can't kill the run.
→ `backend/app/api/middleware.py`.

**H29. How would you prove these defences work?**
**Answer:** With regression tests per control: a revoked or blacklisted token must be rejected at
the WebSocket handshake, a spoofed `X-Forwarded-For` must be ignored, Redis must never contain a
plaintext OTP, an unknown Origin must be blocked outside production, and the dummy password hash
must be cached so timing doesn't leak. Plus the auth and rate-limit suites.
→ `backend/tests/test_security_fixes.py`.

**H30. What does "fail closed" mean, and where did you choose it deliberately?**
**Answer:** If a security component is unavailable, deny the request instead of allowing it. We
chose it for token-blacklist reads in production, for rate limiting when Redis is down, and for
`X-Forwarded-For` handling. The single exception is development, where a Redis restart shouldn't
break the dev loop — that's a deliberate, documented choice.
→ `docs/auth-and-security.md` §12.

---

## I. Trading engine, AMM, split/merge

**★ I1. Explain order matching in one paragraph.**
**Answer:** When an order arrives we look at the resting orders already on the book, best price
first, then oldest first. We lock those rows with `SKIP LOCKED` so we never wait on another worker.
You fill at the **maker's** price — if you said you'd pay up to $0.60 and the best offer is $0.55,
you pay $0.55: that's price improvement. Before anything moves we check the buyer can afford it and
re-check the seller actually holds the shares; then both wallets are updated (locked in sorted order
to avoid deadlock), the maker's remaining amount is decremented — dollars for a resting buy, shares
for a resting sell — and two trade rows are written, one per side.
→ `docs/trading-engine.md` §2.1.

**★ I2. What is the AMM's price formula?**
**Answer:** `price(YES) = YES shares in the pot ÷ total shares in the pot`, and `price(NO)` is the
rest — so the two always add up to exactly $1. It is deliberately *not* the textbook `x·y=k`
constant-product curve; here the pot's share count is what sets the price, and the pot grows when
you buy.
→ `backend/app/amm/engine.py`.

**★ I3. How does the AMM decide how many shares a $10 buy gets?**
**Answer:** It solves the equation "how many shares make the dollar amount equal to the number of
shares times the price *after* my trade" — because you must pay the price your own order created:
`shares = (C_net − R + sqrt((R − C_net)² + 4·C_net·T)) / 2`, where `R` is the pot's reserve on that
side and `T` the total. Charging the post-trade price on every share is precisely what charges price
impact.
→ `docs/trading-engine.md` §2.

**★ I4. What was the bug, and why did it matter?**
**Answer:** The buy used to be priced at the *pre-trade* price — no price impact at all. So you
could buy (price rises), immediately sell (you're paid at the higher price), and come out ahead:
+11.8% risk-free on a $100 pool. Anyone could have drained the pot. We fixed the formula so you pay
the post-trade price, updated the tests, and pinned the no-arbitrage property.
→ `docs/trading-engine.md` §2.2, `tests/test_amm.py`.

**★ I5. Prove a round trip can't profit.**
**Answer:** You always transact at the *worse* of the two prices: buying charges you the price you
pushed the market up to, selling pays you the price you pushed it down from. So both sides are
against you, and after fees a buy-then-sell of the same shares returns exactly `(1 − fee)²` of what
you put in — never more, at any size. That's asserted by `test_round_trip_returns_only_fees`.
→ `backend/tests/test_amm.py`.

**★ I6. What does split do?**
**Answer:** It converts dollars into a matched pair: put in $100, a 2% fee is taken, and you receive
98 YES **and** 98 NO shares — your balance goes down by 100, your share count up by 98 on each side,
and the pool's fee ledger goes up by 2. Because the two prices always sum to $1, that pair is worth
exactly $1 regardless of the outcome — so splitting is a neutral deposit, not a bet.
→ `backend/app/api/split_merge.py`.

**★ I7. What does merge do?**
**Answer:** The reverse: you hand back equal amounts of both sides (you must hold both) and receive
`amount × 0.98` dollars — the same 2% fee again. Each side's profit or loss is realized as you go,
zero-share rows are kept for history. A split followed by a merge returns `(1 − fee)²`, the same
fee-only rule as trading.
→ `backend/app/api/split_merge.py`.

**★ I8. Do split/merge move the price?**
**Answer:** No. They only create or destroy shares **you** hold; they never touch the pool's own
reserves, and the price is nothing but the ratio of those reserves. Only AMM buys and sells change
reserves, hence price.
→ `docs/trading-engine.md` §4.

**★ I9. How is a winner paid, and from where?**
**Answer:** At settlement every winning share is credited at $1 flat into your wallet, and losing
positions are recorded with a zero payout. The money comes out of `pool.collateral` — a real
escrow every buy, split and deposit credited and every sell, merge, LP exit and fee sweep debited —
and nothing is taken from you at settlement. A `settled_at` flag set under a row lock means it can
only happen once, and the claim endpoint is all-or-nothing: if the escrow can't cover a winner it
answers `ESCROW_INSUFFICIENT` and leaves the position claimable rather than paying a part.
Honest caveat to volunteer: the settlement worker pays what the escrow holds and logs any shortfall
instead of failing, and nothing audits every pool nightly against open claims.
→ `docs/trading-engine.md` §5, §6.

**★ I10. How is this not gambling?**
**Answer:** Because you're buying a **claim** worth $1 if you're right, not placing a bet against a
house. The price is a public probability that other traders set, you can exit any time at that price,
the only charge is a disclosed trading fee (~3% on pool trades, 1% on direct matches) and **nothing**
is taken when you're paid out — and the money you win comes from the people who were wrong, not from
a bookmaker whose odds already guaranteed it wins either way. Full table plus the honest caveats:
`docs/trading-engine.md` §7.

**I11. Where do fees go?**
**Answer:** The 2% pool fee stays inside the pool, which is what liquidity providers earn their share
of. The 1% protocol fee is recorded in the pool's fee ledger and swept to the platform's treasury
account at settlement — on a direct book match it's taken out of the seller's proceeds and credited
to that same ledger. Split and merge also add their 2% to the protocol fee ledger.
→ `docs/trading-engine.md` §2.

**I12. What is slippage here and how is it enforced?**
**Answer:** Effective price (`dollars ÷ shares`) compared with the price before your trade. You can
send a `max_slippage` (0–10%) with the order, and if the impact-aware pricing makes your effective
price worse than that, the AMM leg is rejected with `SLIPPAGE_EXCEEDED` rather than filled. Note the
fixed formula makes large orders report *worse* effective prices — correctly.
→ `backend/app/services/order_service.py`.

**I13. What do `post_only` and FOK do?**
**Answer:** `post_only` means "never take liquidity": if your price already crosses someone else's,
the order is rejected instead of filled — you only ever add to the book. Fill-or-kill means fill the
entire amount or cancel it entirely, with the check done in the order's own units (dollars for a buy,
shares for a sell — comparing them across units was a real bug we fixed).
→ `docs/trading-engine.md` §2.

**I14. How does a resting limit order ever fill?**
**Answer:** Three ways: immediately, if a new order crosses it; every 30 seconds, a background job
re-tests orders that are still resting against the current pool price and fills them if they now
cross; and when the market closes, an expiry job releases the funds they had locked.
→ `backend/app/workers/tasks.py`.

**I15. What is an LP and what do they earn?**
**Answer:** Someone who deposits money into the pool and gets LP tokens representing their share.
They earn a slice of the trading fees that accumulate in the pool — but at settlement they're paid
out of the side that *won*, so they genuinely carry outcome risk, not just fee income. That's an
unusual design and worth admitting as a weakness.
→ `docs/trading-engine.md` §6.2.

**I16. Why is `average_price` a weighted average?**
**Answer:** Because you may buy the same share at three different prices; the average must reflect
how many you bought at each. `(old average × shares held + what you paid) ÷ new share count` keeps
your unrealised profit correct after every purchase.
→ `backend/app/services/order_service.py`.

**I17. What stops the pool being drained now?**
**Answer:** Three things: the impact-aware buy formula (you pay the price you created), the proven
round-trip invariant (a flip can only ever cost you the fee, never make you money), and slippage
limits on the order itself. On top of that, regression tests fail the build if anyone "simplifies"
the formula back to the old one.
→ `backend/tests/test_amm.py`.

**I18. What's the weakest part of the trading design?**
**Answer:** Depth: the pool is thin and linear-impact — one $10 order moves the price 7 points, so a
whale can push it around, and there's no mid-price from a book. Second, defence in depth on the
accounting: the escrow now holds every inflow and pays every outflow, and an LP exit is floored by
open claims — but nothing runs over each pool nightly comparing `pool.collateral` against
`max(open YES, open NO)` to catch drift from a bug nobody has found yet. Both are in
`docs/trading-engine.md` §6.
→ `docs/trading-engine.md` §6.

**I19. How would you add a new order type (e.g. stop-limit)?**
**Answer:** Add it to the schema's allowed values, validate it in the order service, run it through
the same book/AMM legs, add a Celery trigger that fires when the price crosses the stop, and test the
trigger path — the design deliberately keeps order types as validation plus routing, not new engines.
→ `docs/trading-engine.md` §2.

**I20. Where would you put a circuit breaker?**
**Answer:** On the AMM leg: if the pool's reserves fall below a floor, stop market sells and force
them onto the book. The settlement and LP rules already bound the damage, but an explicit floor turns
a silent drain into a visible, explainable halt.
→ `docs/trading-engine.md` §6.

**I21. Explain "price improvement" with a number.**
**Answer:** You market-buy with a limit of $0.60, and the best resting sell is $0.55 — you pay $0.55
and the maker gets exactly their $0.55. Takers never pay more than their limit, makers never receive
less than they posted; the difference is the improvement, and it comes from trading against the book
before touching the pool.
→ `docs/trading-engine.md` §2.1.

**I22. What does `remaining_amount` mean for a resting buy?**
**Answer:** Dollars of budget still unspent — not shares. A $100 buy that filled $30 has 70 *dollars*
left. Getting this wrong (treating it as shares) silently breaks partial fills, and it's guarded by a
regression test.
→ `tests/test_orders.py::test_buy_limit_persists_usdc_remainder`.

**I23. Two people sell the same shares simultaneously?**
**Answer:** Both take a lock on the same position row; the first decrements it, and the second then
re-reads holdings under lock, sees it no longer has enough, and skips that match rather than letting
shares be sold twice. Shares are never created from nothing — that guard logs the event.
→ `backend/app/services/matching_engine.py`.

**I24. What is `realized_pnl` vs unrealized?**
**Answer:** Realized is profit you've already locked in — closed by a sale, a merge or settlement —
and it accumulates in the position row. Unrealized is what you'd get *if* you closed now, computed on
the fly as `shares held × (current price − average price)`. The first is history, the second is a
number that moves.
→ `backend/app/models/position.py`.

**I25. How would you explain the AMM to a non-technical person?**
**Answer:** "Think of a shared pot full of YES and NO tickets. The more of one side the pot holds,
the pricier that side becomes — that's just the ratio. When you buy, your own order fills the pot
with more of what you bought, so you pay the slightly higher price it created. Because you paid the
price you moved *to*, selling straight back only ever gets you your money minus the fee — which is
exactly why nobody can game the pot."
→ `docs/concepts.md`.

---

## J. Product, ethics, regulation

**J1. Is this a security? a betting product? something else?**
**Answer:** Technically it's an exchange for event-contingent claims — you're trading a share that
settles at $1. Legally it depends on the jurisdiction: in some places that's a derivative and falls
under securities regulation, in others sports-event contracts are contested as betting. The right
answer is that classification is a regulatory determination, not something the code decides — and
that we've built transparent pricing with no house edge at settlement either way.

**J2. What protects users from losing money?**
**Answer:** No leverage, so you can never lose more than you deposited; no liquidation engine, no
deposit bonuses or loss-back offers that encourage chasing; visible order-book depth before you
trade, so you can see what you'd get out at; and rate limits plus friction on money movement.

**J3. What would you add for responsible trading?**
**Answer:** Self-imposed deposit and loss limits, cool-off periods, a plain loss dashboard showing
realised P&L over time, and — in a regulated build — identity and jurisdiction checks.

**J4. Who benefits from accurate prices?**
**Answer:** Everyone who reads the market as a forecast: journalists, researchers, decision-makers.
That's the public-good argument for prediction markets — and it's also why informed traders are
paid for being right, which is what draws them in and makes the price sharp.

**J5. What stops manipulation of the price?**
**Answer:** Cost. Moving the price requires real money, and reversing it costs the fee both ways, so
manipulation is expensive and self-defeating; rate limits add friction too. Honest answer: in a thin
pool a whale *can* move the price — that's exactly why showing depth matters.

**J6. Why is churn punished here?**
**Answer:** Every round trip costs `(1 − fee)²` — about 4% at a 2% fee — so repeated flipping bleeds
money. The product therefore rewards holding a view and being right, not betting on noise, which is
the opposite of the design of casino games.

**J7. What would make you refuse to ship this?**
**Answer:** Marketing it with "guaranteed returns", adding bonuses that reward chasing losses, or
offering it where it isn't licensed. Those three would cross it from exchange into predatory
gambling regardless of what the code does.

**J8. How would you audit fairness?**
**Answer:** Publish the fee schedule, expose live pool reserves and order-book depth to anyone,
keep an append-only trade log anyone can reconcile against their own fills, and make settlement a
deterministic task that can be replayed — so an outsider can verify that the numbers behave as
documented.

---

## K. Frontend (Next 16 / React 19 / Turborepo)

**★ K1. Describe the front end.**
**Answer:** Bun as the package manager and Turborepo for the monorepo, with `apps/web` — a Next.js
16 App Router app on React 19 — and `packages/ui` holding the shared components and charts. Pages
render on the server for a fast first paint and switch to client components for anything live.
→ `frontend/README.md`.

**★ K2. How does it talk to the API?**
**Answer:** Through one typed fetch wrapper: it always sends cookies, automatically performs a
single-flight token refresh when it gets a 401 (so ten parallel requests trigger one refresh), de-
duplicates identical GETs, and retries with bounds. Route protection happens in Next's middleware.
→ `frontend/apps/web/lib/api/client.ts`.

**★ K3. Where does live data go?**
**Answer:** Two WebSocket hooks patch the React Query cache in place: `useMarketSocket` keeps **one
shared connection per browser tab** with per-market subscriptions (prices, order book, live trades)
and `useUserSocket` opens the per-user notification connection. The backend also serves `/ws/trades`
for a global feed. Because the cache is patched, components re-render only where the data changed,
with no refetch.
→ `frontend/apps/web/hooks/use-market-socket.tsx`, `hooks/use-user-socket.ts`.

**★ K4. Why React Query if you have websockets?**
**Answer:** They do different jobs: sockets *push* changes, Query *owns* the cache — loading and
error states, de-duplication, retries, and re-syncing from REST after a reconnect. Sockets without a
cache leave you with nowhere to put the data.
→ `frontend/apps/web/lib/`.

**★ K5. How is state managed?**
**Answer:** Server state lives in React Query, UI state lives locally in `useState` or context, and
there's deliberately no global store like Redux — with Query handling the server half, a global store
would mostly duplicate it.

**★ K6. What's the SSR/hydration consideration?**
**Answer:** Auth is cookie-based, so the server can read who you are on the very first render instead
of flashing a logged-out page. WebSockets only start on the client after hydration — opening
connections during server rendering would leak them on every request.

**K7. How is money rendered safely?**
**Answer:** As formatted strings through decimal-aware helpers at the edge of the UI — never by
doing arithmetic on JavaScript floats. Displaying `$0.1 + $0.2` as `0.30000000000000004` would be a
bug users notice immediately.

**K8. What accessibility work is there?**
**Answer:** Semantic landmarks for screen readers, labelled form inputs, dialogs from Base UI that
are keyboard-navigable and trap focus correctly, and visible focus states. Be honest about what's
implemented rather than claiming full WCAG compliance.

**K9. Known front-end debts?**
**Answer:** The big one, still open: **no test suite at all** — the backend has 327 tests and the
frontend has none, which is exactly backwards for a UI. The rest of this list is what I found and
closed while auditing: ESLint no longer downgrades everything to warnings (the `only-warn` plugin is
gone; only four heuristic `react-hooks` rules remain `warn`, with everything else failing the build),
the duplicate `useCurrentUser` (two definitions, two refetch policies, one cache key) is down to
one, the dead `app/metadata.ts` is deleted, the unused Sonner toaster mount and its dependency are
gone, and the brand drift ("PredictX" versus "Polymarket") is swept to a single name — the `/admin`
link turned out to already be gated on `is_admin`. Naming what you checked *and* what you fixed is
the answer.

**K10. Why a monorepo package for UI?**
**Answer:** So the design system and the shared API types live in one place that both apps import,
and one token change updates everywhere. Turborepo caches that package's build, so unchanged apps
aren't rebuilt.

**K11. How would you add a page safely?**
**Answer:** Route segment for the URL, a server component to fetch initial data, a client component
for interaction, a Query mutation with an optimistic update so the UI responds instantly, a socket
handler if it needs the live edge, and then tests.

**K12. What's your build/deploy story?**
**Answer:** `next build` produces a standalone output, which goes into a small runtime image; nginx
serves the static files directly and proxies `/api` and `/ws` to the right backend. Static assets
never touch Python.
→ `frontend/Dockerfile`.

**K13. Why standalone output?**
**Answer:** Next traces exactly which files it needs and bundles only those — so the runtime image
contains a handful of modules instead of the whole `node_modules` tree. Smaller, faster to pull,
fewer vulnerabilities to scan.

**K14. What is `proxy.ts`/middleware for?**
**Answer:** Route guards and cookie handling at the edge, before a page renders — so an
unauthenticated user is redirected early. It's a first line of defence, not a replacement for the
server-side check: the API still verifies every request itself.

**K15. Why is CSP set in `next.config.ts`?**
**Answer:** Because it has to be attached to the HTML responses *Next* renders, where scripts and
styles are injected. The backend sets its own stricter policy (`default-src 'none'`) for its JSON
responses — two policies, each covering what it serves.

**K16. What would you fix first?**
**Answer:** Wire up vitest and a couple of Playwright flows (nothing is tested today), make ESLint
fail the build instead of warning, and delete the duplicate hook and dead files. In that order —
tests first, because they make the other two safe.

---

## L. Testing & observability

**L1. What's tested?**
**Answer:** 307 tests: unit tests for the AMM maths and the password/OTP/TOTP policies, API
integration tests for auth, orders, markets, wallet, admin and disputes, a concurrency suite that
fires parallel orders, WebSocket tests, and `test_security_fixes.py` for the security fixes. The
database is rebuilt from migrations on every run.

**L2. How are tests isolated?**
**Answer:** Every test truncates all tables first, Redis globals are reset between tests, and rate
limiting is disabled in the harness — which is deliberate, because no test should ever assert a 429.
Each test therefore starts from a known-empty world.

**L3. How do you fake auth in tests?**
**Answer:** We mint a *real* access token bound to a *real* session row, exactly as production does.
The fixtures assert the session exists, because a token without a session id would be rejected — so
the tests exercise the real auth path rather than a bypass.

**L4. What isn't tested?**
**Answer:** The frontend (nothing), real Stripe money end-to-end (there's a live-stack script
instead), and multi-node pub/sub — the realtime tests run in a single process, so cross-instance fan-
out is verified by design and manual runs, not by CI.

**L5. How would you test the AMM against a reference implementation?**
**Answer:** Property tests: price must be monotone, the two prices must sum to 1, a round trip must
never return more than you put in, and shares × post-trade price must equal the net collateral.
Then a seeded simulation compared against an integral of the pricing curve.

**L6. What do you log?**
**Answer:** One structured JSON line per request — `request_id`, `user_id`, method, path, status,
latency and client IP — with headers scrubbed so cookies are never written. Celery logs each task's
start, completion, duration and structured result.

**L7. How do you correlate a bug across services?**
**Answer:** A `request_id` travels from the client (or is generated on entry) through the logs and
into the Celery task id, and every event payload carries market and user ids. One id in a log search
shows the whole path: API → worker → websocket.

**L8. What metrics would you add?**
**Answer:** Request latency histograms, lock-wait time, WebSocket connections and subscriptions,
pub/sub lag, settlement duration, and pool reserve drift — that last one would have caught the AMM
pricing bug early.

**L9. How do you know a deployment is healthy?**
**Answer:** Healthchecks and readiness gates, then error rate and p95 latency from the JSON access
logs, WebSocket connect success rate, and Celery task failure counts. Any of those moving after a
deploy means roll back.

**L10. What's your debugging process for "trade didn't fill"?**
**Answer:** In order: the order status, then `remaining_amount` to see what's left and in which
units, then the market and pool rows, then the Redis dirty set (is this market being processed at
all?), then worker logs, and finally the guards in the order service — balance, holdings, slippage
and fill-or-kill are the four reasons a fill is refused.

**L11. How do you reproduce a concurrency bug deterministically?**
**Answer:** Repeat the exact interleaving with two database sessions and explicit transaction
boundaries — start A, take its lock, start B, let it block, commit A, watch B — instead of hammering
and hoping. Then assert on invariants, not on messages.

**L12. Why assert invariants instead of exact values?**
**Answer:** Because rounding to 8 decimal places and fee splits make exact floating-point
expectations brittle, and a brittle test gets deleted. "Total wallet balances equal the sum of
reported effects, and nothing is negative" catches every real class of bug and never flakes.

**L13. What's in CI that must never regress?**
**Answer:** `ruff check` plus the entire pytest suite with a 65% coverage floor — and because the
suite builds its schema by running the real migrations, a broken migration fails CI too. On the
frontend, lint (zero errors) and typecheck in `apps/web`. Trivy scans also run, but report-only:
findings get uploaded without blocking anything, because there is no deploy to block.

**L14. How do you test security controls?**
**Answer:** One regression test per control: a revoked or blacklisted token must be rejected at the
WebSocket handshake, a spoofed forwarded-for header must be ignored, Redis must never contain a
plaintext one-time code, an unknown Origin must be blocked outside production, and the dummy password
hash must be cached.

**L15. What would your test pyramid look like with more time?**
**Answer:** A broad base of unit and property tests (especially the AMM), a handful of Playwright
end-to-end flows — login → trade → claim — and one load test proving pub/sub fan-out stays correct
under N concurrent connections. Frontend tests first, since that's the empty layer.

---

## M. Open / reflective ("what would you change?")

**★ M1. What's the biggest weakness of this system?**
**Answer:** Depth, and the accounting confidence that comes with depth. The pool is thin — one $10
order in a $100 market moves the price seven points — and while the escrow now holds every inflow
and pays every outflow (an LP exit is floored by open claims), nothing audits each pool nightly
against `max(open YES, open NO)` to catch drift from a bug nobody has found. Both are in §6 of the
trading doc and I'd volunteer them before being asked. The single-entry ledger that used to head
this answer is fixed: one choke point debits and credits, and settlement pays from escrow.
→ `docs/trading-engine.md` §6.

**★ M2. What did you learn the hard way?**
**Answer:** Pick one you can tell properly. My favourite: the AMM used to charge the pre-trade price,
so buy-then-sell returned 11.8% more than you put in — a genuinely drainable pool that only a
round-trip test exposed. Others: trade rows silently disappearing because a buy's `remaining_shares`
was set to zero, and wallet deadlocks solved by sorting user IDs.

**★ M3. If you had another month?**
**Answer:** In order: frontend tests (the only empty test layer), then a nightly invariant audit
over every pool's escrow versus its open claims, then deeper liquidity and a real LP position with
a P&L view, then cross-node sharding for the WebSocket registries, then the observability metrics.
The three that used to head this answer — the escrow ledger, CI moved to the repository root, and
the refresh-chain cap — are done.

**★ M4. Why did you use `SKIP LOCKED` instead of a queue table?**
**Answer:** Because Postgres *is* the queue — no second system to keep consistent with the data, and
claiming a row is transactional with doing the work. A separate queue table means two stores that can
disagree after a crash.

**★ M5. What breaks at 10× traffic?**
**Answer:** Three things: contended markets serialise behind each other (by design), the resting-
order sweep still has a 30-second backstop poll (a fill now re-arms it immediately, throttled to one
per second, but a burst of fills still collapses onto one sweep), and per-process WebSocket
registries don't scale outward. Fixes: batch wallet updates, move the sweep to a real queue with a
per-market consumer, and share subscriptions through Redis or route them consistently by market.

**M6. What would you do differently architecturally?**
**Answer:** Split the matching engine into its own service with an append-only event log, and keep the
API as a query layer over it. Today they're coupled in one process, which is simpler but means
matching scale and API scale are the same axis.

**M7. Tell me about a design decision you'd reverse.**
**Answer:** Three I already reversed, in the order I hit them: crediting the ledger without ever
debiting it (now every pool flow goes through `credit_collateral`/`debit_collateral`), redeeming LPs
from the winning side's reserve (now a pro-rata slice of collateral, floored by open claims), and
accepting `?token=` on the WebSocket by default (now off unless `WS_ALLOW_QUERY_TOKEN=true`). What
I'd still reverse: polling for resting-order fills every 30 seconds instead of a queue — a fill now
wakes the sweep immediately, but the backstop is still a timer.

**M8. How do you keep docs honest?**
**Answer:** They're written from the code and updated in the same change as every fix — including
the parts that are still wrong. This document and its siblings describe the *fixed* behaviour and
carry an explicit list of what remains broken, rather than describing an aspiration.

**M9. What would you tell a new developer on this repo?**
**Answer:** Read two things first: the lock order (market → pool → wallet → position → order) and the
units table (a buy's `amount` is dollars, a sell's is shares). Most confusion — and most bugs — in
this codebase come from one of those two.
→ `docs/trading-engine.md` §1.

**M10. If the AMM fee were zero, what breaks?**
**Answer:** Round trips become exactly break-even, so churning costs nothing, and arbitrage between
the book and the pool becomes free — someone could bounce value between them until one side empties.
Liquidity providers would also earn nothing, so nobody would provide liquidity. The fee is what makes
churn unprofitable.

**M11. Why Postgres and not MongoDB?**
**Answer:** Money needs transactions, unique constraints and row locks. In a document store those
guarantees don't exist, so you'd push integrity into application code — exactly where a race between
two requests can slip through.

**M12. Why not run matching in Redis?**
**Answer:** Redis isn't transactional with the ledger, so a match could succeed while the money update
failed, and you'd have no way to roll both back together. The speed isn't worth losing atomicity
between a trade and the balance it moves.

**M13. How would you migrate the ledger to double-entry without downtime?**
**Answer:** We did the smaller version of this and it's shipped: one choke point on the pool row
(`credit_collateral`/`debit_collateral`), every call site moved onto it path by path with the test
suite proving wallet-delta == collateral-delta at each step, and settlement switched to pay from
escrow last. Shadow first, flip second — no window where money can vanish. Going the final step to
proper double-entry would be the same shape: backfill accounts from `transaction`, run the new ledger
in parallel until its sums match, then switch writers.

**M14. What's one security control you'd add tomorrow?**
**Answer:** A device/geo baseline per session — the refresh token is already bound to a user-agent
and reuse kills the whole chain, but I'd add a coarse IP/ASN change signal so "same UA, other side
of the world" forces a re-login instead of a silent refresh. (The two I'd have said a month ago —
an absolute lifetime on refresh chains, and CI moved to the repository root so GitHub actually runs
it — are both in place.)

**M15. Pitch this in one sentence.**
**Answer:** "A zero-house-edge exchange for event outcomes: an order book plus a price-impact-aware
AMM, settled at $1 per correct share, protected by row-level locking and idempotency keys, and
delivered in realtime over Redis fan-out."

---

## N. Curveballs — short, confident answers

* **"Is this gambling?"**
  → It's a claim, not a bet: you buy a share worth $1 if you're right, exit any time at a public
  price, pay a disclosed trading fee, and take nothing at settlement. The money you win comes from
  the losing side, not from a bookmaker. Own the nuance — sports contracts are legally contested.
  Full table: `trading-engine.md` §7.

* **"Hack it live — where would you start?"**
  → Registration tells you if an email exists; a spoofed `X-Forwarded-For` if `TRUSTED_PROXY_IPS`
  is unset; a `?token=` in a proxy's access log. Then immediately say which of the three you'd fix
  first (the Origin/register one, since the token only has a 15-minute window).

* **"What's your take rate?"**
  → 2% pool fee + 1% protocol fee = 3% configured on pool trades, 1% on direct book matches, and
  nothing at settlement. Roughly 4% lost per round trip.

* **"Show me where you prevent SQL injection."**
  → `select(User).where(User.email == data.email)` compiles to a bound parameter, never string
  concatenation; the only raw SQL blocks use `:name` binds, and `ORDER BY` is a whitelist.

* **"Why 8 workers?"**
  → One event loop per worker, so they use all the CPUs and isolate crashes from each other — and
  `timeout=120` keeps long-lived WebSockets alive inside them.

* **"What if Redis dies mid-trade?"**
  → The trade still commits: money lives in Postgres. You lose the live push and, in production, rate
  limiting — which fails closed. Users refresh over REST.

* **"Why is my order still pending?"**
  → Because it's a limit priced away from the market and no resting order crosses it. It gets
  re-tested whenever a fill moves that market's price (the fill re-arms the sweep immediately, at
  most once a second), with the 30-second background check as the backstop, and expiry frees the
  funds when the market closes.

* **"How do you know two concurrent buys don't corrupt balances?"**
  → `test_concurrency.py` fires parallel orders and asserts the invariants, plus the balance check
  `balance − locked ≥ required` runs while both wallets are locked.

* **"What's the hardest bug you fixed?"**
  → The AMM round-trip exploit — buy then sell returned 11.8% more than you put in, so the pool could
  be drained. Fixed by charging the post-trade price, with regression tests that fail if anyone
  reverts it.

* **"What's a thing you knowingly left wrong?"**
  → No frontend test suite at all, a thin AMM with linear impact, and no nightly invariant audit
  comparing each pool's escrow to its open claims — all listed in `trading-engine.md` §6 and
  `auth-and-security.md` §12. The three that used to be the answer here (single-entry ledger,
  register email enumeration, uncapped refresh chains) are fixed and tested; naming what's *still*
  wrong yourself is the answer.

---

## Cheat sheet — numbers worth remembering

| Thing | Value |
|---|---|
| Access token TTL | 900 s (15 min) |
| Refresh token TTL | 2 592 000 s (30 days), rotated per use |
| Password hash | bcrypt cost 12, ~100 ms |
| TOTP | 6 digits, ±30 s window, setup session 900 s |
| OTP | 8 digits, 600 s TTL, 5 sends / 5 verifies per 300 s, hash-only in Redis |
| Rate limits | 60/min/IP general · 5/min auth-decision · 3/min auth-fast · 10/min strict |
| Friction | 5 free attempts, then 1→2→4→8→16 s, 900 s lockout |
| Request body cap | 256 KiB (checked on `Content-Length`) |
| WS frame cap | 64 KB · 50 subs/socket · 50 conns/IP · 5 conns/user |
| Fees | pool 2% (`trading_fee_rate`) · protocol 1% (`protocol_fee_rate`) · split/merge 2% |
| AMM round trip | returns exactly `(1 − f)²` of input — never more |
| AMM buy | `shares = (C_net − R + sqrt((R−C_net)² + 4·C_net·T)) / 2` |
| AMM price | `p(YES) = yes_shares / (yes_shares + no_shares)` |
| Lock order | market → pool → wallet → position → LPShare → Order (wallets also sorted by id) |
| Workers | gunicorn 8 × UvicornWorker, `timeout=120`, `graceful_timeout=30` |
| Beat cadence | order expiry/limit check 30 s · prices 60 s · resolution 5 min · snapshot 300 s |
| Test suite | 307 tests, DB rebuilt from Alembic `head` every run |
| Test infra | `pm-postgres` on 5433, `pm-redis` on 6380 — `docker start pm-postgres pm-redis` |
