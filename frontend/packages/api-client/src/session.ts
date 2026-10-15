/**
 * Session validation for Next.js proxies.
 *
 * ## Why this is shared and not copied
 *
 * `apps/web/proxy.ts` grew ~70 lines of this: read the access cookie, call
 * `/auth/me`, and on a miss rotate through the refresh cookie and *replay every
 * `Set-Cookie` the API returned onto our own response*. That last part is the
 * whole difficulty — forget it and rotation appears to work while the browser
 * keeps the stale token, which surfaces days later as "users get logged out every
 * twenty minutes". None of it fails loudly. All of it is worth having exactly one
 * copy of.
 *
 * ## The trap this code exists to avoid
 *
 * A proxy runs on the server and has **its own cookies**. They are not the
 * browser's. So every outbound call must forward the incoming cookie explicitly,
 * and every `Set-Cookie` the API hands back must be appended to our response one
 * at a time — `Headers.set` on a repeated name overwrites rather than appending,
 * so a loop is required even though it looks like it should not be.
 *
 * Framework-agnostic on purpose: this takes cookie values and returns strings, so
 * the package does not depend on `next/server` and each app can build its own
 * `NextResponse` around it.
 */

export interface ProxyIdentity {
  id: string
  email: string
  username: string
  is_admin: boolean
}

export interface ProxySession {
  user: ProxyIdentity | null
  /** `Set-Cookie` headers from the API that must reach the browser. */
  setCookies: string[]
}

export interface ValidateSessionOptions {
  /** API origin, e.g. `https://api.example.com`. */
  apiBase: string
  accessToken: string | null
  refreshToken: string | null
  /** Injectable for tests; defaults to the global. */
  fetchImpl?: typeof fetch
}

export const ACCESS_COOKIE = "access_token"
export const REFRESH_COOKIE = "refresh_token"

/**
 * `Set-Cookie` must be read one at a time.
 *
 * `Headers.get("set-cookie")` folds multiple headers into one comma-joined
 * string, and `Set-Cookie` values contain commas themselves (`Expires=...`). The
 * folded form cannot be split back apart reliably, which is why this prefers
 * `getSetCookie()` when the runtime provides it.
 */
export function readSetCookies(res: Response): string[] {
  const headers = res.headers as Headers & { getSetCookie?: () => string[] }
  if (typeof headers.getSetCookie === "function") return headers.getSetCookie()
  const raw = headers.get("set-cookie")
  return raw ? [raw] : []
}

/**
 * Append, never set.
 *
 * `headers.set("set-cookie", a); headers.set("set-cookie", b)` leaves only `b`.
 * The access *and* refresh cookies are rotated together, so losing either one
 * breaks the app in a way that looks unrelated to cookies.
 */
export function applySetCookies(
  target: { headers: Headers },
  setCookies: readonly string[]
): void {
  for (const cookie of setCookies) target.headers.append("set-cookie", cookie)
}

async function fetchMe(
  apiBase: string,
  cookieHeader: string,
  fetchImpl: typeof fetch
): Promise<ProxyIdentity | null> {
  const res = await fetchImpl(`${apiBase}/api/v1/auth/me`, {
    headers: { Cookie: cookieHeader },
    cache: "no-store",
  })
  if (!res.ok) return null
  const json = (await res.json()) as { success: boolean; data?: ProxyIdentity }
  return json.data ?? null
}

/**
 * Is this payload shaped like an identity?
 *
 * Checked before a proxy trusts it. A redirect target and a session claim both
 * come from this, and `user.id` ends up in a cookie-replay path — an unexpected
 * shape from a deploy that is mid-migration should send the operator to login,
 * not be forwarded.
 */
export function isPlausibleIdentity(user: ProxyIdentity | null): boolean {
  if (!user) return false
  const isUuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(user.id)
  const isEmail = /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(user.email)
  return isUuid && isEmail && typeof user.is_admin === "boolean"
}

/**
 * Validate, and rotate if the access token has expired.
 *
 * A network failure resolves to "no session" rather than throwing: a proxy that
 * throws on a transient API blip turns a 2-second outage into every user being
 * logged out.
 */
export async function validateSessionCookies({
  apiBase,
  accessToken,
  refreshToken,
  fetchImpl = fetch,
}: ValidateSessionOptions): Promise<ProxySession> {
  if (accessToken) {
    try {
      const user = await fetchMe(apiBase, `${ACCESS_COOKIE}=${accessToken}`, fetchImpl)
      if (isPlausibleIdentity(user)) return { user, setCookies: [] }
      if (user) {
        // Signed in, but the payload is not what this app expects. Fall through
        // to a rotation rather than trusting it.
        return { user: null, setCookies: [] }
      }
    } catch {
      // Network error — fall through to refresh, then to "not signed in".
    }
  }

  if (!refreshToken) return { user: null, setCookies: [] }

  let refreshRes: Response
  try {
    refreshRes = await fetchImpl(`${apiBase}/api/v1/auth/refresh`, {
      method: "POST",
      headers: { Cookie: `${REFRESH_COOKIE}=${refreshToken}` },
      cache: "no-store",
    })
  } catch {
    return { user: null, setCookies: [] }
  }

  // Collected before the `ok` check: a *failed* refresh still carries Set-Cookie
  // headers (clearing the dead ones), and dropping them leaves the browser holding
  // a token the server has already invalidated.
  const setCookies = readSetCookies(refreshRes)
  if (!refreshRes.ok) return { user: null, setCookies }

  const newAccess = setCookies
    .map((cookie) => cookie.split(";")[0]?.trim())
    .find((cookie) => cookie?.startsWith(`${ACCESS_COOKIE}=`))
  if (!newAccess) return { user: null, setCookies }

  try {
    const user = await fetchMe(apiBase, newAccess, fetchImpl)
    return { user: isPlausibleIdentity(user) ? user : null, setCookies }
  } catch {
    return { user: null, setCookies }
  }
}

/**
 * Baseline response headers.
 *
 * `X-Frame-Options` and `nosniff` on every response; HSTS only in production,
 * where sending it over plain HTTP would pin a *localhost* development session to
 * HTTPS for a year.
 */
export function applySecurityHeaders(headers: Headers, nodeEnv = process.env.NODE_ENV): void {
  headers.set("X-Content-Type-Options", "nosniff")
  headers.set("X-Frame-Options", "DENY")
  headers.set("X-XSS-Protection", "1; mode=block")
  headers.set("Referrer-Policy", "strict-origin-when-cross-origin")
  if (nodeEnv === "production") {
    headers.set("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
  }
}