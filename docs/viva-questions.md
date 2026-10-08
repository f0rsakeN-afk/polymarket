# Viva Question Bank — Polymarket Clone

> **Sections A–N** are the core set (architecture, backend, DB, concurrency, idempotency, realtime,
> ops, security, trading, product, frontend, testing, reflective, curveballs). **O–R** add the data
> model, background jobs, frontend and platform-feature answers. Start with the starred (★) ones.
> frontend and platform-feature answers. Start with the starred (★) ones.

> **Every question below has a full, spoken-word answer.** You do not need to be a programmer to
> deliver any of these: read the **Answer** paragraph out loud and you have said the right thing.
> The `→` at the end points to the doc/file with the deep version, if the examiner pushes.
>
> Companion docs: `docs/concepts.md` (plain English, start here) · `docs/data-model.md` ·
> `docs/trading-engine.md` · `docs/platform-features.md` · `docs/auth-and-security.md` ·
> `docs/docker-concurrency-realtime.md` · `docs/background-jobs.md` · `docs/frontend.md` ·
> `docs/architecture.md`.

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
**Answer:** Two layers. `backend/app/redis.py` owns the clients — an async one for the API and a sync
one for Celery, plus Sentinel support and a `RedisCircuitBreaker` that opens after five consecutive
failures and lets one probe through after thirty seconds. Then `redis_cb.call(...)` wraps every
individual Redis call so a hung or down Redis degrades one feature — caching, fan-out, rate limiting —
instead of the whole request. The trading path is unaffected because money lives in Postgres.
→ `backend/app/redis.py`, `docs/background-jobs.md` §6.3.

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
**Answer:** It depends on the socket, and the split is by data, not by convenience.
**`/ws/markets/{id}` and `/ws/trades` are public** — the same numbers are already served
anonymously by `GET /markets/{slug}/orderbook` and `GET /trades`, so requiring a login would gate
public information. A cookie is used if present (it upgrades you to the per-user connection cap)
but is not required; the abuse limits that matter — 50 connections per IP, 50 subscriptions per
socket, 64 KB frames — are keyed on IP and work fine anonymously.
**`/ws/notifications/{user_id}` is private**: it is the only surface serving the per-user
`user:{uid}:notifications` and `user:{uid}:fills` channels, so it needs a valid token whose uid
matches the path.
The important subtlety is that "no token" and "bad token" are **different answers**. A token that
*is* presented runs the same check as the REST API — valid signature, correct type, not
blacklisted, user active, bound to a live session — and a failure closes the socket. Without that
distinction, revoking a session would just downgrade it to anonymous instead of ending it.
(`?token=` is only honoured when `WS_ALLOW_QUERY_TOKEN=true`, **off** by default — a token in a URL
ends up in proxy logs, history and `Referer`. On a public socket an ignored query token simply
means "anonymous"; on the private one it means "refused".)
→ `docs/auth-and-security.md` §10.

**F9. Why does the front end reconnect with backoff?**
**Answer:** Server restarts drop every socket at once. Reconnecting instantly would create a
thundering herd, so the delay grows exponentially (capped at 30 s), and React Query refetches REST
state on reconnect so nothing on screen is stale. It also **stops after 8 consecutive failures**
(~2 min of trying) instead of retrying for the lifetime of the tab, and recovers on `online` or tab
focus — a parked socket would otherwise spam the API log with identical handshake rejections, and
`online` is the only signal the browser gives you when a laptop wakes from sleep.
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

**★ F19. Why one WebSocket per tab instead of one per market?**
**Answer:** Because the socket is a *subscription to the bus*, not to a market. One socket per market
sounds fine until you count the homepage: two carousels of eight cards each, and every card
subscribes — that's 16 markets, plus the trade ticker. A socket per market means 17 connections to
render one list page. And that's not just wasteful, it **breaks**: the server caps connections at 50
per IP, so three people sharing an office or a university NAT would exhaust the cap and the fourth
would be refused. It also burns a file descriptor, a keepalive timer and a TLS handshake per card,
and competes with REST requests for the browser's per-origin connection budget.

So the client holds a **module-level singleton** — one socket per browser tab — and multiplexes
markets over it with `subscribe`/`unsubscribe` frames. A component asks for a market and gets back
an unsubscribe function; the socket is shared. The server side confirms this was the intended
shape: it's built to multiplex, with 50 subscriptions allowed per socket and its fan-out registry
keyed market→sockets so delivering to a market only touches that market's subscribers.

The last subscriber to leave is what closes the connection — and that close is deferred by one tick,
because React's Strict Mode remounts components in development and a registry that briefly empties
would otherwise close and immediately reopen the socket on every page.
→ `docs/docker-concurrency-realtime.md` §D7.

**★ F21. How do you stop a dead WebSocket from leaking?**
**Answer:** A scheduled heartbeat sweep that pings every socket and disconnects whatever doesn't
answer within the send timeout. The interesting part is *why that has to exist at all*, because the
obvious detection — "a failed send means a dead socket" — is wrong twice over. A TCP connection can
die without the server ever seeing a FIN: a closed laptop, a NAT timeout, a killed container. The
socket still looks open. And sending to a half-open socket *succeeds*, because it only fails once
the kernel buffer finally overflows — so a successful send is not evidence the client is alive.
Which means broadcast-failure detection only ever reaps sockets on markets that actually trade, and
a socket watching a quiet market leaks forever. Each leak holds a file descriptor and a slot in that
IP's connection counter, which slowly locks real users out.

So there's a 30-second sweep in the app lifespan, cancelled cleanly on shutdown. It re-raises the
cancellation error rather than swallowing it — swallow that and the task becomes uncancellable and
the process hangs on exit — and wraps the body in a broad `except` so one bad socket can't kill the
loop whose whole job is cleaning up bad sockets. Three tests pin it: a hanging send gets reaped, a
responsive socket is **not** reaped, and the lifespan actually schedules the loop. That last one is
the real regression test, and I verified it by reverting the wiring and watching the test fail.

**★ F22. Is 50 connections per IP actually the limit?**
**Answer:** No, and I want to be precise about this because it's the easy thing to get wrong. The cap
is enforced per *process*, on an in-memory counter. With eight gunicorn workers the effective ceiling
is up to eight times fifty — 400 connections from one IP, not 50.

That's deliberate. A global counter means a Redis round-trip on every connect *and* every disconnect,
and worse, a counter that leaks when a node dies would lock a user out permanently — which is exactly
the bug that once locked users out at five connections after an unclean socket death. So the per-process
cap stays: it's fast, it has no dependency, and it cannot strand a user. And now that there's a
`ws_connections` gauge, the true fleet-wide number is observable rather than something you have to
derive by hand. If abuse ever became a real problem I'd move to a Redis-backed counter with a TTL so
it self-heals — but I wouldn't do that on speculation.
→ `docs/docker-concurrency-realtime.md` §D4, §D10.

**★ F23. How do you know how many WebSocket connections you're holding?**
**Answer:** Prometheus gauges, per worker: `ws_connections` and `ws_subscriptions` for the current
number, plus counters for connects by outcome, disconnects by cause, sends by result, and fan-out by
channel class. Before this there were exactly two collectors and both were HTTP, which made the
headline capacity claim — the 50k-connection story — completely unmeasurable. You can't claim headroom
you can't observe.

The detail I'd volunteer is the send result split, because "timeout" and "failed" mean different
things operationally: a timeout is a *wedged* client with a full TCP buffer that is still connected,
while a failure is genuinely dead. And the subtle implementation trap is that the gauges must only
decrement for sockets this worker actually counted — a socket can reach the disconnect path that was
never registered, and decrementing for it drives the gauge negative, which is worse than no metric at
all, because a negative gauge reads as "we have headroom" when the opposite is true. Registration is
captured before the registry is popped for exactly that reason.
→ `docs/docker-concurrency-realtime.md` §D10.

**★ F25. You said the heartbeat reaps dead sockets. Did you check it actually does?**
**Answer:** Yes — and checking found three bugs in my own fix, which is the honest way to answer it.
The first version swept only market sockets, so notification sockets were never pinged; those live
in a separate manager, and they're the long-lived per-user ones, so it leaked for exactly the case
the heartbeat was meant to cover. The second version pinged sockets *sequentially*, which at a
two-second timeout means fifty wedged sockets take a hundred seconds against a thirty-second
interval — the sweep would take longer than its own period and pile up. And the third was a test
that passed for the wrong reason: calling the user sweep directly proves that sweep works, but says
nothing about whether the combined sweep calls it, so deleting that line left the test green.

All three are now pinned by tests I verified by sabotage — I made each defect deliberately, watched
the specific test fail, then restored the file and diffed to confirm nothing was left behind. That's
how I'd want anyone to check my work, and it's the only reason I'm confident these three are the
last three.

**★ F26. So what's the lesson from that?**
**Answer:** The bugs were all found by asking what the code does *when it runs*, not by reading it
closely. The method I found first — a working, tested function that nothing called — is precisely
the failure mode unit tests are worst at catching: every test passes and the feature is simply
absent. A green suite tells you the parts that are exercised behave correctly; it says nothing about
whether anything exercises them, or whether the thing you wired up covers every registry. That's
also why I now include one test that asserts the *wiring* — that the lifespan schedules the sweep —
because that assertion is the one that would have caught the original dead code.

**★ F24. What's a bug you'd call subtle, and how did you find it?**
**Answer:** The one I'd pick is in the client mutex. The original per-market lock was a spin-wait —
"while locked, sleep five milliseconds and check again". It worked, which is why it survived: it only
costs a timer when two components race on the same market, which is rare in development. But it burns
a timer per contended market and occupies the event loop while it waits, and under a burst of
subscribe/unsubscribe that's exactly when you can least afford it. Replacing it with a promise chain
was straightforward — chain onto the previous promise rather than polling.

The subtle part wasn't the mutex, it was the "improvement" I nearly made alongside it. The obvious
tidy-up is to guard the subscribe frame with "only send if the socket is actually open". That would
have been a **new bug**: if a second market is subscribed while the socket is still connecting, the
send correctly no-ops — but the market still has to be recorded, because the `onopen` handler replays
that recorded set. Returning early drops that market permanently, and the socket URL only ever names
the *first* market, so nothing would ever re-add it. The lesson is that "the socket isn't ready, skip
it" is wrong whenever something later is responsible for replaying your intent. I caught it by
reading what `onopen` actually replays before I trusted the guard.

**F20. How do you add a *new* market to a live socket?**
**Answer:** Send `{"type":"subscribe","market_id":"..."}`. The server adds it to the socket's
subscription set under that socket's lock, and the market's reverse index under that market's lock —
deliberately not both under one lock, because holding two socket locks at once is how you deadlock.
Then the server subscribes to the Redis channel for that market so this process can be woken when it
moves. The unsubscribe path is the mirror, and it deletes the market's index entry entirely when the
set empties, rather than leaving a zero-length one behind — that leak once locked users out
permanently at 5 connections after an unclean socket death.
→ `docs/docker-concurrency-realtime.md` §D3, §D4.

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
login/verify/reset; 3 per minute for resends and registration; 30 per minute per IP for silent
token refresh; 10 per minute for strict endpoints.
They're sliding windows computed in Lua on Redis, so counts are exact. After 5 failed attempts
there's progressive friction — 1s, 2s, 4s, 8s, 16s — then a 15-minute lockout that clears on a
successful login.
Refresh gets its own bucket on purpose: the 3/min cap is sized for endpoints that send an email or
reveal whether an account exists, and a signed-in client rotating its token does neither. Sharing
that cap meant a burst of 401s — a flaky network, a laptop waking from sleep, several components
refetching at once — locked the user out of recovering their own live session.
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
Then alerting on the invariant violations the nightly escrow audit already emits (today they
only reach a log file), then depth: deeper liquidity and an LP position that isn't just a number
in a dropdown. Accounting and the refresh-chain cap are done, which is why they're not on this
list.
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
Honest caveat to volunteer: settlement is all-or-nothing — it adds up the entire obligation first
and aborts if the escrow can't cover it, so nobody is ever paid partially, but the market stays
`resolving` until someone funds it or the worker retries. The nightly audit re-checks every pool
against its open claims so drift surfaces at 4am rather than at resolution — but it only writes
`ERROR` lines to a log file that nobody watches, which is the honest weakest part of this setup.
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
→ `docs/trading-engine.md` §6 ("Known limitations").

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
accounting: the escrow now holds every inflow and pays every outflow, an LP exit is floored by
open claims, settlement pre-flights the whole obligation before paying anyone, and a 4am job
re-checks every pool against `max(open YES, open NO)` + fees. What that last part can't do is
*repair* anything or tell anyone — it writes `ERROR` lines to a log file, and a detection nobody
is paged for is only as good as someone reading that file. Both are in `docs/trading-engine.md` §6.
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
**Answer:** Depth, and the confidence that comes with being able to watch it. The pool is thin — one
$10 order in a $100 market moves the price seven points. The accounting is in much better shape
than when this answer led with a broken ledger: the escrow holds every inflow and pays every
outflow through one choke point, LP exits are floored by open claims, settlement refuses to
underpay anyone, and a 4am job re-checks every pool's escrow against what it still owes. But that
job's findings go to a log file nobody tails, and nothing repairs a violation automatically. So my
weakest link is now *observability*, not correctness. Both are in §6 of the trading doc and I'd
volunteer them before being asked.
→ `docs/trading-engine.md` §6.

**★ M2. What did you learn the hard way?**
**Answer:** Pick one you can tell properly. My favourite: the AMM used to charge the pre-trade price,
so buy-then-sell returned 11.8% more than you put in — a genuinely drainable pool that only a
round-trip test exposed. Others: trade rows silently disappearing because a buy's `remaining_shares`
was set to zero, and wallet deadlocks solved by sorting user IDs.

**★ M3. If you had another month?**
**Answer:** In order: frontend tests (the only empty test layer), then actually *alerting* on the
nightly invariant audit instead of only logging it, then deeper liquidity and a real LP position
with a P&L view, then cross-node sharding for the WebSocket registries, then the observability
metrics.
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
  funds when the market closes. Honest thing to volunteer if asked about this area: the resting
  branch used to return before the commit, so the order and its locked funds were rolled back —
  resting orders did not actually exist until it was fixed, and it survived because the API
  session could read its own uncommitted writes. A test using a *rollback* as the discriminator
  caught it; using the request session never would have.

* **"How do you know two concurrent buys don't corrupt balances?"**
  → `backend/tests/test_concurrency.py` fires parallel orders and asserts the invariants, plus the balance check
  `balance − locked ≥ required` runs while both wallets are locked.

* **"What's the hardest bug you fixed?"**
  → The AMM round-trip exploit — buy then sell returned 11.8% more than you put in, so the pool could
  be drained. Fixed by charging the post-trade price, with regression tests that fail if anyone
  reverts it.

* **"What's a thing you knowingly left wrong?"**
  → No frontend test suite at all, a thin AMM with linear impact, and an invariant audit whose
  findings only ever reach a log file nobody tails — all listed in `trading-engine.md` §6 and
  `auth-and-security.md` §12. The three that used to be the answer here (single-entry ledger,
  register email enumeration, uncapped refresh chains) are fixed and tested; naming what's *still*
  wrong yourself is the answer.

## O. Database & data model

**★ O1. How many tables, and what are the main groups?**
**Answer:** 24 tables in five groups. **Identity** — users, refresh tokens, sessions. **Markets** —
markets, outcomes, FAQs, flags, disputes, price history. **Trading** — liquidity pools, LP shares,
orders, positions, trades. **Money** — wallets, transactions. **Platform** — comments, alerts,
notifications, notification preferences, referrals. Plus the governance pair, treasury and treasury
logs, and the auth audit log.
→ `docs/data-model.md`.

**★ O2. What does your database actually *guarantee*, versus what does your code guarantee?**
**Answer:** The database guarantees identity and uniqueness (UUID keys, one position per user per
market per outcome, one order per idempotency key), ranges (an order's price must be 0 to 1, amount
above zero, positions non-negative), and idempotency — two partial unique indexes enforce one
withdrawal per key and one deposit per Stripe payment intent. What it does **not** guarantee is money
conservation: the pool's collateral column has no CHECK constraint, so "the escrow always covers what
it owes" is enforced by our service code and re-verified by a nightly audit. And to be honest, five
CHECK constraints I wrote in the models are missing from the migrations, so on a real database
negative wallet balances are prevented by code rather than by Postgres. I'd fix that first.
→ `docs/data-model.md` §5, §8.2.

**O3. Why is `price <= 1` a database constraint?**
**Answer:** Because it's the schema's structural statement of what this product is. A share settles at
exactly $1, so a price above $1 could never be profitable — the constraint makes an impossible state
unrepresentable rather than validating it at the edge. It's the cheapest possible guard against a bad
decimal ever entering the book.

**O4. You have no database enums at all. Why not?**
**Answer:** Deliberate. Every status, side, order type and event type is a plain string with the
allowed values recorded in code. The comment in the market model says it plainly: the values are "a
contract enforced by the API/service layer." The trade-off is that a bad write via raw SQL or a psql
session isn't caught; the benefit is that adding a status is a code change, not a migration — no
`ALTER TYPE`, no enum-ordering gotchas, no "cannot drop a type still in use". The one place I *do*
enforce a value in the database is the treasury's singleton flag, because there the constraint is what
makes the singleton actually hold.

**★ O5. What's the most interesting constraint in the schema?**
**Answer:** The treasury singleton, because it's two constraints doing one job. A CHECK forces
`singleton = true` on every row, and a UNIQUE constraint allows at most one row holding that value.
Individually neither is enough — the CHECK alone allows a thousand identical rows. Together they make
the table structurally zero-or-one rows, with no application code involved at all.
→ `app/models/treasury.py:18-22`.

**O6. Explain the partial unique indexes on transactions.**
**Answer:** There are two, both unique on `reference_id`, but each with a `WHERE` clause — one for
withdrawals, one for deposits. So the database allows exactly one withdrawal per idempotency key and
exactly one deposit per Stripe payment intent, while ordinary rows with no reference are untouched.
Because `NULL`s are excluded by the predicate, that exclusion is what makes it work: it stops
unrelated transactions colliding on a null reference. This is the deposit webhook's
double-delivery guard living in the schema rather than in application code.
→ `app/models/wallet.py:45-56`.

**O7. Why is `positions.settled_at` a number and not a timestamp?**
**Answer:** It stores a Decimal UTC timestamp, but it's used as an idempotency sentinel rather than a
date. `NULL` means unsettled; any value means settled. It's the guard that stops `claim_winnings`
paying the same position twice, and it's tested with `IS NULL` in the query, which is why the index
on it matters. I did leave it out of the API response, which was a mistake — a client can't tell a
claimed position from a pending one.

**O8. What stops the pool's collateral going negative?**
**Answer:** Not the database — there's no CHECK on it. It's `debit_collateral`, which raises an
`EscrowShortfallError` rather than partially paying. That exception is deliberate: there is no "pay
what you can" mode, because a partially-paid obligation would stay claimable forever with nobody
tracking it. And settlement pre-flights the whole arithmetic before touching a single wallet, so a
shortfall aborts the entire payout instead of leaving the last winner with scraps.
→ `app/models/liquidity.py:73-97`, `app/workers/tasks.py:834-873`.

**O9. How do you stop a user claiming winnings twice?**
**Answer:** Two independent layers. In the database, a guarded update selecting only unsettled
positions, plus a re-check inside the payout loop as defence in depth against the self-service claim
endpoint. At the application level, a Redis marker per market written only *after* the settlement
commits — and the "only after" is the important part, because the old code set the market status
before the worker ran, which meant a status-based guard skipped every settlement.
→ `app/workers/tasks.py:743-752, 877-879`.

**O10. How is full-text search on markets indexed, and why is it an expression index?**
**Answer:** It's a GIN index on `to_tsvector('english', question)`, not on the plain column. The reason
is in the code comment: Postgres has no default GIN operator class for varchar or text, so a plain
GIN index on `question` can't be created at all. The index has to match the exact expression the
query uses. And `'english'` is wrapped in `literal_column` so it renders as a literal the planner can
match, rather than a bind parameter it would refuse to equate.

**★ O11. Tell me about an inconsistency you found between your models and your migrations.**
**Answer:** Five CHECK constraints — three on wallets, two on markets — exist in the model files and
are absent from the migrations, so a database built from `alembic upgrade head` doesn't actually have
them. You can verify it in thirty seconds: grep the migrations for `CheckConstraint`, then grep for
`ck_wallets` and `ck_markets`, and they only appear in the models. There's also a renamed constraint on
the treasury and a leftover server default on `transactions.confirmations`. It happened because the
initial migration got hand-edited to add indexes, and the constraints weren't included in that
reconciliation.
→ `docs/data-model.md` §8.2.

**O12. Which is the source of truth — models or migrations?**
**Answer:** Migrations, and that was deliberate. `create_all` is never called anywhere, startup only
inspects and warns, and the test suite drops and rebuilds the database from `alembic upgrade head` on
every run so a stale schema can't mask a failure. The awkward part is that the migration path
currently produces a *weaker* schema than the models, while `create_all` would produce a stronger one
on checks but miss the partial unique indexes. Neither path alone is right, which is exactly why I'd
write a migration to close the gap.

**O13. What is the lock order, and why is it fixed?**
**Answer:** Market, then pool, then wallet, then position, then LP shares, then orders — and wallets
are locked sorted by id, so two transactions can't deadlock locking the same pair in opposite orders.
It's enforced by convention at every call site rather than by a shared helper, which is the weak
point: a new developer could write a service that violates it and nothing would stop them. A shared
`acquire_locks_in_order()` helper is the fix.
→ `docs/docker-concurrency-realtime.md` §B.

**O14. Explain `Numeric(20,8)` versus `Numeric(10,6)`, and why the scales differ.**
**Answer:** Money and share quantities are `Numeric(20,8)` — 20 digits of range, 8 decimal places,
which comfortably fits a USDC balance. Prices are `Numeric(10,6)` on orders and positions. But trades
and alerts use `Numeric(10,8)` — a different scale for what is conceptually the same price. It works
because Postgres numeric is exact, but it's an inconsistency I'd normalise. Critically, these are
never floats in storage: a float can't represent 0.1 exactly, and money that's off by a ten-thousandth
per operation becomes a real loss over millions of rows.
→ `docs/data-model.md` §4.1.

**O15. How do you keep a user's balance from being spent twice?**
**Answer:** Wallets carry two numbers: `balance`, and `locked_balance`, which is money reserved for a
resting limit order but still sitting inside `balance`. Spendable is `balance − locked_balance`, and
every buy path checks that expression rather than `balance`. Checking `balance` alone would let a user
place a resting order and then spend the same money on something else. The database also has a CHECK
that `locked_balance <= balance` — but see O11, that's one of the ones missing from the migrations, so
the application check is what actually protects this today.

**O16. Do you use read replicas?**
**Answer:** The architecture supports them — there are two engines and a `get_db_replica` dependency
that every read endpoint uses, and it falls back to the primary when the replica URL is empty, so it
works correctly with zero extra infrastructure. No replica is deployed yet. The same pattern holds for
Redis Sentinel: the code supports master-for-read failover, but no Sentinel service exists in the
compose files. Both are configuration, not code changes.

**★ O17. How do you avoid N+1 queries, concretely?**
**Answer:** Three techniques depending on the shape. For a list endpoint, batch with `IN (...)` and
index the results in Python — the positions endpoint does markets, outcomes and pools in three queries
instead of three per row. For reply counts, one grouped aggregate over all the parent ids instead of a
query per comment. And for "top N per group", a window function — `row_number() OVER (PARTITION BY
outcome_id ORDER BY shares_held DESC)` gives every outcome's leaderboard in a single pass. Whenever
you'd otherwise write "the top N per group", that's when you reach for a window function.
→ `docs/platform-features.md` §1.3, §9.2.

**O18. What's a self-referencing foreign key, and where do you use one?**
**Answer:** Comments: `parent_id` points back at `comments.id`, which is what makes threading possible.
In the ORM it needs disambiguating — a `remote_side` on the many-to-one side, and the relationship is
assigned after the class body rather than inside it. The application caps nesting at depth three, but
the `depth` column has no CHECK constraint, so that cap is ours to enforce, not the database's.

**O19. How would you add a new field safely?**
**Answer:** A migration, never `create_all` — add the column as nullable (or with a default), deploy
the code that tolerates both shapes, then backfill and tighten. The reason it's a migration rather than
a model edit is that production's schema is owned by the migration chain; changing a model alone would
make autogenerate want to drop and recreate constraints forever, which is exactly the drift in O11.

---

## P. Background jobs, caching, rate limits & monitoring

**★ P1. What runs in the background, and how often?**
**Answer:** Eight scheduled jobs. Every 30 seconds: expiring stale orders, and the resting-limit-order
sweep. Every 60 seconds: syncing AMM prices into Redis. Every 5 minutes: closing markets past their
close date, and writing price-history snapshots for the charts. And three nightly jobs in a deliberate
order — 3am cleans up expired sessions, 3:30am sweeps protocol fees, and 4am re-audits every pool's
escrow, *after* the fee sweep, so the audit checks post-sweep state rather than numbers that are about
to change.
→ `docs/background-jobs.md` §1.4.

**★ P2. What happens if a background job runs twice?**
**Answer:** Every task has an idempotency guard, because Celery gives at-least-once delivery. Three
different styles. Settlement uses a Redis marker per market, written only after the commit. The
price-history snapshot uses a minute-window dedup — it computes the current minute floor, selects
which market-and-outcome pairs already have a row in that window, and skips them. And order expiry
uses its predicate itself as the guard: re-running matches nothing, because the rows are now `expired`.
If you're relying on "the row is already updated, so it won't match again", that only works if the
predicate excludes the new state — worth checking every time.
→ `docs/background-jobs.md` §2.

**★ P3. How does Celery know a task really finished?**
**Answer:** Two settings together. `task_acks_late` means the message is acknowledged after the task
runs rather than when it's received, so a worker dying mid-task returns it to the queue. And
`task_reject_on_worker_lost` means Celery re-queues instead of acknowledging when a worker vanishes.
Without the second one, the late acknowledgement is lost and the task disappears. Together they give
at-least-once delivery, which is only safe because of P2. I also set prefetch to 1 so one slow task
can't hoard the queue, and capped worker concurrency at 4 because separate processes mean separate
database connection pools.

**P4. Why isn't your dead-letter queue working?**
**Answer:** It's configured — I declared the RabbitMQ dead-letter exchange and routing key on the
queue, and a two-hour visibility timeout so a long settlement has room. But production runs Redis as
the broker, and dead-lettering is a RabbitMQ feature, so those arguments are inert. The code comment
says so explicitly. Moving the broker URL to RabbitMQ activates it with no code change. That's the
honest version: configured, documented, and not actually running.
→ `docs/background-jobs.md` §1.3.

**★ P5. Walk me through the resting-limit-order sweep.**
**Answer:** Five steps. First, skip markets that haven't moved — the price sync adds them to a Redis
set, and popping it tells us which to look at. That pop returns `None` on error rather than an empty
list, so a Redis outage triggers a full scan instead of silently doing nothing. Second, lock in a fixed
order — market, pool, wallet, order, position. Third, per-order, re-lock the order by id and re-check
its status, so an order already filled by another path is skipped; that's the over-matching guard.
Fourth, group by market with a try/except per group, so one bad market can't abort the run, and commit
at each boundary to release locks. Fifth, do the fill: check available balance as balance minus
locked, move the money, credit the pool, update or upsert the position, write the trade and transaction
rows. Then re-arm the sweep — but with `SET NX EX 1`, so fifty fills in one tick cause one enqueue,
not fifty.
→ `docs/background-jobs.md` §2.1.

**P6. Why does the price-sync task skip publishing tiny price changes?**
**Answer:** Because it only publishes when the price moved by more than one ten-thousandth. Without
that threshold, a market whose price is essentially flat still pushes an update every minute to every
subscriber, and each one causes a chart redraw on every open tab. It's an explicit anti-fan-out
measure that costs nothing in accuracy, because a change that small isn't visible anyway.

**★ P7. What does the nightly escrow audit actually check?**
**Answer:** Five invariants across every pool, at a cost of three queries total regardless of how many
markets exist — because it aggregates in SQL and interprets in Python. It checks for a missing pool with
claims outstanding, fees exceeding escrow, negative collateral, LP token supply drift where the issued
tokens exceed the recorded supply, and the big one: escrow below obligations. That last check compares
the *larger* of the two open sides plus fees against the collateral — not the sum of both sides. The
detail matters: at resolution only one side is paid a dollar a share, so the worst case is the bigger
side. It mirrors the settlement pre-flight exactly, and that's what makes a clean audit meaningful.
→ `docs/background-jobs.md` §3.3.

**P8. Does the audit fix anything it finds?**
**Answer:** No, and that's deliberate. It only logs — structured, machine-parseable events you could
alert on. The reasoning is in the docstring: a repair written by something that doesn't fully
understand the drift is how a rounding bug turns into a loss. There's even a test asserting a healthy
pool reports zero violations, so the audit can't cry wolf. The honest weakness is that nothing watches
it — a violation is detected nightly and then sits in a log file. That's the first thing I'd add.

**P9. How does your caching work, and how do you invalidate?**
**Answer:** Cache-aside with tag sets. Alongside each cached value there's a Redis set holding the
names of every key with that tag, so invalidating a tag means reading the set and deleting the members.
Without it you'd have to track "which keys belong to this market list" somewhere, which is the same
problem one level down. The tag sets expire ten seconds after their members, so the index outlives what
it indexes. Every invalidation is wrapped, so a failed cache delete can't fail the trade that
triggered it.

**P10. What's your weakest spot in caching?**
**Answer:** No stampede protection. If a hot key expires under load, every concurrent request misses at
the same instant and they all recompute it. The fix is a per-key mutex — a `SET NX` lock so one
request rebuilds while the others wait or serve stale — and ideally a Lua unlock that verifies the
owner, because a naive delete can release someone else's lock. I didn't build it; the ten-second tag
grace is all I have.

**P11. How does the orderbook cache handle units?**
**Answer:** The aggregated order rows come back with bid remainders and ask remainders in *different*
units — a resting buy stores its remaining amount as a USDC budget, while a resting sell stores
shares. So the code divides bid remainders by their price, making both sides quote size in shares. Miss
that and bids render as roughly a hundred times too large in the chart. It's the same units trap as the
trading document describes, showing up in a different place.

**★ P12. How do you stop someone brute-forcing a password?**
**Answer:** Three layers. A sliding-window rate limit of five per minute on login, keyed by email and
IP together — keying by IP alone lets one attacker lock out a whole office, keying by email alone lets
them target one victim, so it's the pair. Progressive friction on top: five free attempts, then an
exponential delay doubling up to sixteen seconds, then a fifteen-minute lockout. And bcrypt at cost
twelve, about a hundred milliseconds, so every attempt is expensive for the attacker. Login failures
are audited with four distinct reasons — unknown user, wrong password, missing 2FA code, wrong 2FA code
— so you can tell a brute-force pattern from someone who forgot their password.
→ `docs/auth-and-security.md` §5.

**P13. Why implement the rate limiter in Lua?**
**Answer:** Because trim, count and insert have to be atomic. With a pipeline, a concurrent request
could read the count before my insert landed, and two requests could both see "one slot left" and both
be admitted. Redis runs a script as one indivisible step. It's a sorted set rather than `INCR` plus
`EXPIRE` because a fixed window lets a client send double the limit across a window boundary — sixty in
the last second of one minute, sixty in the first second of the next. And each sorted-set member
includes a random suffix, because two requests in the same millisecond have to be two members or the
second overwrites the first and the count is wrong.

**P14. What's a detail in the rate limiter most people miss?**
**Answer:** IPv6 normalisation. A single subscriber is normally handed an entire /64, so a client could
rotate through billions of addresses and never hit its own bucket. I collapse the address to its /64
prefix before using it as a key. Also worth knowing: the auth buckets are keyed on email-at-IP as a
single string, which is why the key looks like `rl:auth:user@example.com@10.0.0.1`.

**P15. When does your rate limiter fail open, and when does it fail closed?**
**Answer:** Deliberately different, and each site documents why. The plain check fails **closed** — if
Redis is unreachable, requests are denied — because a limiter that fails open isn't a limiter. The
progressive-friction check fails **open**, because you don't want a momentary Redis blip locking every
logged-in user out of their own account. The principle is fail closed on security decisions, fail open
on convenience, and be explicit about which is which.

**P16. You have rate-limit settings in your config that do nothing. Why?**
**Answer:** `rate_limit_per_ip` and `rate_limit_per_email_ip` are declared in the settings class but
nothing reads them — the real numbers are a hardcoded table in the rate-limit service. So changing those
environment variables has no effect, which is genuinely misleading for whoever operates this. They
should either be wired up or deleted.
→ `docs/background-jobs.md` §5.6.

**★ P17. Tell me about the Redis circuit breaker.**
**Answer:** States are closed, open, half-open; it opens after five consecutive failures and lets one
probe through after thirty seconds. Two implementation details I'd point at. First, it takes its lock
only to inspect or change state and **releases it before the network call** — holding a lock during the
I/O would serialise every Redis user behind one slow call, which is the exact problem a circuit breaker
exists to reduce. Second, it records the failure state *before* re-raising the exception, so a second
caller in the same event-loop iteration already sees the breaker open. The naive version records it
after returning, and a whole burst gets through.
→ `docs/background-jobs.md` §6.3.

**P18. Why does your Redis client check which event loop it's on?**
**Answer:** Because an async connection pool is bound to the loop that created it. With eight Uvicorn
workers, plus pytest, plus Celery's per-thread loops, all potentially in one process, reusing a
module-global client across loops produces "Future attached to a different loop" errors. So `get_redis`
compares the running loop's identity and rebuilds the client if it changed, closing the old one. That
check is what makes the global safe.

**P19. How would you know the system is unhealthy?**
**Answer:** Three things. Prometheus counters and a latency histogram, labelled by route template rather
than raw path — reading the route after the handler runs, which keeps IDs out of the labels so
cardinality stays bounded. One structured JSON log line per request with a request id, and header
values deliberately never logged because header dumps leak cookies and authorization. And three health
endpoints: liveness that checks nothing, readiness that checks Postgres and Redis and returns 503 when
degraded, and the metrics endpoint.
→ `docs/background-jobs.md` §7.

**P20. Why must liveness not check the database?**
**Answer:** Because then a database outage would fail liveness, the orchestrator would restart every API
process, and the outage gets worse — you lose every warm connection pool and add restart churn to an
already-broken system. Liveness should only ask "is this process wedged?" Readiness asks "can it
serve?" and only readiness should gate traffic. Keeping those separate is the difference between a
dependency outage and an outage plus a stampede.

**P21. What's your request id, and why validate the incoming one?**
**Answer:** We accept an `X-Request-ID` if it matches a strict pattern — alphanumerics, dash and
underscore, at most 64 characters — and generate a UUID otherwise, then echo it back so a user can
quote it in a support ticket. The validation is the point: without a character and length cap, a caller
could inject newlines or megabytes into your logs, or forge someone else's request id. I trace it into
the rate-limit identifiers and the logs, so one id ties a rejection to its log line.

**★ P22. Why is your middleware in that order?**
**Answer:** Because Starlette's `add_middleware` inserts at the front, so the last one added is the
outermost — which means declaration order reads backwards from execution order, and getting it wrong is
invisible in review. The execution order is: correlation id first, so everything downstream can cite
it; then throttling, so oversized bodies and cross-origin writes are rejected before any database or JWT
work; then request logging, because it needs the id and the user and must read the final status; then
metrics, so rejected requests are still counted; then security headers, inside rate limiting so headers
reach the 413 and 429 responses too; and CORS innermost, so a layer above can return a bare JSON
response without CORS mangling it.
→ `docs/background-jobs.md` §8.1.

**P23. Why does your rate-limit middleware return a response instead of raising an exception?**
**Answer:** Because of where the exception handlers live. Starlette's catch-all handler belongs to the
server-error middleware, which is the outermost layer — outside all user middleware. The normal
HTTP-exception handlers sit *inside* the whole user stack. So an exception raised from the outermost
user layer would bypass the error-envelope handlers entirely and produce a response the frontend can't
parse. Returning a ready-made response sidesteps that.

**P24. What happens at startup, and which failures are fatal?**
**Answer:** In order: configure logging, clear stale metrics files, optionally start Sentry, then fail
fast if any of the JWT secret, the app secret or the TOTP encryption key is still the placeholder — the
app refuses to boot with a known-public secret. Then it warns if production has no trusted-proxy list,
and warns in development that the token blacklist fails open when Redis is unreachable. Then it waits up
to sixty seconds for Postgres and Redis, because Docker's dependency ordering only covers initial
startup, not a dependency that dies later. Then it checks the schema is present but never alters it —
migrations own the schema. And Redis pub/sub failing is only a warning, so the API still serves REST
without realtime.
→ `docs/background-jobs.md` §8.

**P25. What would you add to make this observable enough?**
**Answer:** Three things, in order. Alert on the escrow audit's violation events instead of only
logging them — the structured log is already machine-parseable, so it's a query away. Add a beat leader
election, because two beat instances fire every periodic task twice and right now only task
idempotency protects us. And propagate the request id into Celery task headers so a user-reported
problem can be traced from the HTTP request through to the settlement task that handled it.

---

## Q. Frontend

**★ Q1. What's your frontend stack, and why?**
**Answer:** Next.js 16 with React 19 in a Turborepo monorepo using Bun, with TanStack Query for server
state and Tailwind v4 for styling. Two workspace packages: the app, and a shared UI package. The
decision I'd defend is that the UI package has **no build step at all** — it's consumed as raw
TypeScript source through Next's `transpilePackages`, so there's no watch process, no dist folder, and
no build cache to invalidate.
→ `docs/frontend.md`.

**★ Q2. How is auth stored on the client, and why is that a security win?**
**Answer:** Nowhere in JavaScript. The backend sets the access and refresh tokens as HttpOnly cookies, so
no script can read them — there is no localStorage, no sessionStorage, no `document.cookie` anywhere in
the app. That means an XSS injection cannot steal the session; it can only make requests as the user.
Compare a token in localStorage, where one line of injected script reads and exfiltrates it. The
trade-off is that the client can't check whether a session exists, so the app is explicitly *told* by
the endpoints that set cookies, and it tracks that in a small session-state machine.
→ `docs/frontend.md` §6.1.

**★ Q3. What happens when the client gets a 401?**
**Answer:** It tries to refresh, replays the original request once, then redirects to login. The
interesting part is that the refresh is single-flight — a module-level promise, so if ten requests all
401 at once they share one refresh call instead of firing ten. And the refresh treats a 401 or 403 as a
verdict that the session is gone, but treats a 429, a 5xx or a network error as *inconclusive* and backs
off for thirty seconds while preserving the current state. That distinction is the fix for a real bug:
previously an anonymous page view produced one refresh per 401 until the per-minute cap answered 429 and
the tab rate-limited itself. Conflating "session gone" with "server briefly unwell" logs your users out
during an outage.
→ `docs/frontend.md` §4.2.

**★ Q4. How does the WebSocket client work?**
**Answer:** One socket per browser tab, held in a module-level singleton rather than React state, with
many components subscribing to it. Subscriptions are per market, the URL is market-scoped, and
reconnects go to whatever market the user is currently looking at rather than the first one they
subscribed to.
→ `docs/frontend.md` §5.

**★ Q4b. Why one socket for the whole tab rather than one per market?**
**Answer:** Because a socket is a subscription to the *bus*, not to a market — and the count is what
proves it. The homepage renders two carousels of eight cards each, and every card subscribes: that's
16 markets plus the trade ticker, so 17 connections to draw one list page. That's not merely
inefficient, it **fails** — the server allows 50 connections per IP, so three people behind one
office or campus NAT exhaust the cap and the fourth is refused with a policy-violation close. Each
extra socket also costs a file descriptor, a keepalive timer, a TLS handshake, and a slot from the
browser's per-origin connection budget that REST requests need.

So a component calls `useMarketSocket({marketId})`, gets back an unsubscribe function, and the socket
is shared behind a module-level singleton. Adding a market sends a `subscribe` frame; the server
records it in two places — the socket's subscription set and the market's reverse index — and
subscribes this process to that market's Redis channel. The reverse index keyed market→sockets is
what makes fan-out O(subscribers to that market) rather than O(all sockets).

The detail I'd add unprompted: the teardown is deferred by one tick. React's Strict Mode remounts
every component in development, so a subscription set that briefly empties would close the socket and
immediately reopen it on every page render. Anything that re-subscribes on the next tick keeps it
alive.
→ `docs/docker-concurrency-realtime.md` §D7.

**Q5. Why can the WebSocket be anonymous?**
**Answer:** Because the data on it is public. Market prices are readable over REST without an account,
so the socket pushes exactly that and accepts an anonymous handshake — gating live prices behind a
login would deny them to logged-out visitors, who'd just see a static page. If the visitor does have a
session, the cookie rides along automatically. The important subtlety is on the server: a *missing*
token is anonymous, but a token that is present and invalid is rejected outright. Without that third
case, revoking a session would silently downgrade to anonymous instead of being refused.

**Q6. How does reconnection work?**
**Answer:** Exponential backoff — a thousand milliseconds doubling up to thirty seconds — capped at eight
attempts, about two minutes. The cap is deliberate: without it, an endpoint that's down gets retried for
the lifetime of the tab. There's also sleep-and-wake recovery, listening for the browser's online and
visibility-change events, because a laptop resuming from sleep drops the socket silently and those are
the only signals available. And the socket close is deferred by a zero-millisecond timeout, because
React's Strict Mode double-mounts in development and a registry that briefly empties would otherwise close
and immediately reopen.

**★ Q7. Tell me about a bug you fixed in the WebSocket client.**
**Answer:** Two, and they're the same mistake. Closing a socket is asynchronous, so a socket that had
already been replaced would fire its close event after its successor was live — and the handler nulled
the connection unconditionally, making the live socket untracked. The next subscribe then opened a second
socket: two sockets, both receiving, and the flap repeated on every subscribe cycle. The fix was to
compare identity — if this isn't the current socket, return. The second was a boolean flag meaning "this
close was intentional", which was shared across sockets, so a late close read a value its successor had
already reset; the fix was to store the socket identity instead of a boolean. Both teach the same lesson:
when lifecycle events can arrive out of order, compare identity rather than trusting a flag.
→ `docs/frontend.md` §5.5.

**★ Q8. Do you have frontend tests?**
**Answer:** No, and that's the honest headline. Zero test files, no test runner in any package manifest,
no test script, and no test task in the Turbo pipeline. The backend has 387 tests; the client has none.
The two highest-risk files here are the API client, with its refresh state machine, and the WebSocket
hook, with its reconnect and single-flight logic — and both are defended by dense comments explaining the
exact bug each section prevents, which is a reasonable substitute for tests but genuinely isn't
equivalent. The fix is to turn each of those comments into a test, starting with the two bugs I just
described.
→ `docs/frontend.md` §10.

**Q9. How do you keep the charting library out of the initial bundle?**
**Answer:** Every one of the nine dynamic imports in the app is server-render-disabled, so the visx and
d3 code splits into its own chunk and never renders on the server. The effect is that the detail page
paints text and orderbook first and the chart hydrates after. That's essential here because the chart
package is over a hundred and sixty files — though only four of them are actually used by the app, which
I'll come back to.
→ `docs/frontend.md` §8.1.

**★ Q10. You have a huge chart library but only use four files. Why?**
**Answer:** The design-system package carries sixteen chart families — candlestick, bar, area, radar,
sankey, sunburst, choropleth, heatmap, gauge, funnel and more — and the application imports exactly
four: the live line chart and its axis and line children. Everything else is fully implemented and
unexercised, including OHLC converters written specifically to feed the candlestick chart. It came in with
the design system. The honest version is that it's general-purpose scaffolding and the product currently
needs one of them, and shipping alpha visx packages in production dependencies for four components isn't
something I'd defend as a deliberate choice.
→ `docs/frontend.md` §7.3.

**Q11. Server components or client components — what did you choose?**
**Answer:** Overwhelmingly client: eighty of a hundred and forty-one files carry the client directive,
including every single one under the components folder. Only one server component actually fetches data
— the homepage, which runs three API calls in parallel on the server and passes them down as seeds, so
the first paint already has real markets. The reason for the lopsidedness is structural rather than
stylistic: anything touching live data, a query, or search parameters has to be a client component.

**★ Q12. What's wrong with your server-side data fetching?**
**Answer:** It doesn't forward cookies. The homepage reuses the client API wrappers, whose fetch carries
credentials, but Next.js doesn't forward browser cookies to a fetch issued from a server component — and
there's no cookies call anywhere in the app. So the server-rendered homepage data is effectively
anonymous. Harmless for the homepage, since it's public markets and trades, but it means the pattern
can't be reused for an authenticated route without adding explicit cookie forwarding. The related one: the
market detail page accepts no params and fetches nothing server-side, so it server-renders no market data
at all and its metadata is generic.
→ `docs/frontend.md` §3.2.

**Q13. How do you paginate on the client?**
**Answer:** Two styles, matched to what each backend endpoint supports. Offset pagination for markets,
positions and transactions; keyset cursors for the trade tapes and orders, because the backend is
cursor-paginated there and asking for a page number would just be ignored. The query-key factory
deliberately gives infinite and non-infinite variants of the same feed different keys, so invalidating
one doesn't accidentally wipe the other.

**Q14. Do you do optimistic updates?**
**Answer:** No, and for this product I think that's the right call. There is exactly one direct cache
write in the whole app and it's a WebSocket push, not an optimistic mutation. Everything else invalidates
after success. On a trading screen, a wrong optimistic balance is worse than a two-hundred-millisecond
wait, so I'd argue invalidate-after-success is the more correct choice here rather than a shortcut.

**Q15. How do you protect routes on the client?**
**Answer:** Three layers, and deliberately no route-guard component. The middleware — which in Next 16
is renamed to a proxy — validates the session and redirects to login with a next parameter. Second,
every private query is gated on the current user being loaded, so an anonymous visitor never fires a
request that would fail. Third, a 401 anywhere triggers the refresh-and-replay path, which skips
redirecting on public paths so an anonymous visitor gets an empty state instead of a redirect loop. The
`next` parameter is validated to start with a single slash and not a double one, which is the
open-redirect defence.
→ `docs/frontend.md` §2.1.

**★ Q16. What's in the Content Security Policy, and why does it matter most here?**
**Answer:** The connect-src directive is the critical one, and it's derived from the configured API and
WebSocket origins rather than hardcoded — because it must list every origin the browser talks to, or
fetch and WebSocket connections are silently blocked in production, which is a failure mode you only
discover after deploying. Alongside it: default-src self, object-src none, frame-ancestors none, and
form-action self. And on the server there's a much stricter policy for the API itself — default-src none,
form-action none — with an explicit exception for the docs pages, because under a deny-all policy the
Swagger bundle never loads and you get a blank page with a 200.

**Q17. Do you use Next's image optimisation?**
**Answer:** No, because there was nothing to optimise — there are no raster images in the app. The logo
and favicon are inline SVG, the social preview image is generated at the edge, and the two-factor QR code
is an inline SVG component. So I won't claim image optimisation as a feature.

**Q18. What's your accessibility story?**
**Answer:** Real rather than token. A skip link targeting a focusable main landmark, live regions for
async state so screen readers hear updates, `aria-current` on active navigation, and — the one I'm
proudest of — the WebSocket connection status is exposed as text, "Live", "Sync", "Off", not just a green
dot. The gap: charts are hidden from assistive technology with a text label on the wrapper giving the
current probabilities, but there's no data-table alternative, so a screen-reader user gets the summary and
not the series.

**Q19. Do you support multiple languages?**
**Answer:** No, and it's a non-goal rather than an oversight. There's no i18n layer, the language
attribute is hardcoded, and every string is an inline literal — including the terms of service, privacy
policy and FAQ. Adding a language would mean externalising every literal behind a message catalogue,
adding locale-aware routing and language negotiation, and parameterising the date formatters the charts
already use. The first thing I'd do is move the FAQ and legal copy into a content directory.

**★ Q20. Any content bugs in your own app?**
**Answer:** Two I'd rather raise than have you find. The FAQ tells users to "connect your wallet and your
account is created automatically" — but there is no wallet-connect code at all; the real auth model is
email and password with two-factor, and the very next FAQ answer describes it correctly. It's leftover
copy from a different product. And the old brand name still appears in five files, including the support
and legal pages, even though the frontend README claims that was swept.
→ `docs/frontend.md` §11.

---

## R. Platform features: moderation, disputes & fees

**★ R1. What stops an administrator from rigging a market resolution?**
**Answer:** A dispute window. An admin proposes an outcome, which puts the market into a dispute-window
state and starts a 48-hour clock. Any user can file a dispute with evidence during that window. An admin
then adjudicates, and a dispute can be ruled on exactly once. Settlement only runs after the window
closes without a successful challenge. So resolution isn't one person's decision — there's a timed,
evidenced, appealable challenge step in the middle.
→ `docs/platform-features.md` §6.

**★ R2. Why is the dispute window 48 hours, and what happens at the end of it?**
**Answer:** Forty-eight hours is long enough for an ordinary person to notice and react, short enough that
the market still settles promptly. At the end of the window, if nobody disputed, the resolution stands and
settlement is queued. The implementation detail I'd point at is that the market row is read with a row
lock while a dispute is filed, so two simultaneous filings serialise rather than both succeeding.

**R3. Why do you let people dispute an already-resolved market?**
**Answer:** On purpose. The status check accepts the resolving, resolved and dispute-window states. The
reason is that otherwise there'd be a gap: an admin could propose, resolve and settle so quickly that
nobody could ever dispute, making the window decorative. The code comment says exactly that. It also
means a null dispute deadline means "unbounded" rather than "expired", which is a subtle condition worth
knowing.

**★ R4. Why is settlement queued before the database commit?**
**Answer:** Because I inverted the usual order deliberately. Normally you commit and then dispatch a side
effect. Here the queue happens first, and if the broker is down we fail with a 503 *before* the database
records the market as resolved. A resolved market with no settlement ever queued is orphaned permanently
and nobody would ever retry it, whereas a 503 is recoverable — the client just retries. It's the same
principle as checking a precondition before committing an irreversible state.
→ `docs/platform-features.md` §6.4.

**★ R5. How are protocol fees actually accounted for?**
**Answer:** They accrue per pool, not in the treasury table — on each fill, one percent of the trade value
is added to the pool's protocol-fees column, and the pool also keeps a two percent trading fee for its
liquidity providers. The critical concept is that the protocol-fee figure is a *sub-ledger inside* the
pool's collateral, not extra money. So moving a fee out requires zeroing the claim and debiting the
backing dollars, in that order, and the debit is strict. And the real destination is a wallet belonging
to a system account, not the treasury table at all.
→ `docs/platform-features.md` §8.5.

**R6. What happens if the escrow can't cover the fees owed?**
**Answer:** The sweep pays what the escrow actually holds, keeps the unpaid remainder recorded, and logs
an error. The comment states the rule: never zero the record while handing over less than it claims, so
the next sweep retries it. That decoupling — record and cash move independently, and the record is never
cleared while cash is short — is the principle I'd point at.

**★ R7. Tell me about something in the treasury that's disconnected.**
**Answer:** The treasury table is effectively a manual accounting record. Nothing in the application ever
increases its balance or its collected-fees total — those are only set by the seed script — and the
documented "fee collected" log event is never written by any code path. The real fee flow runs entirely
through the system account's wallet. So the table is a useful record for an administrator, but it isn't
wired into the live fee movement. On a fresh install with no seed, the distribute endpoint correctly
refuses for insufficient balance.
→ `docs/platform-features.md` §8.6.

**R8. How do you guarantee there's only one treasury row?**
**Answer:** With two constraints working together rather than application code — a CHECK forcing the
singleton flag to true on every row, and a UNIQUE constraint on that same flag. Neither alone is
sufficient: the CHECK alone allows a thousand identical rows, and UNIQUE alone allows one row with the flag
false. Together they make the table structurally zero-or-one rows. There's also a race-free
get-or-create using insert-on-conflict-do-nothing rather than select-then-insert.

**R9. How do users report a bad market?**
**Answer:** A flag — reason text, five to a thousand characters. One flag per user per market, enforced in
the application rather than by a unique constraint, so a concurrent double-submit could create two;
that's a gap. Flags don't hide anything themselves — they're a queue for a human, and an admin resolves or
escalates them. Two weaknesses: the flag list for a market isn't paginated at all, and nothing notifies an
admin that a flag exists.
→ `docs/platform-features.md` §5.

**R10. What moderation powers exist?**
**Answer:** New markets arrive in a pending-review state — invisible publicly but readable by their
author — and an admin approves or rejects them, with a compare-and-set on the status so two admins can't
both win. Admins can also ban and unban users, list users, read the auth audit log, and trigger a
protocol-fee sweep. Worth being clear about what does *not* exist: there's no way to grant admin in the
API, no global pause or kill switch, no way to force-close a stuck market, and no audit record for
moderation decisions or any admin action beyond ban and unban.
→ `docs/platform-features.md` §7.

**★ R11. How do alerts avoid firing twice when several workers are running?**
**Answer:** Two independent guards. In Redis, the sorted sets are keyed by market, side and direction, so
"alerts due at this price" is one range scan, and a Lua script does the fetch and the removal together —
because the removal happens inside the script, exactly one worker can win a given alert. Then in the
database, an update guarded on "still not triggered" returns the rows that actually flipped, and only
those notify. Even if Redis lost the claim, the database still can't notify twice.
→ `docs/platform-features.md` §2.2.

**R12. Why is it acceptable for the alert index to be lost?**
**Answer:** Because it's an index, not the source of truth — Postgres holds the real state. The index is
written through on creation with a seven-day expiry, and if a claim comes back empty the engine rebuilds
the index from the database and retries once, so a cold index repairs itself on the first miss. There's
also crash recovery: if the worker dies between the Redis removal and the database commit, it reindexes
before re-raising, otherwise those alerts would be orphaned out of the index while still un-triggered in
the database.

**★ R13. What's in your audit log?**
**Answer:** Fifteen authentication event types — logins, registrations, password changes and resets,
two-factor setup, enable and disable, bans — with four distinct reasons recorded for a failed login:
unknown user, wrong password, missing second-factor code, wrong second-factor code. That distinction is
what lets you tell a scripted attack from someone who forgot their password. Two design points worth
naming: the user foreign key is set to null on delete, so forensic rows outlive the account and the email
and IP still identify the actor; and the audit write commits separately and never raises, so a failure to
log can never turn a valid login into an error.
→ `docs/platform-features.md` §13.

**★ R14. What's missing from your audit log?**
**Answer:** Quite a lot, and it's the most useful thing to admit about that subsystem. There's no audit
event for comments, alerts, notification preferences, market flags including who resolved them, disputes
including the admin's reasoning, treasury distributions, or market moderation decisions. So admin actions
beyond ban and unban leave no record at all. And even for bans, the acting admin only exists inside a JSON
metadata field that the admin audit endpoint doesn't return — so "who banned whom" isn't recoverable from
the API. That'd be my first fix: an admin-action audit table with a real actor column.

**★ R15. How do you paginate the trade tape, and why not offset?**
**Answer:** Keyset pagination with an opaque cursor. The cursor encodes the timestamp and the trade id
together, because timestamps aren't unique — several trades can land in the same millisecond — so the id
is the tiebreak. The filter is "timestamp is older, or same timestamp and id is smaller", matched against
a descending sort. Offset pagination would make the database walk and discard a hundred thousand rows to
reach page two thousand, and the result set can shift under you as new trades arrive. I also fetch one
extra row to detect whether another page exists, which answers that without a count over a high-write
table.
→ `docs/platform-features.md` §10.

**R16. Anything wrong with your pagination?**
**Answer:** Two things, and one of them was a bug I can describe. The global trade feed refuses offsets
beyond a thousand and tells the client to use a cursor — and there's a comment explaining that the check
used to be dead code, because a boolean was computed such that the condition could never be true, so deep
page requests silently returned the first page. That's a good example of a safeguard that looks like it's
working when it isn't; you have to read the boolean logic. Second, the per-market feed doesn't have that
guard at all, so you can force a large sequential scan there — an inconsistency between two nearly
identical handlers.

**★ R17. What does your API return on error, and how does the client handle it?**
**Answer:** One envelope everywhere: success with a data field, or failure with an error message and a
machine-readable error code, plus optional details. Schema validation failures come back as 422 with a
per-field list. There's a set of custom exception classes so a handler can say "not found", "forbidden",
"conflict", "insufficient balance", "market closed", "idempotency conflict" and "slippage exceeded"
without inventing status codes. And validation errors can name an exact condition, which lets the frontend
switch on the code and say something specific instead of "request failed".
→ `docs/platform-features.md` §12.

**R18. There's one place that doesn't follow the envelope. Which?**
**Answer:** The cross-origin check. It returns an error code and a message field but no success flag and no
error field, so a client with a single error parser will mis-read it. The rate-limit 429 in the same file
does conform and even has a comment saying the goal is that clients only ever parse one shape — so the
origin check is the outlier.

**R19. Why does a malformed ID produce 422 rather than 500?**
**Answer:** Because it's the caller's mistake, not a server fault. Asking for an order by a
non-identifier value sends an unparseable literal into a query that casts to a database UUID type.
Without a dedicated handler that error escapes as a 500 and the client concludes the server is broken, when
in fact the request was malformed. Mapping it to 422 with "invalid ID format" is the honest response — and
it also stops database errors leaking as 500s in monitoring.

**R20. How do comments handle replies?**
**Answer:** A self-referencing parent pointer plus a depth column. The application caps depth at three, so
four levels maximum including the top level. Deleting a comment is a soft delete, so replies keep a valid
parent and the thread doesn't collapse into orphans. And the parent lookup is scoped to the market, so you
can't reply to a comment on one market while posting "on" another — a genuine cross-market injection that
has a test.

**R21. How are referrals rewarded?**
**Answer:** A flat amount paid in the order path, not at signup — so the reward only happens when the
referred user actually trades. That's the right trigger: signup-only rewards attract fraud, while a reward
paid from real activity means it only fires when the platform is being used. Code generation retries five
times against the unique constraint and lets the database arbitrate the collision rather than
pre-checking, which would itself race.

---

---

## Cheat sheet — numbers worth remembering

| Thing | Value |
|---|---|
| Access token TTL | 900 s (15 min) |
| Refresh token TTL | 2 592 000 s (30 days), rotated per use |
| Password hash | bcrypt cost 12, ~100 ms |
| TOTP | 6 digits, ±30 s window, setup session 900 s |
| OTP | 8 digits, 600 s TTL, 5 sends / 5 verifies per 300 s, hash-only in Redis |
| Rate limits | 60/min/IP general · 5/min auth-decision · 3/min auth-fast · 30/min refresh · 10/min strict |
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
| Nightly jobs | 03:00 session cleanup → 03:30 protocol-fee sweep → 04:00 escrow audit (that order is deliberate) |
| Database | **24 tables**, 5 migrations, linear chain. **Zero** DB enums — statuses are plain strings |
| DB guarantees | identity/uniqueness, ranges (`price <= 1`), idempotency (partial unique indexes) |
| DB does *not* guarantee | money conservation — escrow discipline is service code + nightly audit |
| Known schema drift | 5 CHECK constraints in the models but **absent from the migrations** |
| Dispute window | 48 h from a proposed resolution; a dispute is adjudicable exactly once |
| Comment depth | max 3 |
| DB pool | `pool_size=5` per worker × 8 workers = 40, `max_overflow=5`, `pool_pre_ping=True` |
| Cache TTLs | market detail 300 s · market list 60 s · orderbook 60 s |
| Redis breaker | opens after 5 consecutive failures, 30 s recovery, one half-open probe |
| Celery | `acks_late` + `reject_on_worker_lost` (at-least-once), prefetch 1, concurrency 4 |
| Metrics | `http_requests_total{method,route,status}`, `http_request_duration_seconds{method,route}` |
| Health | `/health` liveness (no deps) · `/health/ready` (Postgres+Redis, 503 degraded) |
| Frontend | Next.js 16.3.3 · React 19.2.8 · Turborepo · Bun · TanStack Query 5 · Tailwind v4 |
| Frontend routing | 27 pages in 3 route groups; middleware renamed to `proxy.ts` in Next 16 |
| WS client | 1 socket per tab, capped at 8 reconnect attempts, 30 s max backoff |
| Frontend tests | **0** — the honest headline |
| Test suite | **387** tests across 22 files; DB rebuilt from Alembic `head` every run |
| WS heartbeat | 30 s ping sweep, reaps on `SEND_TIMEOUT_S` (2 s); `cause="heartbeat"` |
| WS metrics | `ws_connections`, `ws_subscriptions` (per-worker gauges) + 4 counters |
| Test infra | `pm-postgres` on 5433, `pm-redis` on 6380 — `docker start pm-postgres pm-redis` |
