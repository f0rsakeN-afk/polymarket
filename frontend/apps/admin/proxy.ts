/**
 * Proxy (Next 16's middleware) for the admin app.
 *
 * ## Why this exists at all
 *
 * Every admin route is privileged and the app had **no proxy at all**. `apps/web`
 * has had one all along, which makes this an omission rather than a decision.
 *
 * The API is the actual security boundary — every admin endpoint authorises
 * server-side, so nothing here is what stops a non-admin reading a user's record.
 * What the proxy fixes is everything around that:
 *
 * - A signed-out visitor no longer downloads the operator surface and its admin
 *   API calls before being told to sign in. The shell's client-side gate is still
 *   there and still needed (see below), but it is no longer the *first* thing.
 * - A signed-in **non-admin** is redirected with `?reason=not-admin` instead of
 *   being allowed to load four routes' worth of queries that each 403.
 * - An admin who navigates to `/login` is sent to the dashboard rather than shown
 *   a sign-in form they do not need.
 *
 * ## The client-side gate stays anyway
 *
 * Deliberately, and it is worth being explicit about why, because "the proxy
 * handles it, remove the gate" is the obvious next step and it would be wrong.
 *
 * The proxy decides from a cookie it can read. The shell decides from a live
 * `/auth/me`. They fail differently: a `Set-Cookie` replay problem, a proxy that
 * did not match a route, a middleware `matcher` that misses a prefix — each leaves
 * the operator looking at an admin UI. The shell's gate is the second opinion, and
 * it is the one that costs nothing when it is right.
 *
 * ## Why this does not duplicate `apps/web/proxy.ts`
 *
 * The subtle part — cookie forwarding, rotation, replaying every `Set-Cookie`
 * because `Headers.set` overwrites where the protocol wants an append — is
 * `@workspace/api-client/session`, shared. Only the *policy* is per-app, because
 * the two apps genuinely disagree about it: the storefront protects
 * `/portfolio` and leaves the homepage public, while **every** admin route but
 * `/login` is behind an admin check.
 */

import { NextResponse, type NextRequest } from "next/server"

import { config as appConfig } from "@workspace/api-client/config"
import {
  ACCESS_COOKIE,
  REFRESH_COOKIE,
  applySecurityHeaders,
  applySetCookies,
  validateSessionCookies,
} from "@workspace/api-client/session"

/** The one route reachable without an admin session. */
const LOGIN_PATH = "/login"

/**
 * Where a signed-in non-admin is sent.
 *
 * The storefront, not `/login`: they are not going to become an admin by signing
 * in again, and bouncing them between the two would be a loop with extra steps.
 */
/** Where a signed-in non-admin is sent. Never `undefined`; falls back to root. */
function siteUrl(): string {
  return appConfig.siteUrl || "/"
}

async function checkSession(request: NextRequest) {
  return validateSessionCookies({
    apiBase: appConfig.apiUrl,
    accessToken: request.cookies.get(ACCESS_COOKIE)?.value ?? null,
    refreshToken: request.cookies.get(REFRESH_COOKIE)?.value ?? null,
    // Forwarded because the backend fingerprints refresh tokens by User-Agent
    // and revokes on mismatch. This refresh runs in Node, whose `fetch` sends
    // its own UA — so without it, the first refresh after the access token
    // expires reads as a different device, the token is revoked and the session
    // is destroyed. That is what logged an operator out of this app roughly every
    // fifteen minutes, and took the storefront session with it.
    userAgent: request.headers.get("user-agent"),
  })
}

function pass(setCookies: readonly string[] = []) {
  const response = NextResponse.next()
  applySetCookies(response, setCookies)
  applySecurityHeaders(response.headers)
  return response
}

function toLogin(request: NextRequest, setCookies: readonly string[], reason?: string) {
  const url = new URL(LOGIN_PATH, request.url)
  if (reason) {
    url.searchParams.set("reason", reason)
  } else {
    // Preserved so a successful sign-in returns the operator to where they were.
    // Same-origin paths only: `//evil.example` is a protocol-relative URL and
    // passing it through would make the login page an open redirect.
    const next = request.nextUrl.pathname
    if (next.startsWith("/") && !next.startsWith("//")) url.searchParams.set("next", next)
  }
  const response = NextResponse.redirect(url)
  applySetCookies(response, setCookies)
  applySecurityHeaders(response.headers)
  return response
}

export async function proxy(request: NextRequest) {
  const { pathname } = request.nextUrl

  if (pathname === LOGIN_PATH || pathname.startsWith(`${LOGIN_PATH}/`)) {
    const { user, setCookies } = await checkSession(request)

    if (user?.is_admin) {
      // Already in. Sending them to the storefront instead would be a pointless
      // trip; `next` is honoured so a deep link survives the detour.
      const raw = request.nextUrl.searchParams.get("next")
      const target = raw && raw.startsWith("/") && !raw.startsWith("//") ? raw : "/"
      const response = NextResponse.redirect(new URL(target, request.url))
      applySetCookies(response, setCookies)
      applySecurityHeaders(response.headers)
      return response
    }

    if (user) {
      // Signed in, but not an admin. Redirected to the site rather than left
      // here: rendering the form would invite a second sign-in that cannot help,
      // and redirecting to `/` would land them back in this proxy, which sends
      // them here again.
      const response = NextResponse.redirect(new URL(siteUrl(), request.url))
      applySetCookies(response, setCookies)
      applySecurityHeaders(response.headers)
      return response
    }

    return pass(setCookies)
  }

  // Everything below the login page is privileged.
  //
  // Checked before any static fast-path, so a lookalike URL (`/users/report.json`)
  // can never skip the session check by matching a "has a dot" rule.
  const { user, setCookies } = await checkSession(request)

  if (!user) return toLogin(request, setCookies)
  // Signed in but not an admin: the same destination as above, carrying the
  // reason so the login page can explain rather than just showing a form.
  if (!user.is_admin) return toLogin(request, setCookies, "not-admin")

  return pass(setCookies)
}

export const config = {
  matcher: ["/((?!_next/static|_next/image|favicon.ico|opengraph-image).*)"],
}