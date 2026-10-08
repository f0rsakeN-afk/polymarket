# Frontend Architecture — Next.js 16, React 19, Turborepo

Everything about the client: the monorepo, the routing model, the data layer, the WebSocket client,
session handling, the chart system, and the honest gaps.

> Written from `frontend/apps/web/**` and `frontend/packages/**`. Versions are read from
> `package.json` / `bun.lock`, never recalled. Claims are verified — several unflattering ones are
> included on purpose (§10, §11).

---

## 0. Stack at a glance

| Concern | Choice | Version |
|---|---|---|
| Framework | **Next.js** (App Router) | `^16.3.3` (resolved 16.3.3) |
| UI runtime | **React** / React DOM | `19.2.8` |
| Language | TypeScript | `^7.0.2` root/web, `^5` (→5.9.3) in `packages/ui` |
| Monorepo | **Turborepo** | `^2.11.2` |
| Package manager | **Bun** | `packageManager: bun@1.3.14` |
| Server-state library | **TanStack React Query** | `^5.103.1` |
| Forms | react-hook-form + zod | `^7.88.0` / `^4.6.5` |
| Styling | **Tailwind CSS v4** + CSS vars | `@tailwindcss/postcss ^4.3.3` |
| Component primitives | **Base UI** + shadcn conventions | `@base-ui/react ^1.6.0` |
| Charts | visx + d3 | `@visx/* @4.0.1-alpha.0` |
| Tests | **none** | — (§10) |

**A note on Next 16:** `frontend/AGENTS.md:2-4` warns *"This is NOT the Next.js you know … Read the
relevant guide in `node_modules/next/dist/docs/` before writing any code."* The concrete symptom in
this repo is `apps/web/proxy.ts` — **middleware has been renamed to `proxy.ts`**, exporting
`proxy(request)` rather than `middleware()`. If you are asked "what did Next 16 change for you?",
that is the concrete answer.

---

## 1. Monorepo layout

```
frontend/
├── package.json          root workspace; scripts delegate to turbo
├── turbo.json            task graph + caching
├── bun.lock              lockfile
├── apps/web/             the application  (@workspace/web → "web")
├── packages/ui/          design system + chart system (@workspace/ui)
├── packages/eslint-config/
└── packages/typescript-config/
```

`workspaces: ["apps/*", "packages/*"]`, `engines.node >= 20`.

### 1.1 Turborepo task graph (`turbo.json`)

| Task | `dependsOn` | `inputs` | `outputs` |
|---|---|---|---|
| `build` | `["^build"]` | `$TURBO_DEFAULT$`, `.env*` | `.next/**`, excluding `.next/cache/**` |
| `lint` / `format` / `typecheck` | `["^lint"]` etc. | — | — |
| `dev` | — | — | `cache: false`, `persistent: true` |

`globalEnv: ["NODE_ENV"]` — because `next.config.ts` branches on it, so it has to bust the cache.
**There is no `test` task** (§10).

Root scripts are pure pass-throughs: `build`/`dev`/`lint`/`format`/`typecheck` → `turbo <task>`.
Docker runs `bunx turbo build --filter=web` (`Dockerfile:33`), which is how the single app is built
without building a package that has nothing to build.

### 1.2 `packages/ui` has no build step — and that is deliberate

`packages/ui/package.json:6-10` defines **no `build` or `dev` script**. It is consumed as raw
TypeScript source, which is why:

- `next.config.ts:39` sets `transpilePackages: ["@workspace/ui"]`, and
- `apps/web/tsconfig.json:7` maps `"@workspace/ui/*" → ["../../packages/ui/src/*"]`.

**Why this is the right call:** no watch step, no build cache to invalidate, no dist folder, and
edits to a component are reflected on the next Next.js compile. The cost is that Next's bundler must
compile the package on every build — which `transpilePackages` handles.

Export map (`packages/ui/package.json:65-71`): `./globals.css`, `./postcss.config`, `./lib/*`,
`./components/*`, `./hooks/*`. (The last one is dead — that directory contains only `.gitkeep`.)

### 1.3 TypeScript config

Root extends `@workspace/typescript-config/base.json`: `strict: true`,
**`noUncheckedIndexedAccess: true`**, `isolatedModules: true`, `NodeNext`, target ES2022.
`nextjs.json` overrides to `Bundler` resolution + `jsx: preserve` + `noEmit`.

`noUncheckedIndexedAccess` is a deliberate strictness choice: indexing an array yields
`T | undefined`, so you must handle the miss. Say that if asked why the codebase has so many
guard clauses.

**Two compilers in one workspace:** TS `7.0.2` at the root and in `apps/web`, TS `^5` (→ 5.9.3) in
`packages/ui` (`bun.lock:1540,1676,1678`). A genuine inconsistency worth naming.

### 1.4 ESLint

`apps/web/eslint.config.js` is 4 lines re-exporting `nextJsConfig`, which composes
`js.recommended` + `eslint-config-prettier` + `typescript-eslint` + `react` +
`@next/eslint-plugin-next` (recommended + core-web-vitals) + `react-hooks`.

Four react-hooks v6 compiler rules are downgraded to `"warn"` with a comment admitting *"~65
pre-existing hits in the chart package"* (`packages/eslint-config/next.js:49-59`). So the honest
answer to "is lint clean?" is: **warnings only in the chart package, errors elsewhere** — which is
stricter than the frontend README's "warnings only today".

`frontend/.eslintrc.js` also exists in the legacy format — **inert** under ESLint 9 flat config.

---

## 2. Routing — 27 pages in three route groups

Route groups let you share a layout without changing the URL. Three of them:

| Group | Layout | `robots` | Routes |
|---|---|---|---|
| `(plain)` | bare `<main>`, no header/footer | `index: false, follow: false` | `/login`, `/signup`, `/forgot-password`, `/reset-password` |
| `(public)` | header + footer | indexable | `/markets`, `/markets/[slug]`, `/trades` |
| `(app)` | header + footer | mostly `noindex` | `/`, `/portfolio`, `/orders`, `/positions`, `/transactions`, `/wallet`, `/notifications`, `/settings/**`, `/faq`, `/docs`, `/support`, `/legal{,/terms,/privacy,/risk}` |

Plus: `app/error.tsx` (route error boundary), `app/not-found.tsx`, `app/api/og/route.tsx` (the only
API route — an edge-runtime 1200×630 OpenGraph image via `ImageResponse`), and `sitemap.ts` /
`robots.ts`.

**No `loading.tsx` anywhere** — loading UX is `Suspense` + hand-rolled skeletons instead. **No
`global-error.tsx`**, so a root-layout throw is not caught by `app/error.tsx`.

### 2.1 Middleware → `proxy.ts` (183 lines)

```ts
export const config = {
  matcher: ["/((?!_next/static|_next/image|favicon.ico|opengraph-image).*)"],
}
export function proxy(request: NextRequest) { ... }
```

Runtime note in the file (`:5-8`): *"Runs on the Node.js runtime (Next 16: the `edge` runtime is not
supported here)."*

Three path classes (`proxy.ts:20-22`):

```ts
PUBLIC_PATHS    = ["/", "/markets", "/trades", "/faq", "/docs", "/legal", "/support"]
PROTECTED_PATHS = ["/portfolio", "/orders", "/positions", "/transactions", "/wallet", "/settings"]
AUTH_PATHS      = ["/login", "/signup", "/forgot-password", "/reset-password"]
```

Logic, in order:
1. If the path is protected, validate the session **before** the public fast-path (`:129-131`) so a
   lookalike URL can't skip auth. Failure → `/login?next=<pathname>`.
2. On success it **re-validates the backend payload** with a UUID regex and an email regex
   (`:141-147`) — a malformed token is treated as no session.
3. If the path is an auth path and you're already signed in → redirect to `next`, hardened:
   `rawNext.startsWith("/") && !rawNext.startsWith("//")` (`:157-159`). **That two-line check is the
   open-redirect defence** — `//evil.com` is protocol-relative, so a naive `startsWith("/")` check
   would happily redirect off-site.
4. On every response it re-applies security headers (`:105-113`).

**Session validation with cookie replay.** It reads the `access_token` cookie and calls
`GET /api/v1/auth/me` with `cache: "no-store"` (`:54-62`). On 401 it falls back to
`POST /api/v1/auth/refresh` with the `refresh_token` cookie, and **replays every `Set-Cookie` onto
its own response** (`:42-52, 90-99`). The header comment explains why this is mandatory: *"the
proxy's cookies are not the browser's"* — without replaying, the rotated tokens would be lost and
every navigation would refresh again.

**Gap worth naming:** `/notifications` is **not** in `PROTECTED_PATHS`, yet the page needs auth and
renders `null` without a user (`(app)/notifications/page.tsx:180`). An anonymous visitor reaches it
and sees an empty page rather than a login redirect.

---

## 3. Server vs client components — and why the split is lopsided

Measured: **80 of 141** `.ts`/`.tsx` files under `apps/web` start with `'use client'`. **All 49**
files under `components/` are client components. Only ~10 files under `app/` are server components,
and only **one** of them fetches data.

### 3.1 The one data-fetching server component

`app/(app)/page.tsx` is the homepage, `async`, `export const dynamic = "force-dynamic"` (`:12`):

```ts
const [markets, closingSoon, trades] = await Promise.all([
  marketsApi.list(...), marketsApi.list({sort: 'closing_soon'}), tradesApi.list(...)
]);
```
with `.catch(() => undefined)` on each for graceful degradation, then the results are passed to the
client as `initialData` seeds. The comment states the intent: *"The three content queries run ON THE
SERVER in parallel (one fast backend hop, no client waterfall) and seed React Query via initialData —
first paint already contains real markets, which is what LCP measures."*

That is a correct application of the parallel-fetch + seed pattern, and it's the one place it pays
off.

### 3.2 Two consequences you should volunteer

1. **The market detail page server-renders no market data at all.**
   `(public)/markets/[slug]/page.tsx` doesn't even accept `params` — the slug is read client-side
   with `useParams()` (`MarketDetailClient.tsx:11`), and `generateMetadata()` returns generic
   hardcoded strings (`:3-8`). So per-market `<title>`/`<description>` never reflect the actual
   question. *Server components* was the right default; *dynamic-route data fetching* was not
   applied consistently.
2. **The server fetch does not forward cookies.** `(app)/page.tsx` reuses the client `lib/api/*`
   wrappers, whose `fetch` carries `credentials: "include"` — but Next.js does **not** forward
   browser cookies to a `fetch` issued from a server component, and **no `cookies()` call exists
   anywhere in the app**. So the homepage's SSR data is effectively anonymous. Harmless for `/`
   (public markets and trades), but it means the "server-first" pattern cannot be reused for an
   authenticated route without adding explicit cookie forwarding. Know this before you're asked.

No `HydrationBoundary` / `dehydrate` anywhere — seeds are passed as **props** and fed to
`initialData`, so React Query's cache is built twice by two mechanisms rather than dehydrated once.
Functional, not idiomatic.

---

## 4. The data layer

### 4.1 Three clean layers

```
components/**  →  hooks/api/*  (React Query)
hooks/api/*    →  lib/api/*    (typed thin wrappers)
lib/api/*      →  lib/api/client.ts   (the ONLY place fetch() is called)
```

`lib/api/` has 17 files (`client.ts`, `queryKeys.ts`, then one per domain); `hooks/api/` has 16 hook
modules plus an `index.ts` barrel. Two overlapping barrels exist — `hooks/api/index.ts`
(`export *`) and `hooks/index.ts` (explicit re-exports with a hand-maintained comment list of hook
names). Minor inconsistency.

### 4.2 `lib/api/client.ts` (416 lines) — the heart of the client

This is the most interesting file in the frontend and the most likely to be probed.

**Base URL** (`lib/config.ts`, 27 lines) — three env vars, normalised:
```ts
apiOrigin = normalizeBase(process.env.NEXT_PUBLIC_API_URL, "http://localhost:8000")
wsOrigin  = normalizeBase(process.env.NEXT_PUBLIC_WS_URL,  "ws://localhost:8000")
siteUrl   = normalizeBase(process.env.NEXT_PUBLIC_SITE_URL, apiOrigin)
```
`normalizeBase` strips trailing slashes **and** a trailing `/api/v1`, so a misconfigured value can
never produce `//api/v1/...`. These are inlined at Docker build time (`Dockerfile:27-31`), so
changing them requires a rebuild.

**Error normalisation** — `extractMessage()` (`:31-76`) handles **four** documented backend shapes:
1. `AppException`/handlers → `{success:false, error, error_code, details?}`
2. FastAPI validation → `{detail:[{loc,msg}]}`
3. rate-limit middleware → `{error_code:"RATE_LIMIT_EXCEEDED", retry_after}` — checked **first** so
   `retry_after` survives
4. origin middleware → `{error_code:"ORIGIN_NOT_ALLOWED", message}`

Field-level validation detail is **surfaced, not swallowed**: `details.errors` is appended as
`"field: message · field: message"` (`:54-65`). `apiErrorMessage()` (`:87-98`) then maps
`AbortError`/`TimeoutError` → "The request timed out", network `TypeError` → "Can't reach the
server", otherwise prefers the backend's own message.

**Retries** — `fetchWithRetry()` (`:149-196`): default `retries = 3`, `timeout = 10_000`, per-attempt
`AbortController`. Retries on `429` (honouring `Retry-After`, else `min(1000·2^n, 30_000)`), on
`5xx`, and on network throw. **It does not retry 4xx** — correct, since a validation error won't fix
itself.

**The single-flight refresh** — the most sophisticated part:

```ts
type SessionState = "unknown" | "active" | "none"
let sessionState, refreshPromise, refreshBlockedUntil
const REFRESH_COOLDOWN_MS = 30_000
```
- `refreshSession()` (`:280-287`) is **single-flight** — ten parallel 401s share one
  `POST /auth/refresh`.
- `doRefresh()` (`:254-277`) treats `401/403` as a **verdict** → `markSessionEnded()`; treats
  `429/5xx`/throw as **inconclusive** → 30s cooldown with state preserved.

The 26-line comment block at `:207-226` records the exact bug this fixed, and it's a great answer:
*an anonymous page view used to produce one `/auth/refresh` per 401 until the endpoint's per-minute
cap answered 429 and the tab rate-limited itself.* The distinction between "the session is gone" and
"the server is briefly unhealthy" is the whole point — conflating them logs users out during an
outage.

**GET de-duplication** — `pendingRequests: Map<string, Promise>` keyed
`` `${method}:${path}:${JSON.stringify(body ?? null)}` `` (`:314, 336`). In-flight GETs share one
promise. (Note: writes into the map happen for GET **and** DELETE (`:394-396`), but lookups are
GET-only (`:338`), so DELETE entries are stored and never read — harmless, but dead weight.)

**Credentials:** `credentials: "include"` everywhere. **No `Authorization` header is ever set** — auth
is 100% cookie-based (§6).

**Dead export:** `parseResponse()` (`:127-141`) is exported and never called; hooks unwrap
`.then(r => r.data)` by hand.

### 4.3 React Query configuration

Global defaults (`components/providers.tsx:12-19`):
```ts
staleTime: 30_000, gcTime: 5 * 60_000, retry: 1, refetchOnWindowFocus: false
```

`staleTime` is then tuned per query — and **the tuning is the design**:

| Query | `staleTime` | Reasoning |
|---|---|---|
| order book | 5s | changes constantly, and the socket pushes updates anyway |
| trades | 10s | near-realtime tape |
| markets / market | 30s | matches the backend's own cache TTLs |
| activity, notifications | 15s | |
| FAQs, related, prefs | 60s | almost static |
| price history | 300s | backend snapshots every 5 minutes |
| `useCurrentUser` | `staleTime: 0, retry: false` | auth state must never be cached |

`refetchInterval: 300_000` on price history only.

**Pagination — two styles, both mapped correctly.** Offset/page for markets, positions,
transactions, notifications. **Keyset/cursor** for the trade tapes and orders, with the comment
*"Backend is keyset-paginated: `cursor`, never `page`."* (`use-markets.ts:69-79`,
`use-orders.ts:19-22`). That's the client correctly mirroring the backend's
`(executed_at, id)` cursor.

`queryKeys.ts` (73 lines) is a typed key factory with a documented subtlety (`:15-22`): infinite and
non-infinite variants of the same feed must be **distinct** keys, achieved with a `"simple"` segment
so prefix invalidations still match.

**Optimistic updates: zero.** There is exactly one `setQueryData` in the whole app
(`market-detail.tsx:166`) and it is a *WebSocket* cache write, not an optimistic mutation. Every
mutation uses invalidate-after-success. The closest thing to an optimistic update is the
notification bell's hand-rolled `readIds: Set` overlay (`notification-bell.tsx:143-190`).

Be ready to justify this: for **money-moving** operations, invalidate-after-success is arguably the
*correct* choice, because a wrong optimistic balance on a trading screen is worse than a 200ms wait.

---

## 5. Realtime — `hooks/use-market-socket.tsx` (410 lines)

### 5.1 Architecture: a module-level singleton, not React state

```ts
interface SharedConnection {
  ws: WebSocket | null
  status: WSStatus
  subs: Map<string, MarketSub>        // per-market: {seq, handlers:Set, wsSubscribed}
  subLocks: Map<string, Promise<void>> // per-market mutex (promise chain)
  retries: number
  serverSubs: Set<string>
  statusHandlers: Set<MessageHandler>
  lastConnectedMarket: string | null
  gaveUp: boolean
  intentionalCloseSocket: WebSocket | null
}
let _conn: SharedConnection | null = null
```

**One WebSocket per browser tab; many subscribers.** If each component opened its own socket, a
market page with a chart, a book, a trade feed and a comments feed would hold four sockets — and the
server caps connections per IP at 50. A module singleton is the right answer.

`subscribe(marketId, handler) → unsubscribe` (`:264-319`): first subscriber connects; last one to
leave schedules a **deferred** close.

### 5.2 Auth on the socket: deliberately anonymous

```ts
const ws = new WebSocket(`${config.wsUrl}/ws/markets/${firstMarketId}`)
```
No token in the query string, no subprotocol. The rationale is documented at `:129-134`: market data
is public over REST, the socket pushes exactly that, so the server accepts an anonymous handshake;
the `access_token` cookie rides along automatically when there is a session. **Gating live prices
behind a login would deny them to logged-out visitors.**

This pairs with the server's tri-state `authenticate_ws_token` (`websocket/routes.py:31-69`):
`(None, False)` → anonymous allowed; `(user_id, True)` → valid; `(None, True)` → **presented and
invalid ⇒ reject**. The third case matters: without it, a revoked token would silently degrade to
anonymous instead of being refused.

The path is **market-scoped**, so the URL is rebuilt on reconnect to the most recently active market
(`:231-234`) — reconnecting to what the user is *looking at*, not the first thing they subscribed to.

### 5.3 Message handling

`onmessage` (`:173-203`) in order: `JSON.parse` in a silent `try/catch`; drop if no `market_id`;
**drop if no handler is registered**; `sub.seq++` (a sequence number to discard stale messages);
deliver to every handler **each in its own `try/catch`** so one throwing handler can't kill the
socket; then if `sub.seq` changed mid-iteration, `break` — a re-subscribe happened, so stop
delivering pre-resubscribe messages.

That per-handler isolation is a real design decision: with a fan-out `for` loop and no isolation, a
single bug in a chart handler would disconnect the whole page.

### 5.4 Reconnection

```ts
const MAX_RECONNECT_ATTEMPTS = 8
delay = Math.min(1000 * 2 ** retries, 30_000)
```
Capped at 8 with the documented reason (`:46-53`): backoff stretches to 30s, so 8 attempts ≈ 2
minutes — *"without a ceiling an endpoint that is down is retried for the lifetime of the tab"*.
On exceeding it, `gaveUp = true` and status becomes `"error"` (a visible state, not a silent hang).

**Sleep/wake recovery** (`:337-363`): listeners on `window "online"` and
`document "visibilitychange"`; on recovery, if there are subscriptions and the socket is gone or
`gaveUp`, reset the counters and reconnect. Rationale at `:333-336`: a laptop resuming from sleep
drops the socket silently, and those are the only signals available.

**Strict Mode handling** (`:296-316`): the close is deferred with `setTimeout(…, 0)` and re-checks
`subs.size > 0`. Strict Mode double-mounts in dev; without the deferral the socket would close and
immediately reopen on every mount.

### 5.5 Two bugs that were found and fixed — quote these

The file documents both fixes in place, which is exactly what a panel wants to hear:

- **Stale `onclose` from a superseded socket.** `close()` is async, so a socket already replaced fires
  `onclose` after its successor is live; nulling `conn.ws` unconditionally made the live socket
  untracked and the next subscribe opened a second one — *"two sockets, both receiving, and the flap
  repeated on every subscribe/unsubscribe cycle."* Fix: `if (conn.ws !== ws) return` (`:206-212`).
- **A boolean couldn't express "intentional close".** The flag was shared across sockets, so a late
  close read a value its successor had already reset. Fix: store the **socket identity**
  (`intentionalCloseSocket: WebSocket | null`) instead of a boolean (`:40-41, 150-153, 217-220`).

Both are the same lesson: *identity, not a flag, when lifecycle events can arrive out of order.*

### Two more fixed here — a busy-wait mutex and a socket that leaked on hot reload

**The per-market mutex was a spin-wait:**
```ts
while (locked) { await new Promise(r => setTimeout(r, 5)); locked = conn.subLocks.get(marketId) }
```
That burns a 5 ms timer *per contended market* and occupies the event loop for the whole wait — a
cost paid for something that should be free. It is now a promise chain:
```ts
function withMarketLock<T>(conn, marketId, fn) {
  const prev = conn.subLocks.get(marketId) ?? Promise.resolve()
  const run = prev.then(fn, fn)   // run regardless of how the previous link settled
  ...
}
```
`fn` is passed as *both* handlers so one throwing caller can't poison the chain and deadlock every
later caller, and the map entry is dropped once it's the tail so it doesn't grow unbounded. One
microtask turn instead of a timer.

**Nothing tore the socket down on HMR or unload.** `_conn` is module scope — that is *what makes it
per-tab* — but it also means a hot reload creates a new `_conn = null` while the old socket is still
open and still referenced by the old module's closures. The browser keeps the TCP connection; the
server keeps the file descriptor and the slot in that IP's counter. A handful of edits and you have
leaked sockets the app can no longer reference. Fixed with a `hot.dispose` hook and a `pagehide`
listener, both of which close explicitly (`teardownSocket`) rather than trusting TCP teardown.

**Three bugs found while writing that fix, all worth recording:**

1. *Nulling the module variable on `pagehide` was wrong.* The provider captures the connection
   object in a `useRef` at mount, so replacing the module variable leaves the provider pointing at a
   dead connection while any newly-mounted component gets a **second, fresh** one — two connections,
   one orphaned, which is exactly the flapping this design exists to prevent. `teardownSocket` now
   nulls `_conn` **only on HMR**, where the whole module is being replaced anyway.
2. *Clearing `subs` would have been wrong too.* Consumers hold handlers in `subs`; emptying it would
   strand every mounted component — handlers registered, but the socket they route through gone,
   giving silent dead updates. Only `ws` is cleared, so the next `subscribe` takes the normal
   `if (!c.ws) connect()` path and recovery needs no second code path.
3. *The reconnect timer had to be cleared before anything else*, or a pending reconnect would
   resurrect the socket deliberately closed a moment earlier.

Full reference: `use-market-socket.tsx` (`teardownSocket`, near the end of the file).

> **A regression caught while making this change, worth remembering:** the obvious "improvement" of
> adding a `readyState === OPEN` guard to `wsSubscribe` would have been a **new bug**. If a second
> market is subscribed while the socket is still `CONNECTING`, `sendWs` no-ops — but the market must
> still be recorded in `serverSubs`, because `onopen` replays that set. Returning early would drop
> that market permanently, since the socket URL only ever names the *first* market. The lesson:
> the "socket isn't ready, skip it" intuition is wrong when a later `onopen` is responsible for
> replaying the intent.

### 5.6 Events handled client-side

`market:price_update`, `trade:new`, `market:resolved`, `orderbook:update`, `comment:new` /
`updated` / `deleted`, `notification`, `alert:triggered`, `order:fill`, `position:update`.

Two WS-driven cache decisions worth naming:
- `orderbook:update` writes the **wrapped** shape `{success:true, data:{outcomes}}` so the socket
  write and `getOrderBook` produce an identical value (`market-detail.tsx:161-167`). Getting this
  wrong causes a shape mismatch that only appears on the first live tick.
- `market:resolved` invalidates `market(slug)`, `markets()` **and** `positions()` (`:149-151`) —
  resolution changes both the market and the user's PnL.

### 5.7 The second socket: `hooks/use-user-socket.ts` (132 lines)

An independent implementation for `/ws/notifications/{userId}` — same shape, same 8-attempt cap,
same backoff — with a `mountedRef` guard protecting every async callback (which prevents
setState-after-unmount). It returns `{status, send}`, and **`send` is never called**.

The backend also serves `/ws/trades` (a public global tape). **No client code connects to it.**

---

## 6. Auth on the client

### 6.1 Tokens live only in HttpOnly cookies

Grep across `apps/web` for `localStorage|sessionStorage|document.cookie` returns **zero matches**.
The backend sets `access_token` and `refresh_token` as HttpOnly cookies; JS cannot read them.

This is the single most important security decision in the frontend. Because the client literally
cannot read the tokens, **XSS cannot steal the session** — it can only make requests as the user.
Compare a `localStorage` token, which any injected script reads and exfiltrates in one line.

The consequence the code handles carefully: since JS can't check, the app is *told* when a session
exists. `signedIn()` calls `markSessionActive()` after any endpoint that sets cookies
(`lib/api/auth.ts:67-72`), `signedInUnlessChallenged()` does **not** on a `requires_2fa` challenge
(`:79-86`), and logout uses `.finally(markSessionEnded)` because cookies clear on the way out
regardless (`:108-111`).

### 6.2 Route protection — three layers, no guard component

1. **`proxy.ts`** — validate, redirect to `/login?next=…`, replay rotated cookies.
2. **Query gating** — `useAuthGate()` (`hooks/api/use-auth-gate.ts:17-20`) sets `enabled: !!user` on
   every private query, so an anonymous visitor never fires a request that would 401.
   `useLoadingWithGate` (`:29-34`) stops an authenticated page flashing its empty state while
   `/auth/me` is in flight.
   The docstring records why it exists: *"trade-form sits on the **public** market page, so an
   ungated wallet fetch produced `No access token provided` on every anonymous page view."*
3. **401 handling in the client** — refresh, replay once, then `redirectToLogin()`, which **skips
   public paths** (`:296-310`) so anonymous visitors get an empty state instead of a redirect loop.

There is no route-guard component and no redirecting `useEffect`. Protection is exactly those three
mechanisms plus `return null if no user`.

### 6.3 Login is a 3-step state machine

`components/auth/login-form.tsx` (559 lines) with `flow: "password" | "magic" | null`:

- **Email step** — react-hook-form + `zodResolver(emailSchema)`.
- **Password step** — optional TOTP field (`inputMode="numeric"`, `maxLength={6}`,
  `autoComplete="one-time-code"`). The `next` param is open-redirect-hardened identically to the
  proxy (`:182-186`).
- **Magic-link step** — OTP with a 60s resend cooldown, auto-submit at 6 characters, and a
  **second-stage TOTP step**: a `200 {requires_2fa}` returns a `partial_token` which is then
  exchanged at `verifyMagic2fa`.

The page is wrapped in `<Suspense>` because the form reads `useSearchParams()`.

### 6.4 One definition of the current-user query

`hooks/use-auth.ts` is 21 lines and carries an explicit warning:
```ts
// Single source of truth: MUST be queryKeys.me() so profile mutations
// (verify-email / password change / 2FA toggle) invalidate the same cache entry.
```
`hooks/api/use-auth.ts:18-22` documents the same history: *"It used to be redefined here with looser
options: two hooks, two behaviours, same cache key — whoever imported which one got a different
refetch policy."* A duplicate query definition with the same key and different options is a subtle,
expensive class of bug; saying you found and closed it is worth points.

---

## 7. `packages/ui` — design system & chart system

### 7.1 Styling: Tailwind v4, CSS-first, `oklch()`

There is **no `tailwind.config.js`** — v4 is configured in CSS:
```css
@import "tailwindcss";
@import "tw-animate-css";
@import "shadcn/tailwind.css";
@custom-variant dark (&:is(.dark *));
@source "../../../apps/**/*.{ts,tsx}";
@source "../**/*.{ts,tsx}";
```
`@source` is how the app's classes are discovered from another package — without it every
`text-muted-foreground` in `apps/web` would be purged.

Tokens are CSS custom properties in **`oklch()`** (perceptually uniform), in `:root` and `.dark`
blocks. Chart theming is a **separate namespace** (`--chart-line-primary`, `--chart-grid`,
`--chart-tooltip-background`, `--chart-marker-*`, `--chart-scale-01…05`), mirrored in JS by
`chartCssVars` in `charts/chart-context.tsx:28-48`. That's why a chart re-themes correctly on dark
mode without re-rendering.

Dark mode is class-based via `next-themes` (`attribute="class"`, `defaultTheme="dark"`), plus a
custom `D`-key hotkey that skips while typing or when a modifier is held.

### 7.2 Base UI, not Radix — with shadcn conventions

`components.json` declares `"style": "base-mira"`, `rsc: true`, `cssVariables: true`,
`iconLibrary: "lucide"`. But the primitives are **Base UI**:
```ts
import { Button as ButtonPrimitive } from "@base-ui/react/button"   // button.tsx:1
```
So: **shadcn's copy-in ownership model, CSS variables, `cva` variants and per-file exports — on top
of Base UI primitives.** Say that precisely rather than "we use shadcn".

~50 components across form/input, overlays (dialog, sheet, drawer, popover, tooltip, dropdown,
command palette via `cmdk`), layout (card, table, scroll-area, resizable, sidebar), and data display
(badge, avatar, tabs, accordion, skeleton, spinner, `market-card`).

### 7.3 The chart system — 164 files, and only 4 are used

**Chart families implemented:** time-series line, area, **live line (streaming)**, composed
(line+area+bar), categorical bar (+ `bar-squares`), candlestick, scatter, **heatmap** (a
GitHub-contributions calendar), pie, ring/donut, radar, sankey, sunburst, choropleth, funnel, gauge,
and profit/loss. Five sub-packages: `tooltip/`, `legend/`, `sankey/`, `choropleth/`, `heatmap/`.

Built on **visx** (`@visx/*`, all pinned at `4.0.1-alpha.0` — alpha in production `dependencies`) plus
raw d3 (`d3-sankey`, `d3-geo`, `d3-shape`, `d3-scale`), `motion` for animation, and
`react-use-measure`.

> **The finding that will impress (or disarm) a panel:** only **4 of the 164 files** are imported by
> the application — `live-line-chart`, `live-line`, `live-x-axis`, `live-y-axis`. Candlestick, bar,
> area, line, composed, scatter, heatmap, pie, ring, radar, sankey, sunburst, choropleth, funnel,
> gauge and profit-loss are **fully implemented and entirely unexercised**. Even
> `lib/utils/chart.ts`'s `priceToOHLC` / `addPriceToOHLC` converters — which exist specifically to
> feed the candlestick chart from live prices — are never called.
>
> Two honest framings, and you should pick one deliberately: either *"the design system shipped a
> general-purpose chart library and the product currently needs one of them"* (true, and the code is
> real), or *"this is scaffolding I inherited and never needed"* (also true, if that's the history).
> What you must **not** say is "we use all of these charts".

### 7.4 `LiveLineChart` — the one that matters

The streaming chart the market page actually uses:

- **Window slicing uses a d3 bisector**, not a linear scan (`:204, 470-472`).
- **Tooltip values are interpolated**, not looked up — `interpolateAtTime()` binary-searches and
  linearly interpolates over visible points (`:178-202`), so the cursor reads a smooth value between
  ticks.
- A **rolling window** (default 30s) extends the domain by one tick so the line reaches the right
  edge and the axis always has a next tick (`:268-272, 480-491`).
- `computeTargetRange` pads by 15%, or 3% when `exaggerate` (`:139-140`).
- Dual-line mode via `yes_price`/`no_price`.
- The `<svg>` is **`aria-hidden="true"`** (`:601`) — see §9 for the trade-off.

It reuses `ChartProvider` and the same `LiveLine`/`LiveXAxis`/`LiveYAxis` children as the cartesian
charts, so streaming and static charts share one context contract.

---

## 8. Performance

`next.config.ts` has exactly **four** keys:
```ts
{ transpilePackages: ["@workspace/ui"], output: "standalone",
  experimental: { optimizePackageImports: ["lucide-react", "date-fns"] },
  async headers() { /* one rule for /(.*) */ } }
```

### 8.1 The single most important bundle decision

**All 9 `dynamic()` imports in the app are `{ ssr: false }`** — `LiveLineChart`, `LiveXAxis`,
`LiveYAxis`, `LiveLine`, `AlertDialog`, `AddLiquidityForm` in `market-detail.tsx:35-59`;
`LiveLineChart`/`LiveLine` in `trending-carousel-item.tsx`; `LazyTradeFeed` in
`home-page-content.tsx`.

The inline comment (`:29-30`) states it: *"visx/d3 chart code splits into its own chunk and never
SSR-renders — the detail page paints text/orderbook first, charts hydrate after."*

This is what keeps a 164-file charting library off the initial route chunk. It's also a genuine
SSR trade-off: the chart is never server-rendered, so there is a skeleton-then-hydrate moment.

`optimizePackageImports` targets `lucide-react` (13 consumers) and `date-fns` — the comment explains
the goal: barrel imports resolve to per-module chunks instead of dragging whole packages in.

### 8.2 Memoisation

`React.memo` on `WalletHero`, `PositionsSection`, `OrdersSection` (`portfolio/page.tsx:107,222,331`);
on `NotificationItem`, `NotificationSkeleton`, `EmptyState`; on `OutcomeButton`, `SideButton`,
`OutcomeOrderbook`; throughout `packages/ui/charts`. `useMemo` on every expensive derivation in
`market-detail.tsx` (`seedPoints`, `historicalPoints`, `priceHistory`, `outcomePrices`, `stats`,
`combinedTrades`, `chartColors`).

With a WebSocket pushing new points several times a second, memoisation isn't premature — it's load-
bearing.

### 8.3 `output: "standalone"` + a 3-stage Dockerfile

The runner stage copies only `.next/standalone`, `.next/static`, `public` (`Dockerfile:47-49`), runs
`node server.js` as the non-root `nextjs` user (`:41-45, 60`), sets `HOSTNAME=0.0.0.0`, and has a
health check on `GET /` (`:57-58`).

### 8.4 Image optimisation is not used — and correctly so

`next/image` is imported **nowhere**; there is no `images` config block. There are no raster images
in the app: the logo is an inline SVG, the favicon is an SVG, the OG image is generated at the edge
by `ImageResponse`, and the 2FA QR code is an inline `QRCodeSVG`.

So don't claim image optimisation as a feature — the honest answer is *"there was nothing to
optimise; every image is inline SVG or generated at the edge."*

---

## 9. Accessibility, i18n, error handling

### 9.1 Accessibility — real, not token

- **Skip link** in the root layout targeting `<main id="main-content" tabIndex={-1}>`, declared in
  all three group layouts.
- **ARIA live regions** for async state: `aria-live="polite" aria-atomic="true" role="status"` on
  the portfolio summary and notifications feed; `role="feed"` + `aria-label`; `role="alert"` on
  trade-form banners; `aria-busy` on the mark-all button.
- **WebSocket status is exposed, not just coloured** — `role="status" aria-label="WebSocket Live"`
  plus a visible "Live"/"Sync"/"Off" label.
- `aria-current="page"` on active nav links, `aria-pressed` on toggles, `aria-hidden` on decorative
  SVGs, focus-visible rings globally.
- Charts are `aria-hidden` with a compensating text label on the wrapper card
  (`aria-label="<question> — YES 62%, NO 38%"`).

**The gap to admit:** no data-table or ARIA alternative for any chart family, and the chart SVG is
`aria-hidden` with no adjacent summary. A screen-reader user gets the label but not the series.

### 9.2 i18n — none, and it's a non-goal

No `next-intl`, no locale routing, no message catalogues. `<html lang="en">` is hardcoded; every
string is an inline English literal, including the FAQ, terms, privacy policy and risk disclosure.
Formatting is `toLocaleDateString("en-US", …)`.

If asked *"how would you add another language?"*: externalise every literal behind a message
catalogue, add locale-aware routing and `lang` negotiation, and parameterise the `Intl` formatters
the chart package already uses. Don't claim any of it exists.

### 9.3 Error boundaries — three layers, one dead

1. `app/error.tsx` (23 lines, `"use client"`) — route-segment boundary with `{error, reset}`.
   **There is no `global-error.tsx`**, so a root-layout throw escapes it.
2. `components/error-boundary.tsx` (54 lines) — reusable class boundary with a `fallback` prop and a
   `reset` alias *"for shadscan detection"*. **It is exported and never mounted.**
3. `app/not-found.tsx` — the 404.

---

## 10. Testing — the honest answer

**There is no frontend test suite.** Verified four ways:

| Check | Result |
|---|---|
| `find` for `*.test.*` / `*.spec.*` under `apps`+`packages` | **0 files** |
| `grep vitest\|jest\|playwright\|@testing-library\|cypress` across every `package.json` | **0 matches** |
| `"test"` script in any `package.json` | **none** |
| `test` task in `turbo.json` | **absent** |

(`next@16.3.3` lists `@playwright/test` as an *optional peer dependency* — that's Next's own internal
e2e peer, not an installed runner.)

**Why this is the most important gap to name first:** the two highest-risk files in the frontend are
`lib/api/client.ts` (~200 lines of 401/refresh/backoff state machine) and
`use-market-socket.tsx` (reconnect, single-flight subscription, Strict Mode deferral). Both are
untested. Both are defended by **dense explanatory comments** documenting the exact bug each section
prevents — which is a reasonable substitute for tests but is not equivalent, and saying so is better
than being caught out.

**The two bugs fixed in `use-market-socket.tsx`** (§5.5) are exactly the kind of thing a test would
have caught. That is a good, honest framing: *"the comments are archaeology from bugs; the fix is to
turn each comment into a test."*

The backend, by contrast, has **22 test files / 387 test functions** — so the correct framing is
*"coverage is deep on the money and concurrency paths, and absent on the client"*, not "we don't test".

---

## 11. Dead code, inconsistencies and content bugs

> **Since the last review, three items here were fixed rather than merely listed:** the WebSocket
> per-market mutex is a promise chain instead of a 5 ms busy-wait; the module-singleton socket now
> closes on hot reload and on `pagehide` instead of leaking; and the server runs a real 30 s
> heartbeat sweep (see `docker-concurrency-realtime.md` §D10). See §5 for the details and the
> `readyState` regression caught on the way.

Naming these **before** you're asked is the whole game.

**Dead / unused**
1. 160 of 164 chart files unused by the app (§7.3).
2. `lib/utils/chart.ts`'s `priceToOHLC` / `addPriceToOHLC` — never called.
3. `components/error-boundary.tsx` — never mounted.
4. `parseResponse()` in `client.ts` — exported, never called.
5. `packages/ui`'s `./hooks/*` export — directory holds only `.gitkeep`.
6. `useUserSocket`'s returned `send` — never called.
7. `verifyMagicUrl2fa` — never called from `apps/web`; a parallel `verifyMagic2fa` exists with a
   comment distinguishing the two flows.
8. `zod-form-data` (declared dependency) — never imported.
9. `frontend/.eslintrc.js` — inert under flat config.
10. Backend `/ws/trades` — no client connects.
11. Inline `biome-ignore` comments in `packages/ui/charts` with **no biome config in the repo** —
    vestigial from the design system's origin.

**Inconsistencies**
12. Two TypeScript compilers: `7.0.2` vs `5.9.3`.
13. Two hook barrels: `hooks/api/index.ts` (`export *`) and `hooks/index.ts` (explicit).
14. Two form-field systems: legacy `form.tsx` (auth) vs newer `field.tsx` (`trade-form.tsx`).
15. Bun drift: `packageManager: bun@1.3.14` vs `oven/bun:1.4-slim` images.
16. Security headers set **twice** on the same responses — `next.config.ts:46-64` and
    `proxy.ts:105-113`. Identical values, so harmless, but redundant.
17. `zod` v4 migration is partial inside one file: `z.email()` throughout `schemas/auth.ts` but
    `z.string().email()` at `:45`.

**Content bugs — flag these, they're the strongest evidence you actually read the app**
18. **`predictx.io` still appears in 5 files** — `support@predictx.io` (`(app)/support/page.tsx:25,28`),
    `https://docs.predictx.io` (`(app)/docs/page.tsx:9`), `api@predictx.io` (`(app)/docs/page.tsx:84,87`),
    `privacy@predictx.io` (`legal/privacy`), `legal@predictx.io` (`legal/terms`), plus more in
    `faq/page.tsx`. The frontend README claims the brand drift "is swept to 'Polymarket'" — it isn't.
19. **The FAQ contradicts the implemented auth model.** `(app)/faq/page.tsx:11-13` says *"Connect
    your wallet to the platform. Your account is automatically created on your first connection using
    your wallet address"* — but the system is **email + password with TOTP 2FA**, and the app has
    **no wallet-connect code at all**. The very next FAQ answer (`:20-21`) describes the real model.
    Leftover copy from a different product.
20. `X-XSS-Protection: 1; mode=block` (`next.config.ts:54`, `proxy.ts:108`) — deprecated and a no-op
    in every major browser since 2018. Harmless, but don't present it as a defence; the real defence
    is the CSP and HttpOnly cookies.

**Risks**
21. Server-side fetch doesn't forward cookies (§3.2).
22. `/notifications` missing from `PROTECTED_PATHS` (§2.1).
23. Market detail SSRs no data; per-market SEO metadata doesn't exist (§3.2).
24. No `global-error.tsx`, no `loading.tsx`.

---

## 12. One-paragraph summary, for reading aloud

> The frontend is a Bun + Turborepo monorepo with two packages: the Next.js 16 / React 19 app and a
> shared UI package that has **no build step** — it's consumed as raw TypeScript through
> `transpilePackages`, which removes the whole watch-and-cache layer. Authentication is **cookie-only
> and HttpOnly**, so JavaScript cannot read a token at all and XSS cannot exfiltrate a session; the
> app is *told* whether a session exists and compensates with a single-flight refresh state machine
> that distinguishes "session gone" from "server briefly unhealthy". Data is TanStack Query with
> `staleTime` tuned per query and two pagination styles matched to the backend's offset vs keyset
> APIs. Realtime is a **module-level singleton WebSocket per tab** with per-market subscription
> multiplexing, capped exponential backoff, sleep/wake recovery, and Strict-Mode-safe teardown — and
> the two subtle lifecycle bugs it fixed are documented in place. The charting layer is a large
> visx/d3 system that is code-split with `dynamic({ssr:false})` so it never touches the initial
> bundle, of which the app currently uses one of sixteen chart families. The honest gaps are: **no
> frontend tests at all**, server-component fetches that don't forward cookies, the market detail
> page rendering no server data, and leftover copy from a wallet-connect product this no longer is.

---

## 13. Where to look in the code

| Thing | File:line |
|---|---|
| Middleware (renamed in Next 16) | `apps/web/proxy.ts` |
| Route-protection lists + open-redirect guard | `apps/web/proxy.ts:20-22, 157-159` |
| Cookie replay after refresh | `apps/web/proxy.ts:42-52, 90-99` |
| The only server data fetch | `apps/web/app/(app)/page.tsx:50-62` |
| Base URLs + normalisation | `apps/web/lib/config.ts:10-17` |
| Error-envelope normaliser | `apps/web/lib/api/client.ts:31-76` |
| Retry/backoff | `apps/web/lib/api/client.ts:149-196` |
| Single-flight refresh state machine | `apps/web/lib/api/client.ts:207-310` |
| GET de-duplication | `apps/web/lib/api/client.ts:314, 336-341` |
| React Query defaults | `apps/web/components/providers.tsx:12-19` |
| `useAuthGate` and why it exists | `apps/web/hooks/api/use-auth-gate.ts:4-20` |
| `useCurrentUser` single definition | `apps/web/hooks/use-auth.ts:9-21` |
| WebSocket singleton | `apps/web/hooks/use-market-socket.tsx:23-77` |
| Anonymous-socket rationale | `apps/web/hooks/use-market-socket.tsx:129-134` |
| Reconnect cap + backoff | `apps/web/hooks/use-market-socket.tsx:46-54, 228-229` |
| The two fixed lifecycle bugs | `apps/web/hooks/use-market-socket.tsx:206-212, 150-153` |
| Sleep/wake recovery | `apps/web/hooks/use-market-socket.tsx:333-363` |
| Chart code-splitting | `apps/web/components/markets/market-detail.tsx:35-59` |
| WS→React Query cache writes | `apps/web/components/markets/market-detail.tsx:149-167` |
| Notification optimistic overlay | `apps/web/components/notifications/notification-bell.tsx:143-190` |
| Tailwind v4 CSS-first config | `packages/ui/src/styles/globals.css:1-8` |
| Chart CSS-var namespace | `packages/ui/src/styles/globals.css:138-163` |
| Base UI primitive (not Radix) | `packages/ui/src/components/button.tsx:1` |
| `transpilePackages` | `apps/web/next.config.ts:39` |
| CSP + `connect-src` | `apps/web/next.config.ts:25-36` |
| Turbo task graph | `turbo.json:5-24` |