import { config } from "@/lib/config"

const API_BASE = config.apiUrl

export class ApiError extends Error {
  constructor(
    message: string,
    public status: number,
    public data?: unknown,
    public error_code?: string
  ) {
    super(message)
    this.name = "ApiError"
  }
}

interface ApiErrorData {
  success: false
  error: string
  error_code?: string
  details?: { errors?: { field: string; message: string }[] }
}

/**
 * The backend emits three distinct error envelopes:
 *  1. AppException/handlers → { success:false, error, error_code, details? }
 *  2. FastAPI validation    → { detail: [{loc, msg}, ...] } | { detail: "..." }
 *  3. RateLimitMiddleware   → { error_code:"RATE_LIMIT_EXCEEDED", retry_after }
 *     Origin middleware      → { error_code:"ORIGIN_NOT_ALLOWED", message }
 */
function extractMessage(data: unknown): { message: string; error_code?: string } {
  if (!data || typeof data !== "object") return { message: "An error occurred" }
  const d = data as Record<string, unknown>

  if (Array.isArray(d.detail)) {
    const items = d.detail as { loc: (string | number)[]; msg: string }[]
    return { message: items.map((e) => e.msg || e.loc.join(".")).join("; ") }
  }

  // Rate limiting is checked FIRST so the `retry_after` hint survives even
  // though the middleware now also emits the standard `success/error` keys.
  if (d.error_code === "RATE_LIMIT_EXCEEDED") {
    const retry = typeof d.retry_after === "number" ? d.retry_after : undefined
    return {
      message: retry
        ? `Too many requests — try again in ${retry}s`
        : "Too many requests — try again shortly",
      error_code: "RATE_LIMIT_EXCEEDED",
    }
  }

  const ad = d as Partial<ApiErrorData>
  if (ad.success === false && typeof ad.error === "string") {
    // Field-level detail (FastAPI validation and AppException `details.errors`)
    // carries the *specific* reason — surface it, don't just show "Validation failed".
    const fieldErrors = ad.details?.errors
    const fields =
      Array.isArray(fieldErrors) && fieldErrors.length > 0
        ? fieldErrors.map((e) => `${e.field}: ${e.message}`).join(" · ")
        : ""
    return {
      message: fields ? `${ad.error} — ${fields}` : ad.error,
      error_code: ad.error_code,
    }
  }

  // CORS middleware shape: { error_code, message }.
  if (typeof d.error_code === "string" && typeof d.message === "string") {
    return { message: d.message, error_code: d.error_code }
  }

  if (typeof d.detail === "string") return { message: d.detail }
  if (typeof d.error === "string") return { message: d.error }

  return { message: "An error occurred" }
}

/**
 * Safe error-to-message helper for mutation onError callbacks.
 * Never casts to ApiError — checks it, so non-Error throws fall back cleanly.
 *
 * The backend's own message always wins. The fallback only applies when the
 * failure never reached the server (offline, timeout, aborted request), where
 * the browser's raw text ("Failed to fetch", "The user aborted a request")
 * is meaningless to a user.
 */
export function apiErrorMessage(err: unknown, fallback: string): string {
  if (err instanceof ApiError) return err.message || fallback

  if (err instanceof DOMException && (err.name === "AbortError" || err.name === "TimeoutError")) {
    return "The request timed out — please try again."
  }
  if (err instanceof TypeError && /fetch|network|load failed/i.test(err.message)) {
    return "Can't reach the server — check your connection and try again."
  }
  if (err instanceof Error && err.message) return err.message
  return fallback
}

/** Backend `error_code` when the failure came through the API, else undefined. */
export function apiErrorCode(err: unknown): string | undefined {
  return err instanceof ApiError ? err.error_code : undefined
}

// ─── Response normalizer ────────────────────────────────────────────────────────
// Backend uses 3 response shapes:
//   A: { success: true, data: T, page?, page_size?, has_more?, total? }
//   B: { success: true, data: { nested: T, page?, page_size? } }  (e.g. comments list)
//   C: T directly (non-wrapped)

export interface NormalizedResponse<T> {
  success: boolean
  data: T
  page?: number
  page_size?: number
  has_more?: boolean
  total?: number
}

/** Wraps mutation responses — backend always includes optional message */
export type MutationResponse<T = void> = {
  success: boolean
  data: T
  message?: string
}

export function parseResponse<T>(raw: unknown): NormalizedResponse<T> {
  if (!raw || typeof raw !== "object") {
    return { success: true, data: raw as T }
  }
  const r = raw as Record<string, unknown>

  // Shape A: { success: true, data: ... }
  if (r.success === true && "data" in r) {
    return r as unknown as NormalizedResponse<T>
  }

  // Shape B: nested list (e.g. { comments: [...], page, page_size })
  // Return as-is — callers know their own shape
  return { success: true, data: raw as T }
}

// ─── Retry with backoff ───────────────────────────────────────────────────────

function sleep(ms: number) {
  return new Promise((r) => setTimeout(r, ms))
}

async function fetchWithRetry(
  url: string,
  init: RequestInit,
  options: { retries: number; timeout: number; signal?: AbortSignal }
): Promise<Response> {
  const { retries, timeout, signal } = options
  let lastError: Error | null = null

  for (let attempt = 0; attempt <= retries; attempt++) {
    const controller = new AbortController()
    const timeoutId = setTimeout(() => controller.abort(), timeout)
    const combinedSignal = signal ? anySignal([signal, controller.signal]) : controller.signal

    try {
      const res = await fetch(url, { ...init, signal: combinedSignal })
      clearTimeout(timeoutId)

      if (res.ok) return res

      // 429 — rate limited
      if (res.status === 429) {
        const retryAfter = res.headers.get("Retry-After")
        const delay = retryAfter ? parseInt(retryAfter, 10) * 1000 : Math.min(1000 * 2 ** attempt, 30_000)
        if (attempt < retries) {
          await sleep(delay)
          continue
        }
      }

      // 5xx — server error, retry
      if (res.status >= 500 && attempt < retries) {
        const delay = Math.min(1000 * 2 ** attempt, 30_000)
        await sleep(delay)
        continue
      }

      return res
    } catch (err) {
      clearTimeout(timeoutId)
      lastError = err as Error
      if (attempt < retries) {
        await sleep(Math.min(1000 * 2 ** attempt, 30_000))
      }
    }
  }

  throw lastError ?? new Error("Request failed after retries")
}

function anySignal(signals: AbortSignal[]): AbortSignal {
  const controller = new AbortController()
  for (const s of signals) {
    if (s.aborted) { controller.abort(); break }
    s.addEventListener("abort", () => controller.abort())
  }
  return controller.signal
}

// ─── Session tracking + token refresh ──────────────────────────────────────────
//
// Auth rides on two HttpOnly cookies, so JavaScript cannot read them and cannot
// tell "no session at all" from "access token expired, refresh cookie still
// good". Getting that wrong is what turned one anonymous page view into a burst
// of `/auth/refresh` calls: every 401 asked for a refresh, an anonymous visitor
// has no refresh cookie so each attempt 401'd, and the next 401 asked again —
// until the endpoint's per-minute cap answered 429 and the tab was rate-limiting
// itself. The `isRefreshing` flag only deduplicated *concurrent* attempts; it
// was cleared the moment each one settled, so a burst spread over a few seconds
// still produced one call per 401.
//
// `sessionState` records what we have learned, so the same dead end is walked
// once per tab:
//
//   "unknown" — nothing observed yet. The first 401 gets one refresh attempt,
//               because a 401 genuinely cannot distinguish the two cases above.
//   "active"  — a session exists; a 401 means it needs rotating.
//   "none"    — proven dead. Skip refresh entirely; only a successful sign-in
//               (or a 200 from `/auth/me`) revives it.
type SessionState = "unknown" | "active" | "none"

let sessionState: SessionState = "unknown"
let refreshPromise: Promise<boolean> | null = null
let refreshBlockedUntil = 0

/** How long to stay quiet after an *inconclusive* refresh failure (429 / 5xx / offline). */
const REFRESH_COOLDOWN_MS = 30_000

/** A sign-in succeeded, or `/auth/me` came back 200 — a session definitely exists. */
export function markSessionActive() {
  sessionState = "active"
  refreshBlockedUntil = 0
}

/** Signed out, or a refresh the server definitively refused. */
export function markSessionEnded() {
  sessionState = "none"
  refreshBlockedUntil = 0
}

/** True when a refresh would repeat a known-bad attempt. */
function refreshSuppressed(): boolean {
  if (sessionState === "none") return true
  return Date.now() < refreshBlockedUntil
}

async function doRefresh(): Promise<boolean> {
  try {
    const res = await fetch(`${API_BASE}/api/v1/auth/refresh`, {
      method: "POST",
      credentials: "include",
    })
    if (res.ok) {
      markSessionActive()
      return true
    }
    // 401/403 is a verdict: the refresh cookie is absent, expired or revoked, and
    // it cannot come back on its own. Anything else (429, 5xx) proves nothing —
    // keep the current state and just stop hammering for a cooldown.
    if (res.status === 401 || res.status === 403) {
      markSessionEnded()
    } else {
      refreshBlockedUntil = Date.now() + REFRESH_COOLDOWN_MS
    }
    return false
  } catch {
    refreshBlockedUntil = Date.now() + REFRESH_COOLDOWN_MS
    return false
  }
}

/** Single-flight — a burst of 401s shares one rotation instead of racing. */
function refreshSession(): Promise<boolean> {
  if (!refreshPromise) {
    refreshPromise = doRefresh().finally(() => {
      refreshPromise = null
    })
  }
  return refreshPromise
}

function unauthenticatedMessage(): string {
  return sessionState === "none"
    ? "You need to sign in to view this."
    : "Session expired. Please sign in again."
}

// Routes that are publicly accessible — 401 on these means "unauthenticated", not "session expired"
const PUBLIC_PATHS = ["/", "/markets", "/trades", "/docs", "/faq", "/legal", "/support"]

function isPublicPath(pathname: string) {
  return PUBLIC_PATHS.some((p) => pathname === p || pathname.startsWith(`${p}/`))
}

function redirectToLogin() {
  if (typeof window === "undefined") return
  const { pathname } = window.location
  // Never redirect if already on an auth page
  if (pathname.startsWith("/login") || pathname.startsWith("/signup")) return
  // Don't redirect for public pages — show empty/error state instead
  if (isPublicPath(pathname)) return
  window.location.href = "/login"
}

// ─── Pending request deduplication ──────────────────────────────────────────

const pendingRequests = new Map<string, Promise<unknown>>()

export interface RequestOptions extends Omit<RequestInit, "body"> {
  /** Timeout in ms (default: 10_000) */
  timeout?: number
  /** Number of retries for 5xx/429 (default: 3) */
  retries?: number
  /** Request body — plain object, array, or primitive (serialized to JSON) */
  body?: unknown
}

export function createAbortController(): AbortController {
  return new AbortController()
}

async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const { timeout = 10_000, retries = 3, signal: externalSignal, body: requestBody, ...fetchOptions } = options

  const bodyKey =
    requestBody && typeof requestBody === "string"
      ? requestBody
      : JSON.stringify(requestBody ?? null)
  const cacheKey = `${options.method ?? "GET"}:${path}:${bodyKey}`

  if (options.method === "GET" || !options.method) {
    const existing = pendingRequests.get(cacheKey)
    if (existing) return existing as Promise<T>
  }

  const promise = (async () => {
    const method = (fetchOptions.method as string) ?? "GET"
    const headers = fetchOptions.headers as Record<string, string> | undefined
    const reqBody: BodyInit | undefined =
      requestBody != null && requestBody !== undefined
        ? (typeof requestBody === "string" ? requestBody : JSON.stringify(requestBody as object))
        : undefined
    try {
      // First attempt
      let res = await fetchWithRetry(`${API_BASE}${path}`, {
        credentials: "include",
        headers: { "Content-Type": "application/json", ...headers },
        method,
        body: reqBody,
      }, { retries, timeout, signal: externalSignal ?? undefined })

      // 401 — rotate the access token, then replay the original request once.
      if (res.status === 401 && !headers?.["Authorization"]) {
        // No point asking if we already know the answer, or if a recent attempt
        // was inconclusive: an anonymous visitor then costs zero refresh calls.
        if (refreshSuppressed()) {
          throw new ApiError(unauthenticatedMessage(), 401)
        }

        const refreshed = await refreshSession()
        if (!refreshed) {
          redirectToLogin()
          throw new ApiError(unauthenticatedMessage(), 401)
        }

        // Retry with new session
        res = await fetchWithRetry(`${API_BASE}${path}`, {
          credentials: "include",
          headers: { "Content-Type": "application/json", ...headers },
          method,
          body: reqBody,
        }, { retries, timeout })
      }

      if (!res.ok) {
        const data = await res.json().catch(() => ({}))
        const { message, error_code } = extractMessage(data)
        throw new ApiError(message, res.status, data, error_code)
      }

      return res.json() as Promise<T>
    } finally {
      pendingRequests.delete(cacheKey)
    }
  })()

  if (options.method === "GET" || options.method === "DELETE" || !options.method) {
    pendingRequests.set(cacheKey, promise)
  }

  return promise
}

export const api = {
  get: <T>(path: string, options?: RequestOptions) =>
    request<T>(path, { ...options, method: "GET" }),

  post: <T>(path: string, body?: unknown, options?: RequestOptions) =>
    request<T>(path, { ...options, method: "POST", body }),

  patch: <T>(path: string, body?: unknown, options?: RequestOptions) =>
    request<T>(path, { ...options, method: "PATCH", body }),

  put: <T>(path: string, body?: unknown, options?: RequestOptions) =>
    request<T>(path, { ...options, method: "PUT", body }),

  delete: <T>(path: string, body?: unknown, options?: RequestOptions) =>
    request<T>(path, { ...options, method: "DELETE", body }),
}
