# Authentication System & Security Posture

> Scope: `backend/app/api/auth.py`, `backend/app/deps.py`, `backend/app/api/middleware.py`,
> `backend/app/services/{otp,totp,rate_limit,password_strength,audit}_service.py`,
> `frontend/apps/web/proxy.ts`, `frontend/apps/web/lib/api/client.ts`, `next.config.ts`.

---

## 1. High-level model

**Stateless JWT for the request, stateful rows for revocation.**

| Piece | Where | Detail |
|---|---|---|
| Access token | JWT HS256, `settings.jwt_secret` | `jwt_access_expire = 900s` (15 min). Claims: `sub` (user id), `exp`, `type: "access"`, `jti` (uuid), `sid` (session id) |
| Refresh token | opaque uuid4, **stored only as SHA-256 hash** | `jwt_refresh_expire = 2592000s` (30 days) |
| Session row | `sessions` table | `id = sid`, `user_id`, `refresh_token_id`, `ip_address`, `user_agent`, `expires_at`, `revoked`, `last_active_at` |
| Transport | **HttpOnly cookies**, not localStorage | `access_token`, `refresh_token` |

`_issue_tokens()` (`auth.py:75`) is the single minting path: it creates the session row **first**
(so `sid` exists), then mints the access token carrying that `sid`, then inserts the
`RefreshToken` row with `token_hash = sha256(token)`. Plaintext refresh tokens never touch the DB.

### Why `sid` matters
`_validate_session()` (`deps.py:131`) loads the `Session` named by the token's `sid` and rejects
when the row is missing, belongs to another user, is `revoked`, or is expired. This makes
revocation **exact**:

- `POST /auth/logout` → revokes that refresh token + that session → that device dies immediately.
- `DELETE /auth/sessions/{id}` → another device dies, current one keeps working.
- `POST /auth/logout-all` → revokes every refresh token + every session for the user.

Without `sid` a JWT would stay valid for its full 15 minutes no matter what you did server-side.

### Cookie flags (`set_auth_cookies`, `deps.py:213`)

```
httponly = True          # JS can never read the tokens → XSS can't exfiltrate them
secure   = (app_env == "production")   # HTTPS only in prod; localhost must work in dev
samesite = "lax"         # sent on same-origin + safe top-level navigations only
path     = "/", domain = "localhost" in dev / None in prod
```

### Refresh rotation + reuse detection (`POST /auth/refresh`, `auth.py:1037`)

1. Look up by **hash**, no status filter, `SELECT ... FOR UPDATE` (row lock — two parallel
   refreshes serialize instead of both minting).
2. `token_record.revoked == True` ⇒ **reuse detected**: a rotated-away token came back, meaning
   it was stolen. Response: revoke *all* refresh tokens and *all* sessions for that user,
   `logger.warning(...)`, 401.
3. Expiry check → revoke + 401.
4. Account active check → 403.
5. **Refresh-chain deadline** (`_refresh_chain_deadline`): Redis holds
   `refresh_chain:{sha256(token)} → <absolute unix deadline>`. Login writes it
   (`now + refresh_chain_max_seconds`, default 30 d); rotation *inherits* it rather than starting a
   fresh one, which is what makes the cap absolute — renewing can never move it. Past the deadline
   ⇒ every refresh token **and** every session for that user is revoked (`_revoke_chain`) + 401.
   If Redis has no anchor (pre-feature token, flush) the check is skipped with a warning rather
   than failing closed, because a Redis restart must not log every user out; the per-token TTLs
   still apply.
6. **Issuance-time sanity check** (`expires_at - jwt_refresh_expire` recovers this token's issue
   time; refuse it once that is older than the chain cap).
7. **Device binding**: `token_record.device_info != current UA` ⇒ revoke + 401
   ("Device mismatch — please re-authenticate").
8. Rotate: revoke old token + old session, issue new pair bound to current ip/UA, passing
   `previous_token_hash` so the new token inherits the chain deadline (`_anchor_refresh_chain`).

The frontend does this transparently: `client.ts:221 doRefresh()` fires once
(single-flight via `isRefreshing` + `refreshSubscribers[]`, 10 s timeout), every queued 401
retries after it, and failure → `redirectToLogin()`.

> **Two bugs that lived here, worth naming:** (a) the old step 5 compared a token's *issuance*
> time to `now` (`expires_at - ttl <= now`), which is true for every token ever issued — so
> `/auth/refresh` answered 401 on **every** call and a session died the moment its 15-minute
> access token expired. Nothing caught it because no test exercised the endpoint. (b) With no
> rotation-stable anchor, a client that kept refreshing could renew forever. Both are fixed: the
> DB-only check now means what it says, and the Redis deadline above bounds the whole login chain
> from the moment of login.
>
> **Tests:** `test_auth.py::test_refresh_rotation_inherits_the_chain_deadline` (the rotated token
> carries the same absolute deadline) and `::test_refresh_chain_stops_at_the_absolute_deadline`
> (past it: 401, every refresh token revoked, every session revoked).

---

## 2. Credentials

**Hashing** — `hash_password()` / `verify_password()` (`deps.py:57`) use **bcrypt** with
`bcrypt.gensalt()` (default cost 12). `verify_password` returns `False` on empty hash (never
crashes on the system/treasury account).

**Strength policy** — `PasswordStrengthService.check()`:
- 8–128 chars
- 8–11 chars ⇒ need ≥3 of {lower, upper, digit, special}; ≥12 chars ⇒ need ≥2
- rejects sequential runs (`abc`, `123`), and repeats (`aaa`, `111`)

**Login flow hardening** (`auth.py:800`):
- Rate limit + friction checked **before** any DB work.
- `RateLimitService.record_failure()` is called **even when the user does not exist**, so lockout
  behaves identically for real and fake emails.
- **When the email does not exist the handler still runs a bcrypt verification** against
  `dummy_password_hash()` — a cached hash of a random secret — so an unknown email costs the same
  ~100 ms as a known one. Without it, response time alone is a reliable "does this account exist"
  oracle that defeats every other anti-enumeration measure.
- Failure responses are always the identical `"Invalid email or password"`.
- `POST /auth/register` answers **the same 200 with the same body and message** whether the email
  is new, already-verified (the owner gets a throttled "you already have an account" email) or
  awaiting verification (the code is re-sent). It used to answer `409 "An account with this email
  already exists"` — a free account-existence oracle sitting right next to the login form. The
  duplication notice is throttled per email (10 min) so the form cannot be used to flood an inbox.
- Password check happens *before* `is_active` / `is_email_verified` checks, so account state is
  not leaked to someone who doesn't know the password.
- 2FA code required and verified only after password success.

**Startup fail-fast** (`app.py:107-121`): the app refuses to boot if `totp_encryption_key`,
`jwt_secret`, or `secret_key` is still the `"change-me-in-production"` placeholder.

---

## 3. The five login methods

| Method | Endpoint(s) | Notes |
|---|---|---|
| Password | `POST /auth/login` | + optional `totp_code` when 2FA on |
| Email OTP magic code | `POST /auth/magic-link` → `POST /auth/verify-magic` | 8-digit code, 600 s TTL |
| Magic **URL** | `POST /auth/magic-link/url` → `POST /auth/verify-magic-url` | uuid4 token, 900 s TTL, single-use, **IP-bound** |
| Email verification | `POST /auth/register` → `POST /auth/verify-email` | account is `is_email_verified=False` until code confirmed; login refuses unverified |
| Password reset | `POST /auth/forgot-password` → `POST /auth/reset-password` | OTP verified **before** the strength check, so the policy can't be probed without a valid code; on success revokes all refresh tokens |

**OTP details** (`otp_service.py`):
- 8 digits from `secrets.randbelow(10**8)` ⇒ 10⁸ = 100 M combos, cryptographically random.
- Redis holds **only** `hmac_sha256(key=sha256(jwt_secret:email:purpose), msg=code)` — the
  plaintext code never reaches Redis (it exists only in the return value of `send_code` and in the
  outbound email). Verification re-hashes the submitted code and compares with
  `hmac.compare_digest` (constant-time, no timing oracle). Legacy `code:hash` entries are still
  accepted for the remainder of their ≤10 min TTL so a rolling deploy doesn't reject in-flight
  codes, but nothing writes that format any more.
- Send limit: **5 codes per email+purpose per 300 s** (anti email-bombing) — atomic Lua.
- Verify limit: **5 attempts per email+purpose per 300 s** — atomic Lua, returns `False` when hit.
- Deleted on successful use (single-use); `OTPService.invalidate()` on resend.

**Magic-URL binding** (`auth.py:447`): payload stored as JSON `{user_id, ip, ua}`. On redeem the
current IP must `_ip_matches()` the stored IP — IPv4 compares the **first 3 octets** (/24) and
IPv6 the **first 48 bits** (/48), deliberately tolerating NAT/proxy rotation while still rejecting
a token replayed from a different network. The token is deleted **after** the IP check so a
legitimate user behind a rotating NAT can retry instead of being locked out.

**Partial tokens for 2FA handoff**: when 2FA is on but the TOTP hasn't been supplied yet, the
server returns a short-lived Redis-backed `partial_token` (300 s) in the **response body** —
deliberately not in an error message or URL, so it can't leak via logs or `Referer`. It's
deleted only on success (retry allowed on a mistyped TOTP) and carries the IP for matching.

---

## 4. 2FA (TOTP)

- `GET /2fa/setup` → `pyotp.random_base32()` (160-bit secret), `otpauth://` provisioning URI
  (issuer `Polymarket`), secret **encrypted at rest with Fernet** whose key is
  `sha256(TOTP_ENCRYPTION_KEY)` — an env var **independent of `JWT_SECRET`**, so rotating one
  doesn't break the other. Stored with `is_2fa_pending = True`.
- Redis `2fa_pending:{user_id}` with `totp_setup_expire_seconds = 900` — a setup session older
  than 15 min is dead; `/2fa/enable` wipes the secret and forces a restart.
- `POST /2fa/enable` requires a *valid* code (proof the authenticator actually works).
- `POST /2fa/disable` requires **password AND current TOTP code**.
- Verification: `TOTPService.verify_code` with `valid_window=1` (±30 s drift), rejects
  non-6-digit input.
- **Change password also requires TOTP when 2FA is on** (`auth.py:1010`).

---

## 5. Rate limiting & brute-force defence

**Layer 1 — `RateLimitMiddleware`** (outermost middleware, `middleware.py:124`):
- Sliding-window **Lua** on a Redis ZSET (`ZREMRANGEBYSCORE` + `ZCARD` + `ZADD`) — exact counts,
  no fixed-window boundary burst.
- Limits: `GENERAL 60/min/IP`, `AUTH_DECISION 5/min/email+IP`, `AUTH_FAST 3/min/email+IP`,
  `STRICT 10/min/IP`.
- Auth paths are mapped in `_get_auth_limit_type()`; login/verify/reset → `AUTH_DECISION`.
- Identifier is `user_id` when authenticated else IP; auth limits composite `email@normalized_ip`
  (IPv6 normalized to /64 so one host isn't fragmented across buckets).
- Redis error ⇒ **fail closed** (`allowed=False, retry_after=60`).
- Responds `429` + `Retry-After` + `X-RateLimit-Limit/Remaining`.

**Layer 2 — progressive friction** (`check_with_friction`, per auth endpoint):
- First 5 attempts are free; beyond that the Lua script returns an escalating delay
  `min(2^(attempts-5), 16)` → 1s, 2s, 4s, 8s, 16s cap, with a `lockout = 900s` window.
- Lockout is checked **before** the increment, so it fires on attempt 5, not 6.
- `reset_friction()` wipes the counter on successful auth.

**Layer 3 — trusted proxy IP resolution** (`_get_client_ip`): `X-Forwarded-For` is honoured **only**
when the direct peer is in `TRUSTED_PROXY_IPS`; otherwise it is discarded and the socket peer is
used. This is **fail-closed by design**: the header is entirely client-controlled, so honouring it
would let an attacker rotate fake IPs past every IP-based limit *and* stamp arbitrary source
addresses into the audit trail. When `TRUSTED_PROXY_IPS` is empty in production and a proxy sends
XFF anyway, the code logs a loud warning and ignores the header.

> **Operational consequence (say this out loud in a viva):** set `TRUSTED_PROXY_IPS` to the
> nginx/container proxy address in production. Without it every request appears to come from the
> proxy and shares a single rate-limit bucket — an availability trade-off, deliberately chosen
> over a spoofability hole. The websocket path (`websocket/routes.py:_get_real_client_ip`) uses
> the identical rule, and `api/auth.py:_get_client_ip` now delegates to this one implementation
> rather than keeping a second copy that could drift.

**Layer 4 — body cap**: `_MAX_BODY_BYTES = 256 KiB`, enforced on `Content-Length` *before* the body
is buffered (Pydantic `max_length` only fires after the whole payload is already in memory).

---

## 6. Audit trail

`AuthAuditService` (`services/audit_service.py`) writes to `auth_audit_events`
(`user_id` with `ON DELETE SET NULL` so anonymous events survive, `email`, `ip_address`, `event`,
`metadata`, `success`, `failure_reason`, composite indexes on `(user_id,event)` / `(email,event)`).
~20 named helpers: `log_login_success/fail`, `log_register`, `log_email_verified`,
`log_password_change/reset_*`, `log_2fa_setup_requested/enabled/disabled`, `log_logout/all`,
`log_session_revoked`, `log_account_banned/unbanned`. Surfaced via admin-only
`GET /api/v1/admin/audit-events`.

Every auth request also passes through `RequestLoggingMiddleware`, which logs a structured JSON
line with `request_id`, `user_id`, `method`, `path`, `status_code`, `latency_ms`, `client_ip` —
and explicitly scrubs raw headers so `Cookie`/`Authorization` never reach the log.

---

## 7. SQL Injection — why we're safe

**No raw string concatenation into SQL anywhere in `app/`.** Verified by grep:

1. **The ORM builds every query from Python expressions.**
   `select(User).where(User.email == data.email)` compiles to a **bound parameter**
   (`WHERE users.email = %(email_1)s`) — Postgres then treats the value as data, never syntax.
2. **The four raw-SQL statements that do exist are all parameterised.** `matching_engine.py:218`,
   `order_service.py:524`, `split_merge.py:107`, `workers/tasks.py:322` all use
   `text("""... VALUES (... :user_id, :market_id ... )""")` with a separate `{"user_id": ...}`
   bind dict. `:name` placeholders are *not* f-strings — they're bound by SQLAlchemy.
3. **Search input is bound *and* escaped.** `markets.py:134`:
   ```python
   safe_q = q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
   base = where(Market.question.ilike(f"%{safe_q}%", escape="\\"))
   ```
   The `%...%` is the *pattern template* (a constant); `safe_q` is still a bound parameter — the
   escaping only prevents wildcard abuse (`%`, `_`), not injection. Same pattern in `admin.py:62`.
4. **Full-text search uses `func.plainto_tsquery("english", q)`** — `q` is a bind parameter, not
   interpolated into the tsquery string (this is a classic injection point done correctly).
5. **ORDER BY can't be parameterised**, so the `sort` value is **whitelisted via if/elif**
   (`markets.py:145-153`) mapping to pre-built SQLAlchemy column expressions. An attacker sending
   `sort=1;DROP TABLE` just falls into the `else` branch.
6. **Literals-only `text()` uses** are `SELECT 1` health checks, index predicates
   (`postgresql_where=text("triggered = false")`), and `TRUNCATE` in test fixtures.
7. `f-string` SQL appears **only** in `scripts/seed.py` (internal table-name loop),
   `tests/conftest.py`, and `e2e_api_test.py` (test-only, hardcoded prefixes) — never on a
   request path.
8. **IDs are UUIDs validated by Pydantic/`DataError` handling** — a malformed UUID returns
   422 `"Invalid ID format"` instead of reaching the DB as a string.

---

## 8. XSS — why we're safe

**Frontend (the real XSS surface):**
- **React escapes all interpolated text by default.** `{comment.content}` renders
  `<script>alert(1)</script>` as literal text. Verified: **zero** occurrences of
  `dangerouslySetInnerHTML`, `innerHTML`, `document.write`, `eval(`, `new Function`, `v-html`
  across the entire frontend.
- **No markdown/HTML renderer** (no `rehype-raw`, no `marked`, no DOMPurify needed because no raw
  HTML is ever parsed).
- **Content-Security-Policy** (`next.config.ts:25`), applied to every route:
  ```
  default-src 'self'; script-src 'self' 'unsafe-inline'  ('unsafe-eval' dev-only)
  style-src 'self' 'unsafe-inline'; img-src 'self' data: https:
  connect-src 'self' <apiOrigin> <wsOrigin>; object-src 'none'
  frame-ancestors 'none'; base-uri 'self'; form-action 'self'
  ```
  Even if an injection slipped through, inline script execution is constrained and `base-uri
  'self'` blocks `<base>` hijacking; `form-action 'self'` blocks exfiltration via form post.
- **Backend CSP** is stricter still: `default-src 'none'; frame-ancestors 'none'; form-action 'none'`
  (`middleware.py:85`) — the API returns JSON, it needs no resources at all.
- **Headers on all three layers** (Next config, FastAPI `SecurityHeadersMiddleware`, and both
  nginx confs): `X-Content-Type-Options: nosniff` (kills MIME sniffing → HTML served as JSON
  can't execute), `X-Frame-Options: DENY` (clickjacking), `X-XSS-Protection: 1; mode=block`,
  `Referrer-Policy: strict-origin-when-cross-origin` (no token leakage via Referer),
  `Permissions-Policy` disabling camera/mic/geo/payment/etc., **HSTS
  `max-age=31536000; includeSubDomains`** only in production/HTTPS.
- **Tokens are HttpOnly cookies**, so even a successful XSS payload cannot read
  `access_token`/`refresh_token` via `document.cookie`.
- `nosniff` + JSON `Content-Type` + the backend CSP mean the API itself can never be a script host.

---

## 9. CSRF — why we're safe

There is **no explicit anti-CSRF token** (grep for `csrf|xsrf` → zero matches). The defence is
**defence in depth across four independent mechanisms**:

1. **`SameSite=Lax` on both auth cookies.**
   Lax means the browser **does not attach cookies to cross-site `POST`/`PUT`/`DELETE`
   (non-top-level) requests**. Since *every* state-changing endpoint here is `POST`/`PATCH`/`DELETE`
   (there are no GET mutations — `logout`, `refresh`, `change-password` are all POST), a
   cross-origin `<form method=post>` or `fetch()` from `evil.com` arrives **cookie-less** ⇒ 401.
   `Lax` (vs `Strict`) is chosen so that clicking a link to `/markets` from an email still works.

2. **Content-Type is `application/json` + no CORS preflight bypass.**
   The client always sends `Content-Type: application/json` (`client.ts:300`). A simple
   cross-site `fetch` without that header can't produce a valid body the Pydantic `LoginRequest`
   will accept — and a request *with* `Content-Type: application/json` is **not a CORS-safelisted
   content type**, so the browser is forced to send a `preflight`.

3. **Strict CORS with credentials.**
   `app.py:212`: startup **raises `ValueError` if `CORS_ORIGINS` is empty or contains `*`** —
   you cannot run `allow_credentials=True` with a wildcard. Methods and headers are **explicit
   allowlists**, not `*`:
   ```python
   allow_methods=["GET","POST","PATCH","PUT","DELETE","OPTIONS"],
   allow_headers=["Authorization","Content-Type","Accept","X-Request-ID","Stripe-Signature"],
   ```
   The comment explains why: with `*` methods, *any* origin's script could drive state-changing
   endpoints using the victim's cookies. So `evil.com` never passes the preflight ⇒ the browser
   never sends the actual request.

4. **Origin allowlist enforcement inside the app** (`middleware.py:133`) — a second, independent
   check beyond the CORS middleware: **in every environment** (not just production), any request
   bearing an `Origin` not in `ALLOWED_ORIGINS ∪ CORS_ORIGINS` (localhost/127.0.0.1 always allowed)
   is rejected **403 `ORIGIN_NOT_ALLOWED`** before it reaches a handler. So a misconfigured reverse
   proxy, a staging box, or a non-browser client replaying a forged Origin doesn't get through —
   and because the set is the union of the two origin settings, editing one can't silently break
   requests from our own front end. Clients that send no `Origin` (curl, webhooks, same-origin GET)
   are untouched: they are covered by the SameSite and content-type rules instead.

Plus: `form-action 'self'` in CSP stops a hijacked form from posting anywhere, and the
`Permissions-Policy` header disables `payment=`/`usb=` etc.

> **Residual note for a viva:** the model relies on `SameSite=Lax` rather than a synchroniser
> token. That is a legitimate, widely-used design for SPA + JSON APIs, but it would be worth
> stating that a **subdomain XSS or a same-site (not cross-site) attacker** is the threat it does
> *not* cover — and that the JSON content type + Origin check are what close that gap.

---

## 10. Authorization

- `get_current_user()` (required) vs `get_optional_user()` (a bad/revoked/expired token is
  treated as anonymous, not an error) — so public market reads work logged-out.
- `_load_user()` checks in order: `sub` present → `type == "access"` (a refresh token can't be
  used as an access token) → `jti` not blacklisted → user exists → `user.is_active` → session valid.
  **Websocket handshakes run the identical chain** through `deps.authenticate_token()`, so a token
  killed by logout, logout-all or a session revocation dies at the WS upgrade too — not just on the
  next HTTP request.
- **Admin**: `_get_admin_user()` (`admin.py:37`) raises 403 unless `user.is_admin`. Also enforced
  ad-hoc in `flags.py`, `disputes.py`, `wallet.py` (withdraw confirm), `treasury.py`,
  `markets.py` (resolve/approve). Ban/unban refuses to ban another admin.
- **Ownership**: `DELETE /auth/sessions/{id}` filters `Session.user_id == user.id`; comments,
  orders, positions are always queried scoped to `user.id`.

---

## 11. Token revocation / blacklist

- Logout blacklists the **`jti`** in Redis (`blacklist:{jti}`) with TTL = remaining access-token
  life (≤15 min), so a stolen token dies on logout rather than at expiry.
- **Asymmetric failure policy** (`deps.py:96-128`):
  - blacklist **read** fails **open** in development (keep the dev loop alive) but **closed** in
    production (Redis down ⇒ deny — a revoked token must not be admitted).
  - blacklist **write** fails **closed** everywhere (logout aborts rather than silently leaving a
    live token).
- Because `_validate_session` also runs, session revocation is the primary, always-on guard even
  if Redis is down.

---

## 12. Honest gaps — status

**Fixed (with regression tests in `tests/test_security_fixes.py`):**

| # | Was | Fix | Test |
|---|---|---|---|
| 1 | WebSocket auth did `jwt.decode` **only** — skipped blacklist + `_validate_session` | `verify_ws_token` now calls `deps.authenticate_token()`, the exact HTTP chain (type, jti blacklist, user active, session) and **fails closed** on any DB error | `test_websocket_rejects_revoked_session`, `..._blacklisted_token` |
| 3 | XFF honoured after only a warning when `TRUSTED_PROXY_IPS` empty | Fail-closed: XFF is ignored unless the direct peer is a configured proxy; the duplicate copy in `api/auth.py` now delegates to the single implementation | `test_xff_ignored_without_trusted_proxy`, `test_xff_honoured_from_configured_proxy` |
| 4 | Comment claimed a "24 h absolute cap" while `config.py` set 30 d | Comment and code now agree on the 30 d TTL and state precisely what the check does **not** cover (see §1 note) | — |
| 6 | OTP plaintext written to Redis next to its hash | Redis stores the bare HMAC only; verification re-hashes the submitted code (legacy `code:hash` readable for its remaining ≤10 min TTL) | `test_otp_plaintext_never_stored_in_redis` |
| 7 | No bcrypt work when the user is absent | `dummy_password_hash()` (cached bcrypt of a random secret) is verified against on the unknown-email path | `test_dummy_password_hash_is_cached_bcrypt` |
| 10 | Origin allowlist only ran when `app_env == "production"` | Runs in **every** environment, against `ALLOWED_ORIGINS ∪ CORS_ORIGINS` | `test_origin_allowlist_applies_outside_production` |
| 2 | WS accepted `?token=` in the query string by default | Gated behind `ws_allow_query_token` (`WS_ALLOW_QUERY_TOKEN`, **default false**). Cookies are the supported path — host-scoped, not port-scoped, so `localhost:3000 → localhost:8000` and `app → api.example.com` both work. A `?token=` probe now closes with 1008 | `test_websocket_query_token_is_gated_off_by_default` (rejects a *valid* token in the query, accepts the same token as a cookie) |
| 5 | Register returned `409 "account already exists"` for a verified email | Uniform `200 {email, status: pending_verification}` + message `"Check your email to continue"` for all three cases; the owner is told by email instead (throttled 10 min). The response no longer carries an id, so it cannot differ between paths | `test_register_duplicate_email_is_not_enumerable` (compares both responses key by key) |
| 11 | No absolute cap across refresh rotations | Redis `refresh_chain:{sha256}` deadline set at login and inherited by every rotation (`refresh_chain_max_seconds`, default 30 d); past it every token and session is revoked | `test_refresh_rotation_inherits_the_chain_deadline`, `test_refresh_chain_stops_at_the_absolute_deadline` |
| 12 | `/auth/refresh` compared issuance time to `now` — true for every token — so **every refresh returned 401** | Check rewritten to mean what it says; the chain deadline from row 11 is the real bound | the two tests above (rotation succeeds, then the chain stops) |

Two trading-logic defects found alongside these (see `docs/trading-engine.md`): AMM BUY fills wrote
no `Trade` row (`remaining_shares` is pinned to `0` for buys — now keyed off `amm_shares`), and
`market.total_volume` added share counts for sells next to USDC for buys (now always USDC);
`initial_probability` seeded the pool inverted. Covered by `test_amm_buy_writes_trade_row_and_usdc_volume`
and `test_create_market_initial_probability_is_not_inverted`.

**Remaining — accepted by design, state them openly:**

| # | Gap | Location | Why it stays |
|---|---|---|---|
| 8 | Blacklist **fails open** outside production | `deps.py` (`_BLACKLIST_FAIL_OPEN`) | Dev/staging convenience; production fails closed (Redis down ⇒ deny). Startup now logs a warning naming the consequence (`app_env=…: token blacklist checks FAIL OPEN…`) so nobody discovers it during an incident. |
| 9 | `SameSite=Lax`, no synchroniser token | `deps.py` (`set_auth_cookies`) | Standard SPA+JSON design; `Lax` is needed so emailed links still work. The un-covered threat is a same-site (subdomain) attacker — closed by the JSON content-type + Origin allowlist, not by a token. |
| 13 | `WS_ALLOW_QUERY_TOKEN=true` (opt-in) puts a live JWT in a URL | `config.py` | Only if someone enables it deliberately, for a non-browser client that cannot store a cookie. The shipped default is `false`; URLs end up in proxy logs, history and `Referer`. |

---

## 13. One-paragraph summary

Authentication is **cookie-based JWT with server-side session binding**: a 15-minute HS256 access
token and a 30-day rotating refresh token are delivered as `HttpOnly; SameSite=Lax; Secure-in-prod`
cookies, and the access token carries a `sid` claim that must match a live, non-revoked `sessions`
row — which is what makes logout, per-device revocation and logout-all effective immediately rather
than at token expiry. Refresh tokens are stored only as SHA-256 hashes, rotated on every use, bound
to the device's user-agent, and **reuse of a rotated token is treated as theft and revokes every
session**. Passwords are bcrypt-hashed behind a complexity policy; 2FA is RFC-6238 TOTP with the
secret Fernet-encrypted under a dedicated key; email verification, magic codes and password reset
all use single-use 8-digit CSPRNG OTPs stored as HMACs in Redis with a 5-send/5-verify atomic
brute-force cap. Every unauthenticated endpoint sits behind a Redis Lua sliding-window limiter plus
exponential progressive friction, with client IPs derived only from trusted proxies. **SQL
injection** is impossible by construction — every value is an ORM bind parameter (the four raw
`text()` blocks use `:name` binds, `ORDER BY` is whitelisted, and `ilike` patterns escape
wildcards). **XSS** is prevented by React's default escaping (zero raw-HTML sinks in the codebase),
a strict CSP with `object-src 'none'`/`frame-ancestors 'none'` on both apps, `nosniff`, and
HttpOnly cookies so even injected script can't read a token. **CSRF** is prevented by
`SameSite=Lax` cookies + mandatory `application/json` (which forces a preflight) + an explicit
non-wildcard CORS allowlist of origins/methods/headers with `allow_credentials` + an in-app
`Origin` allowlist that 403s unknown origins **in every environment** — four independent layers,
any one of which is sufficient. The websocket upgrade runs the same token chain as HTTP, so
revocation is exact across both transports. Residual risks are documented rather than hidden: the
blacklist fails open outside production (and says so at startup), `SameSite=Lax` + JSON + the
Origin allowlist — not a synchroniser token — carry the CSRF story, and the WebSocket will accept
`?token=` only if `WS_ALLOW_QUERY_TOKEN=true` is set deliberately. Registration answers one
uniform response whether or not the address exists, and a login chain cannot outlive
`refresh_chain_max_seconds` no matter how often it refreshes.
