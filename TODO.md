# TODO — Remaining Backend Fixes (pick up tomorrow)

> 9 CRITICAL (P0) already fixed & closed on 2026-09-16 (commits `eb9309d`..`e029867`, issues #22,28,31,34,37,40,43,46,49).
> 21 issues remain open — this file is the ordered backlog.

## How to use

- Issues are ordered by severity → do HIGH before MEDIUM. Within HIGH, do infra/db first (H1,H7) then concurrency.
- Each item links to GitHub issue + `file_path:line_number`. Check box when PR merges and issue closed via `curl -X PATCH ... '{"state":"closed"}'`.
- Run `python3 -m py_compile <file>` after each edit, then `git commit -m "fix(ID): ..."`.

## HIGH — do first (11)

- [ ] **#23 H1 Missing indexes / N+1** — `backend/app/api/market_activity.py:80`, `backend/app/api/comments.py:103`
  - Add `Index(ix_comments_parent_id, parent_id)`, `ix_comments_market_id`, composite `orders(market_id,outcome_id,price)`. Migration + `EXPLAIN ANALYZE`.
- [ ] **#44 H7 DB/Redis pool exhaustion** — `backend/app/database.py:15`, `backend/gunicorn.conf.py:6`, `backend/app/config.py:44`, `backend/scripts/postgres.conf`
  - `pool_size=5` per worker, `max_connections=200`, separate redis budgets, reuse `get_db` session instead of `async_session()` in `backend/app/services/market_service.py:69`.
- [ ] **#32 H3 Lock ordering deadlocks** — `backend/app/services/liquidity_service.py:131`, `backend/app/api/split_merge.py:42`, `backend/app/services/order_service.py:159`
  - Enforce global order `Market→Pool→Wallet→Position→LPShare→Order`, helper `acquire_locks_in_order()`.
- [ ] **#38 H5 Rate limiting bypass** — `backend/app/api/middleware.py:16`, `backend/app/services/rate_limit_service.py:178`, `backend/app/app.py:125`
  - Require `TRUSTED_PROXY_IPS` in prod (fail-closed), key on `user_id` when authed, friction fail-closed.
- [ ] **#41 H6 Cache thundering herd** — `backend/app/services/market_service.py:166`, `backend/app/services/cache_service.py:94`
  - Lua unlock verifying owner, `try/finally` delete outside breaker, store full `cache:ml:{k}` in tag set.
- [ ] **#47 H8 Celery reliability** — `backend/app/workers/celery_app.py:19`, `backend/docker-compose.prod.yml:161`, `backend/app/workers/tasks.py:682`
  - `visibility_timeout=3600`, `reject_on_worker_lost`, beat distributed lock `SET NX`.
- [ ] **#50 H9 WebSocket fan-out** — `backend/app/websocket/manager.py:537`, `backend/app/app.py:185`
  - Bound queue `Semaphore(100)` + `Queue`, shard channels by `hash(market_id)`.
- [ ] **#35 H4 Referral code race** — `backend/app/api/referrals.py:17`
  - `SELECT FOR UPDATE` + retry on `IntegrityError`, 12-char code.
- [ ] **#29 H2 Unbounded pagination** — `backend/app/api/market_activity.py:120`, `backend/app/api/trades.py:52`, `backend/app/api/markets.py:374`
  - Cursor pagination, `LIMIT 5000`, SQL `date_bin` aggregation.
- [ ] **#25 H10 Decimal/float mixing** — `backend/app/services/liquidity_service.py:58`, `backend/app/workers/tasks.py:386`
  - Remove remaining `float()` in money paths, `referral_reward_amount: Decimal` already done, quantize only at serialization.
- [ ] **#27 H11 JWT & PII** — `backend/app/deps.py:79`, `backend/app/api/auth.py:988`, `backend/app/api/middleware.py:99`
  - Shorten refresh TTL, blacklist fail-closed, scrub `X-Forwarded-For`, propagate `X-Request-ID` to Celery.

## MEDIUM / LOW — quick wins (10)

- [ ] **#26 M10 `__table_args__` overwritten** — `backend/app/models/market.py:22` (1-line fix, merge `CheckConstraint` + `Index`)
- [ ] **#24 M1 CORS empty origin** — `backend/app/app.py:211` (filter `""`, validate on startup)
- [ ] **#30 M2 Alembic URL drift** — `backend/alembic.ini:6` (read `DATABASE_URL` from env)
- [ ] **#33 M3 Dockerfile leaks** — `backend/Dockerfile:38` + `backend/.dockerignore` (exclude `.env`/`dump.rdb`, drop `psycopg2-binary`, add `HEALTHCHECK`)
- [ ] **#36 M4 Gunicorn tuning** — `backend/gunicorn.conf.py:8` (`timeout=120`, `graceful_timeout=30`)
- [ ] **#39 M5 Webhook verify** — `backend/app/api/webhooks.py:30` (use `stripe.Webhook.construct_event`, dedup `event.id`)
- [ ] **#42 M6 Treasury singleton** — `backend/app/api/treasury.py:20` (singleton CHECK / `INSERT ON CONFLICT`)
- [ ] **#45 M7 Comment depth** — `backend/app/api/comments.py:95` (`WHERE depth <=3`)
- [ ] **#51 M9 Tests leak** — `backend/tests/conftest.py:58`, `backend/app/services/market_service.py:69` (`TRUNCATE CASCADE`, `NullPool`, patch `async_session()`)
- [ ] **#48 M8 Email thread** — `backend/app/services/email_service.py:85` (already fixed for daemon, remaining: remove `requests` dep, add backpressure)

## Closed today (reference)

- #22 C1 `backend/app/workers/tasks.py:827` LP dedent
- #28 C2 `backend/app/api/market_activity.py:48` price inversion
- #31 C3 `backend/app/api/wallet.py:61` Stripe
- #34 C4 `backend/app/services/wallet_service.py:118` idempotency
- #37 C5 + #40 C6 `backend/app/models/wallet.py:16` CHECKs + Decimal guards
- #43 C7 + #46 C8 `backend/app/redis.py:88` + `backend/app/services/email_service.py:85`
- #49 C9 `backend/app/workers/tasks.py:770` double settlement

## One-liner to verify open vs closed

```bash
curl -s 'https://api.github.com/repos/f0rsakeN-afk/polymarket/issues?state=open&per_page=100' | python3 -c "import json; d=[x for x in json.load(open('/dev/stdin')) if 'pull_request' not in x]; print('\n'.join(f\"#{x['number']} {x['title']}\" for x in sorted(d, key=lambda x: x['number'])) )"
```

## Suggested tomorrow order

1. `#26` (1 line) → `#44` (config) → `#23` (migration) → `#32` → `#38` → `#41` → `#47` → rest. Gets infra stable before concurrency work.
