# Defence Runbook • Rehearsing the Live Demo

Everything needed to *run* the project and demo it under pressure: what to start, in what order,
what to show, what to say while showing it, and what to do when something breaks in front of a panel.

> Companion docs: `docs/README.md` (index) · `concepts.md` (the story) · `data-model.md` ·
> `trading-engine.md` · `platform-features.md` · `background-jobs.md` · `frontend.md` ·
> `docker-concurrency-realtime.md` · `viva-questions.md` (322 questions).
>
> A demo is worth about as much as a viva. The rule that matters: **every thing you show must have a
> sentence explaining why it matters.** A panel reads an unexplained screen as a screenshot.

---

## 0. The one-page run sheet

Keep this visible during the demo. Everything else in this document is detail.

| Phase | Show | Say this (one line) |
|---|---|---|
| **1. The product** | Markets list → a market detail page | "A share pays $1 if the event happens. Price = the crowd's probability." |
| **2. It trades** | Place a market buy, watch the price move | "The AMM prices from share reserves, so your own trade moves the price." |
| **3. It's real money** | Wallet balance changes; transaction row appears | "Every balance change is an append-only ledger row with the balance after it." |
| **4. It's live** | Second tab on the same market; trade appears | "One WebSocket per tab, fed by Redis pub/sub, so any of the 8 workers can push." |
| **5. It's safe** | Two accounts order simultaneously | "One serialisation point with a fixed lock order • that's the answer to the hard question." |
| **6. It's correct** | `pytest -q` output | "511 tests, DB rebuilt from migrations every run." |
| **7. It's honest** | The gap list | "Here's what I know is wrong, and here's what I'd fix first." |

**Phases 5–7 are what separate you.** Anyone can show a market list.

---

## 1. Getting it running

### 1.1 Prerequisites

| Need | Version | Check |
|---|---|---|
| Docker | any recent | `docker --version` |
| uv | any recent | `uv --version` |
| Bun | 1.3.x | `bun --version` |
| Python | 3.13+ (3.14 in CI) | `python3 --version` |

### 1.2 Backend • one time

```bash
cd backend
cp .env.example .env
# Generate the three secrets the app refuses to boot without:
python3 -c "import secrets;print('JWT_SECRET='+secrets.token_urlsafe(64))"
python3 -c "import secrets;print('SECRET_KEY='+secrets.token_urlsafe(64))"
python3 -c "import base64,hashlib;print('TOTP_ENCRYPTION_KEY='+base64.b64encode(hashlib.sha256(secrets.token_bytes(32)).digest()).decode())"
# Paste all three into .env
```

> **Why the app refuses to boot:** `app/app.py:107-121` raises `RuntimeError` if any of
> `JWT_SECRET`, `SECRET_KEY` or `TOTP_ENCRYPTION_KEY` is still `change-me-in-production`. Mention it •
> "it refuses to start with a known-public secret" is a sentence that lands.

### 1.3 Start everything

```bash
cd backend
docker compose -f docker-compose.dev.yml up -d   # postgres :5433, redis :6380
uv sync
uv run alembic upgrade head
./start.sh                                       # API :8000 + celery worker + beat
```

In a second terminal:

```bash
cd frontend
bun install
bun run dev                                      # http://localhost:3000
```

Verify before you present anything:

```bash
curl -s localhost:8000/health          # {"status":"ok"}
curl -s localhost:8000/health/ready    # postgres + redis, 200 ok
curl -s localhost:8000/metrics | head  # Prometheus counters exist
```

**Do this at least 30 minutes before the defence.** Every failure mode below is cheaper to fix in
advance than to debug live.

### 1.4 Seed data • strongly recommended

A fresh database is empty, and an empty prediction market is a bad demo.

```bash
cd backend
uv run python -m scripts.seed
```

It creates users, wallets, markets, outcomes, pools, LP shares, pending orders, positions, trades,
comments, disputes, alerts, notifications, referrals, transactions, flags, treasury, and price
history, then prints a row count per table. Seed password is `SEED_PASSWORD` (default
`testpass123`).

This matters because it means the trade tape, charts, comments and holders list all have content •
which is what phase 1 and 3 depend on.

---

## 2. The demo, phase by phase

### Phase 1 • the product (2 min)

Show the markets list, then one market detail page.

**Say:** *"This is a prediction market. A YES share pays $1 if the event happens and $0 if it doesn't.
When a share costs $0.70, the crowd is saying there's about a 70% chance. You can buy, sell or hold at
any time at a public price • that's what separates it from a bet."*

**Point at, deliberately:** the two prices, the order book, the volume, the holders list.

**Don't** read the page out. Name three things and move on.

### Phase 2 • it trades (2 min)

Buy some shares. Watch the price move against you.

**Say:** *"The pool is priced by share ratio, not a constant-product curve. Price is YES shares over
total shares. So when I buy, I take YES shares out of the pool and push the ratio • and I'm paying the
post-trade price, which is why a buy-then-sell round trip can only ever return the fees, never more."*

That last clause is the answer to *"isn't this an exploit?"* • say it before you're asked.

If you want to show a **resting limit order**, place one priced away from the market and show it in
the orders list with funds visibly locked. That demonstrates the money side of order placement, which
is the part most demos skip.

### Phase 3 • real money (1 min)

Show the wallet before and after, then the transactions table.

**Say:** *"Every balance change is an append-only ledger row that stores the balance after it. So the
ledger is self-auditing • I can replay it and check it sums. It's the same pattern as a bank."*

### Phase 4 • it's live (2 min)

Open a second browser tab on the same market. Trade in one.

**Say:** *"One WebSocket per browser tab, not per component. Trades are published to Redis pub/sub,
every one of the eight workers has its own listener, and each pushes only to its own sockets. So it
doesn't matter which worker handled the order."*

Then reconnect deliberately • kill your network or stop the API • and show it recovering. *"Exponential
backoff capped at eight attempts, about two minutes. Without a cap it would retry for the lifetime of
the tab."*

### Phase 5 • it's safe (2–3 min) ← the important one

This is the phase that answers *"two users buy at the same instant"*.

Open two private windows (or two accounts), place orders on the same market at the same time.

**Say:** *"There's exactly one serialisation point • the order service takes row locks on the market,
the pool and the wallets, always in that order. Then the matching engine re-checks that a seller
actually has the shares before it mutates anything. And because the order is fixed, two transactions
can't deadlock."*

**Then prove it:**

```bash
cd backend && uv run pytest tests/test_concurrency.py -q
```

> If you only get to run one test file live, run **this** one. It fires parallel orders at one market
> and asserts the invariants hold. A green concurrency suite is the most convincing 3 seconds of a
> demo you can produce.

### Phase 6 • it's correct (1 min)

```bash
cd backend && uv run pytest -q
```

**Say:** *"511 tests across 30 files. The test database is dropped and rebuilt from the Alembic
migrations on every single run, so a stale schema can never make a failing test pass."*

### Phase 7 • it's honest (2 min) ← do not skip

Open `docs/README.md` → "Known gaps we admit rather than hide".

**Say:** *"These are the things I know are wrong. There's no frontend test suite at all. The escrow
audit only logs • nothing alerts on it. Five CHECK constraints are in my models but missing from my
migrations. I have no kill switch. I'd fix the audit alerting first, because it protects the money."*

Naming gaps unprompted scores more than being asked and conceding.

---

## 3. Live-code targets, and where they are

If a panel says *"show me that code"*, these are the highest-value files. Open them **before** the
demo so they're already in your editor tabs.

| If they ask about… | Open | Point at |
|---|---|---|
| "No money from thin air" | `app/services/order_service.py` | the lock block: market `:191`, pool `:211`, wallet `:218` |
| "Seller cover check" | `app/services/matching_engine.py:138` | the guard, before `shares_held -=` at `:221` |
| "The maths" | `app/amm/engine.py` | price from share ratio |
| "Settlement safety" | `app/workers/tasks.py:834-873` | the escrow pre-flight |
| "Background jobs" | `app/workers/celery_app.py:47-83` | the 8-entry beat schedule |
| "Auth" | `app/deps.py`, `app/api/auth.py` | refresh rotation + reuse detection |
| "The schema" | `app/models/wallet.py:20-24` | the CHECK constraints |
| "Realtime" | `app/websocket/manager.py` | the fan-out + bounded send |
| "The client" | `frontend/apps/web/hooks/use-market-socket.tsx` | the singleton + reconnect |
| "A bug you fixed" | `app/models/liquidity.py:73-97` | `debit_collateral` refusing to underpay |

---

## 4. When it breaks live

This section is the reason to read this document. Have the fallback ready.

### 4.1 The API didn't start

**Symptom:** `./start.sh` exits, or `/health` fails.

| Cause | Fix |
|---|---|
| Placeholder secret still in `.env` | Generate all three (see §1.2). The app refuses to boot on purpose. |
| Postgres not up | `docker ps` • then `docker compose -f docker-compose.dev.yml up -d` |
| Migration not run | `uv run alembic upgrade head` |
| Port 8000 taken | `lsof -i :8000` → `backend/stop.sh` |

The startup code **waits up to 60 seconds** for Postgres and Redis before giving up
(`app/app.py:151-186`) • so if it fails, the dependency genuinely isn't there.

### 4.2 Prices don't move live

**Symptom:** orders fill but the chart is frozen.

Check the WebSocket: browser devtools → Network → WS. Then check the worker:

```bash
docker logs -f <redis-container>      # Redis up?
# Is beat running?  psql -h localhost -p 5433 -U myuser mydatabase -c "select 1"
```

Remember the design: **Redis pub/sub failing never breaks a trade.** If orders fill but nothing
pushes, it's Redis fan-out, not the money path • which is itself a good thing to say out loud.

### 4.3 Frontend shows stale/empty data

Most likely cause: the API base URL. It's baked in at **build** time from
`NEXT_PUBLIC_API_URL` (`Dockerfile:27-31`), so changing it needs a rebuild, not a restart.

Second most likely: `credentials: "include"` isn't reaching the backend because of a cookie domain
mismatch between `localhost:3000` and `localhost:8000`. Cookies are host-scoped and **ignore ports**,
so a host-only cookie from `:8000` is sent to `:8000` just fine • if you're seeing this, something
has reintroduced a `Domain=` attribute.

### 4.4 Tests fail on a clean machine

| Cause | Fix |
|---|---|
| Test infra not up | `docker start pm-postgres pm-redis` (ports 5433 / 6380) |
| Stale test DB | It's dropped and recreated automatically • if it still fails, check Postgres is actually reachable |
| `DATABASE_URL` drift | `conftest.py` forces the DB name to `mydatabase_test`; don't override it |

### 4.5 The nuclear option

If the demo is falling apart and you have 5 minutes left, **stop trying to run it**. Open
`docs/architecture.md` and walk the diagram, then answer from `docs/viva-questions.md`.

A structured verbal defence beats a broken demo every time. Practise this transition so it doesn't
feel like a fallback.

---

## 5. Questions to expect in the first 5 minutes

Practise saying the *short* answer first, then offer the long one.

| Likely opening question | Short answer, then offer |
|---|---|
| "Walk me through it." | The 60-second version → `viva-questions.md` §A1, or phase-1 script above |
| "What's the hardest part?" | Order execution under concurrency → `trading-engine.md` §2, `docker-concurrency-realtime.md` §B |
| "Why these technologies?" | `viva-questions.md` §A2–A4 |
| "What would you do differently?" | `viva-questions.md` §M |
| "Is this legal / is it gambling?" | `trading-engine.md` §7 • have the caveat ready, don't waffle |
| "How do you know it's correct?" | Phase 5/6 • run the tests |

**If you don't know**, say so precisely and say what you'd check:

> *"I don't remember the exact line, but I know the guard is in the matching engine before it mutates
> a position. Let me find it."*

Never invent an answer. A panel can always tell, and a confident wrong answer costs more than an
admitted gap.

---

## 6. Final checklist

**The night before**
- [ ] `.env` has three real secrets
- [ ] `pytest -q` is green • note the count
- [ ] `bun run lint` and `bun run typecheck` clean
- [ ] Seed the database
- [ ] Read `docs/README.md` gap list out loud once

**An hour before**
- [ ] Start the stack, confirm `/health/ready` returns 200
- [ ] Confirm the homepage renders with data
- [ ] Place one real order, confirm it appears in the transactions table
- [ ] Confirm live updates work in a second tab
- [ ] Editor tabs open on the phase-3 target files
- [ ] Terminals clear, `docs/` open

**Five minutes before**
- [ ] Deep breath. You know this system better than anyone in the room.
- [ ] Remind yourself: **naming the gaps is the answer that scores.**

---

## 7. If asked "what's next?"

Have a real answer. The strongest roadmap, in order:

1. **Alert on the escrow audit violations.** The detection already works and logs structured events;
   nothing watches them. Cheapest fix with the highest value.
2. **Frontend tests for the two subtle files** • the API client's refresh state machine and the
   WebSocket reconnect logic. Turn the explanatory comments into tests.
3. **A kill switch.** A prediction market with no way to halt trading during an incident is a real
   operational gap.
4. **Close the schema drift.** One migration adding the five missing CHECK constraints.
5. **A real admin audit trail.** Right now the only admin action recorded is ban/unban, and the actor
   isn't recoverable from the API.

Each of these is concrete, scoped, and justified by something already written down • which is exactly
what "what's next" should sound like.
