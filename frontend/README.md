# Frontend

Next.js 16 (App Router) + React 19, managed with Bun and Turborepo.

## Layout

```
frontend/
  apps/web/            The application
    app/               Routes (App Router), server components for first paint
    components/        Client components (live data, forms, charts)
    lib/api/client.ts  Typed fetch wrapper: cookies, 401 refresh, GET de-dup, retries
    hooks/use-market-socket.tsx   One shared WS connection → per-market subscriptions
    hooks/use-user-socket.ts      Per-user notifications WebSocket
    next.config.ts     CSP + headers for HTML responses
  packages/ui/         Shared design system (Base UI components, visx charts)
  packages/eslint-config, packages/typescript-config
  Dockerfile(.dev)     bun install → next build → standalone runtime
  docker-compose.dev.yml / docker-compose.prod.yml
```

## Commands

```bash
bun install
bun run dev          # turbo dev — http://localhost:3000
bun run build        # turbo build
bun run lint         # eslint (warnings only today — see known gaps)
bun run typecheck    # tsc --noEmit
```

## How it talks to the backend

- **REST** through `lib/api/client.ts`: always sends cookies, de-duplicates identical GETs, performs
  a *single-flight* refresh on 401 (ten parallel requests trigger one refresh), retries with bounds.
- **WebSockets** through two hooks: `useMarketSocket` (one shared connection per tab, per-market
  subscriptions for prices/order book/trades) and `useUserSocket` (per-user notifications). Both
  patch React Query's cache in place. The backend also serves `/ws/trades` for a global feed.
- **Auth** is cookie-based (HttpOnly), so the server can read it on first paint. Middleware
  (`proxy.ts`) guards routes at the edge; the API still verifies every request itself.

Server state lives in React Query, UI state in local `useState`/context — there is deliberately no
global store.

## Known gaps (documented, not hidden)

- **No test suite at all.** First thing to fix (vitest + a few Playwright flows).
- ESLint runs with `eslint-plugin-only-warn`, so lint never fails a build.
- Duplicate `useCurrentUser` hook, a dead `metadata.ts`, an `/admin` link rendered for non-admins,
  a mounted-but-unused toaster, and brand-name drift ("PredictX" vs "Polymarket").

## More

Project documentation lives in [`../docs/`](../docs/README.md) — in particular
[`../docs/architecture.md`](../docs/architecture.md) for the API contract and
[`../docs/viva-questions.md`](../docs/viva-questions.md) §K for the frontend questions.
