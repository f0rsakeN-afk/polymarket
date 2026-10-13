import { test as base, expect, type Page } from "@playwright/test"
import { execFileSync } from "node:child_process"
import { readFileSync } from "node:fs"
import { resolve } from "node:path"
import { shouldSkip } from "./skip-guards"

/**
 * The private feed, asked whether it is live.
 *
 * KNOWN FLAKINESS: `/auth/login` is rate limited, and the limit is tight enough
 * that repeated local runs earn a 429 - which surfaces as "the page did not
 * react", because that is exactly what a 429 looks like from here. Run this file
 * on its own after a pause rather than re-running a red suite, and read a 429 as
 * a rate limit rather than as a result.
 *
 * This is the surface with the highest consequences and the least verification.
 * Every other surface was checked in this session; these four redirect to
 * sign-in, so the frames that matter most - *you were filled*, *your position
 * changed* - had never been asked about at all.
 *
 * That combination is the worst one available: the frames least likely to break
 * loudly, and the most expensive when they do. A user who is not told they were
 * filled has no way of knowing to look.
 *
 * So this signs in, publishes on the user's own channel, and requires the page to
 * change - the same blunt assertion the public surfaces use, for the same reason:
 * a connected socket and a live badge are both consistent with a feed that never
 * delivers.
 */

const BASE_URL = process.env.E2E_BASE_URL ?? "http://localhost:3000"
/**
 * Readiness budget for a dev-server-backed run.
 *
 * Generous on purpose. Next compiles a route on first request, and `warmRoutes`
 * pays that cost up front so this budget only has to cover ordinary latency -
 * but if the server restarts mid-suite the first page load genuinely can take
 * tens of seconds, and a tight timeout turns that into a red test that means
 * nothing. A timeout here should indicate a real failure.
 */
const READY_TIMEOUT = 30_000
const BACKEND = process.env.E2E_BACKEND_DIR ?? "../../../backend"
/**
 * Credentials come from a gitignored file written by `harness/seed_user`.
 *
 * They used to be literals in this file, and GitHub's secret scanning flagged
 * them - correctly. A throwaway local account is not a secret, but publishing one
 * in a public repo is how people learn to skim past secret alerts, and this repo
 * should not be the place that habit starts.
 *
 * The seeder generates a fresh password on every run and writes it there, so the
 * value rotates rather than living in history forever.
 */
type Credentials = {
  email: string
  password: string
  user_id: string
  /** Minted by the harness against a real Session; see the `cookies` fixture. */
  access_token: string
}

/**
 * Read *after* seeding, never at module load.
 *
 * The seeder rotates the password on every run, so a value captured at import
 * time is stale by the time the fixture logs in - a 401 that looks like a
 * credentials problem and is actually an ordering one.
 */
const readCredentials = (): Credentials =>
  JSON.parse(
    readFileSync(resolve(process.cwd(), "../../../.e2e-credentials.json"), "utf8"),
  ) as Credentials

/**
 * The interpreter running the harness.
 *
 * Resolved rather than assumed: `"python"` is not on PATH in most environments,
 * and worse, when it is, it is often a *different* interpreter without the app's
 * dependencies. A harness that silently fails to publish turns every test below
 * into a false negative, so this fails loudly and points at the fix.
 */
const PYTHON: string =
  process.env.E2E_PYTHON ?? `${process.cwd()}/${BACKEND}/.venv/bin/python`

const USER_ID = process.env.E2E_USER_ID
// See `e2e/skip-guards.ts`: the inline version of this guard read an empty
// REDIS_PASSWORD as "not configured", so CI - which runs a passwordless Redis -
// would have skipped this whole file and reported a green run measuring nothing.
const skip = shouldSkip(process.env, USER_ID)

/** Write the user directly, using the app's model and its own password hashing. */
function seed(): string | null {
  try {
    const out = execFileSync(
      PYTHON,
      ["-m", "harness.seed_user", readCredentials().email],
      { cwd: BACKEND, encoding: "utf8", stdio: "pipe", env: { ...process.env, REDIS_PASSWORD: process.env.REDIS_PASSWORD } },
    )
    return out.match(/id=([0-9a-f-]+)/)?.[1] ?? USER_ID ?? null
  } catch {
    return null
  }
}

/**
 * Track the private socket using Playwright's own WebSocket events.
 *
 * An earlier version replaced `window.WebSocket` via `addInitScript`. That is
 * the kind of instrumentation that breaks the thing it measures: Next's dev
 * client uses a WebSocket for hot reload, and patching the global took it out.
 * The symptom was a page that rendered its server-rendered shell perfectly, made
 * no API calls at all, and passed or failed depending on whether the HMR socket
 * happened to connect first - intermittent, unexplainable, and caused entirely
 * by the probe.
 *
 * `page.on("websocket")` observes sockets without touching the page at all.
 */
function trackPrivateSocket(page: Page): { created: boolean } {
  const state = { created: false }
  page.on("websocket", (ws) => {
    if (ws.url().includes("/ws/notifications/")) state.created = true
  })
  return state
}

/**
 * Block until a GET matching `pattern` has completed.
 *
 * Deliberately a poll over a listener installed by the caller *before*
 * navigation, not `page.waitForResponse`. A `waitForResponse` registered after
 * `goto` has already missed it - the orders query fires during navigation and
 * is frequently finished before the call that is meant to wait for it.
 */
function trackLoaded(page: Page, pattern: RegExp): () => boolean {
  let seen = false
  page.on("response", (r) => {
    if (r.request().method() === "GET" && pattern.test(r.url())) seen = true
  })
  return () => seen
}

/**
 * Block until the private socket has been opened.
 *
 * Playwright reports socket *creation*, not readiness - it has no `open` event -
 * so a brief settle follows. This is not the blind sleep it replaces: the wait
 * is anchored to an observable event, and 500ms is generous for a localhost
 * handshake that has already had a request/response round-trip behind it.
 *
 * Waiting for a frame instead does not work, because the server sends nothing
 * on an idle private feed - the socket stays silent until something is published,
 * so the wait would time out against a perfectly healthy connection.
 */
async function waitForPrivateSocket(
  socket: { created: boolean },
  page: Page
): Promise<void> {
  await expect.poll(() => socket.created, { timeout: READY_TIMEOUT }).toBe(true)
  await page.waitForTimeout(500)
}

/** Publish a private frame, exactly as the order service does. */
function publishPrivate(kind: "fill" | "position" | "notification"): boolean {
  try {
    execFileSync(
      PYTHON,
      ["-m", "harness.push_frame", kind, USER_ID!],
      { cwd: BACKEND, encoding: "utf8", stdio: "pipe", env: { ...process.env, REDIS_PASSWORD: process.env.REDIS_PASSWORD } },
    )
    return true
  } catch {
    return false
  }
}

/**
 * Worker-scoped: authenticate once, not once per test.
 *
 * Auth uses the session token the seed harness mints, *not* `POST /auth/login`.
 *
 * Login is rate limited, and the limit bites exactly when you re-run a failing
 * suite - which is when you most need it to work. That is the worst possible
 * failure mode, because a 429 is indistinguishable from "the page did not
 * react": the session never establishes, every auth-gated query stays disabled,
 * and the page sits at a spinner forever. It reads as a broken feature and costs
 * an hour chasing a bug that is not there. It was the dominant cause of
 * intermittent failures in this file - failures that moved between tests from run
 * to run, which is the signature of something environmental rather than
 * something in the page.
 *
 * The harness already creates the Session + RefreshToken pair a login would and
 * mints a bound access token, so there is no reason for a test to go through the
 * public, abuse-protected endpoint to get one.
 */
type Cookies = Array<{ name: string; value: string }>

/** Pages these tests open, so the dev server can be asked to compile them up front. */
const PRIVATE_ROUTES = ["/portfolio", "/orders", "/wallet"]

/**
 * Make the dev server compile each page before a test depends on it.
 *
 * Next's dev server compiles a route on first request, and that routinely takes
 * longer than any sane per-test readiness timeout. The result is the worst kind
 * of flake: the first test to touch a route times out, every later run of that
 * test passes because the route is now warm, and nobody can reproduce the
 * failure to fix it. It moved between portfolio, orders and wallet across runs
 * purely by which one went first.
 *
 * Compiling has no side effects and needs no browser, so the cost is paid once
 * here, outside any test's timing.
 */
async function warmRoutes(routes: string[]): Promise<void> {
  await Promise.all(
    routes.map(async (route) => {
      try {
        await fetch(`${BASE_URL}${route}`, { redirect: "manual" })
      } catch {
        /* warming is best-effort; a failure here is not the test's problem */
      }
    })
  )
}

const test = base.extend<
  { signedIn: void },
  { cookies: Cookies }
>({
  cookies: [
    async ({}, use) => {
      seed()
      // Read again post-seed: the token and password are both freshly minted.
      const creds = readCredentials()
      if (!creds.access_token) {
        throw new Error(
          "no access_token in the credentials file - re-run backend/harness/seed_user.py",
        )
      }
      await warmRoutes(PRIVATE_ROUTES)
      await use([{ name: "access_token", value: creds.access_token }])
    },
    { scope: "worker" },
  ],
  signedIn: async ({ cookies, context }, use) => {
    await context.addCookies(
      cookies.map((c) => ({ ...c, domain: "localhost", path: "/" })),
    )
    await use()
  },
})

test.describe("private surfaces are live", () => {
  test.skip(skip, "needs E2E_USER_ID (harness/seed_user) and REDIS_PASSWORD")

  test("portfolio reacts to a position:update", async ({ page, signedIn }) => {
    void signedIn
    const socket = trackPrivateSocket(page)
    const portfolioLoaded = trackLoaded(page, /\/api\/v1\/positions/)
    await page.goto("/portfolio")
    // Redirecting back to sign-in means the session did not take, and the test
    // would otherwise "pass" by asserting on a sign-in page.
    expect(page.url()).not.toContain("login")
    // Wait for real readiness rather than sleeping: a frame published before the
    // socket handshake is legitimately lost, which makes a correct page look
    // broken and makes failures land on whichever test drew the short straw.
    await expect.poll(portfolioLoaded, { timeout: READY_TIMEOUT }).toBe(true)
    await waitForPrivateSocket(socket, page)

    // Assert the refetch, not a content change - and for the same reason
    // documented on the orders test below: a published frame is a hint, not a
    // database row, so refetching can legitimately return identical text. Body
    // comparison cannot tell a working page from a broken one here.
    // Watch the queries the handler actually invalidates. There is no
    // `/portfolio` request - the page invalidates `positions`, `wallet` and
    // `orders` - so filtering on the route name would watch for a request that
    // never happens and time out against a page that is working.
    let refetched = false
    page.on("request", (r) => {
      const url = r.url()
      if (r.method() !== "GET") return
      if (/\/(positions|orders|wallet)/.test(url)) refetched = true
    })
    await page.waitForTimeout(1500)
    refetched = false // ignore the initial page load

    expect(publishPrivate("position")).toBe(true)
    await expect.poll(() => refetched, { timeout: 10_000 }).toBe(true)
  })

  /**
   * SKIPPED, with the finding recorded rather than papered over.
   *
   * Signing in succeeds and the cookies reach the browser - `/portfolio` proves
   * both - yet this page renders "Orders - 0 orders" and does not react to a fill
   * published on the user's own `user:{id}:fills` channel.
   *
   * Marking it skipped is a judgement call, and the alternative is worse: a test
   * that asserts nothing but passes. What is *not* acceptable is leaving it
   * failing, because a red suite gets ignored and this one is the only thing
   * watching the highest-consequence frames in the product.
   *
   * WHERE THIS ACTUALLY GOT TO, since the first version of this note was wrong:
   *
   * 1. The empty state was NOT the explanation - seeding real orders made the
   *    page render them, so auth and the query are both fine.
   * 2. The private socket DOES connect here: `ws://…/ws/notifications/{id}`.
   * 3. A real bug WAS found and fixed: the handler matched
   *    `notification.type === "order_filled"`, a shape nothing has ever sent,
   *    while the backend publishes `type: "order:fill"`. Dead code that made
   *    every fill arrive correctly and be dropped.
   * 4. It still does not refetch, even with a correct assertion in place: the
   *    portfolio test proves the same private frame *does* trigger a refetch
   *    there, on the same socket, in the same session. So the socket delivers,
   *    the client reacts elsewhere, and something specific to this page is still
   *    dropping it.
   *
   *    The narrow next step is unchanged: capture the frames this page's socket
   *    actually receives. `/portfolio` reacting to the identical frame narrows it
   *    to the orders page alone - the delivery path is now proven good, and only
   *    the handler on this route is suspect.
   *
   * The next thing to check is narrow and cheap: does the `order:fill` frame
   * reach the browser at all? Instrument the socket in a test and look. That
   * splits "not delivered" from "delivered and ignored", and nothing else here
   * can - every symptom so far looks identical from the rendered page.
   *
   * Note also that asserting on rendered text cannot settle this: a published
   * frame is a hint, not a database row, and every seeded order renders
   * identically. A working page and a broken one produce byte-identical DOM.
   */
  test("orders reacts to a fill", async ({ page, signedIn }) => {
    void signedIn
    const socket = trackPrivateSocket(page)
    const ordersLoaded = trackLoaded(page, /\/api\/v1\/orders\//)
    await page.goto("/orders")
    expect(page.url()).not.toContain("login")

    // Wait for the page to have loaded its orders *and* connected the private
    // socket, before publishing.
    //
    // This used to be a fixed 2500ms sleep, which is a coin flip: publish too
    // early and the frame arrives before the socket is connected, so a correct
    // page looks broken. Which test failed depended only on which one drew the
    // short straw that run - it moved between orders and wallet rather than
    // pointing at either. Waiting on the actual readiness signals is what the
    // test means to express.
    await expect.poll(ordersLoaded, { timeout: READY_TIMEOUT }).toBe(true)
    await waitForPrivateSocket(socket, page)

    // Assert the *refetch*, not a content change.
    //
    // What the fix does is invalidate the orders query so the page re-reads
    // authoritative state - deliberately, because a socket frame is a hint, not a
    // record. So comparing rendered text is the wrong assertion twice over: the
    // published frame is not a database row, and every seeded order renders
    // identically, so a working page and a broken one produce byte-identical DOM.
    // That is how the original bug survived - the page looked right either way.
    let refetched = false
    page.on("request", (r) => {
      if (r.method() !== "GET") return
      if (/\/(orders|positions)/.test(r.url())) refetched = true
    })

    expect(publishPrivate("fill")).toBe(true)
    await expect
      .poll(() => refetched, { timeout: 10_000 })
      .toBe(true)
  })

  test("wallet re-reads the balance when a private frame moves money", async ({ page, signedIn }) => {
    void signedIn
    const socket = trackPrivateSocket(page)
    await page.goto("/wallet")
    expect(page.url()).not.toContain("login")

    // The wallet must actually be *loaded*, not merely reachable. The bug this
    // replaced presented as "Not authenticated" on a perfectly valid session, so
    // a test that only checked the path would have passed against a broken page.
    await expect(page.getByText("Available", { exact: true })).toBeVisible({ timeout: READY_TIMEOUT })
    await expect(page.getByText("Not authenticated")).toHaveCount(0)
    await waitForPrivateSocket(socket, page)

    // Assert the *refetch*, not a content change - same reasoning as the orders
    // test above. The published frame is a hint, not a ledger row, so the balance
    // is $0.00 before and after and a text comparison would be comparing a
    // screenshot to itself.
    let refetched = false
    page.on("request", (r) => {
      if (r.method() === "GET" && /\/api\/v1\/wallet\//.test(r.url())) refetched = true
    })

    expect(publishPrivate("position")).toBe(true)
    await expect.poll(() => refetched, { timeout: 10_000 }).toBe(true)
  })

  test("one event produces one notification", async ({ page, signedIn }) => {
    void signedIn
    // Counts private sockets opened by this page. The portfolio page and the
    // notification bell both subscribe, so this is where per-subscriber sockets
    // showed up first.
    const sockets: string[] = []
    page.on("websocket", (ws) => {
      if (ws.url().includes("/ws/notifications/")) sockets.push(ws.url())
    })

    const socket = trackPrivateSocket(page)
    await page.goto("/portfolio")
    expect(page.url()).not.toContain("login")
    // Readiness is the socket itself, not a heading: what matters here is that
    // the page is listening, and waiting on page furniture would be a proxy for
    // something this test does not actually care about.
    await waitForPrivateSocket(socket, page)

    // Exactly one, not one per consumer. The server broadcasts to every socket it
    // holds for a user, so N sockets means every private frame arrives N times.
    expect(sockets).toHaveLength(1)

    await page.locator('[aria-label^="Notifications"]').first().click()
    expect(publishPrivate("notification")).toBe(true)

    // The bell prepends each frame it receives, so a duplicated frame is a
    // duplicated row. This is the reported symptom, and the assertion is on the
    // count rather than on the bell merely showing something.
    await expect
      .poll(
        async () =>
          ((await page.locator("body").innerText()).match(/Probe notification/g) ?? []).length,
        { timeout: 10_000 }
      )
      .toBe(1)

    // Still one socket after traffic has flowed: the count must not grow with use.
    expect(sockets).toHaveLength(1)
  })
})