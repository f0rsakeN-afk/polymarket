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

function extractMessage(data: unknown): { message: string; error_code?: string } {
  if (!data || typeof data !== "object") return { message: "An error occurred" }
  const d = data as Record<string, unknown>

  if (Array.isArray(d.detail)) {
    const items = d.detail as { loc: (string | number)[]; msg: string }[]
    return { message: items.map((e) => e.msg || e.loc.join(".")).join("; ") }
  }

  const ad = d as unknown as ApiErrorData
  if (ad.success === false && ad.error) {
    return { message: ad.error, error_code: ad.error_code }
  }

  if (typeof d.detail === "string") return { message: d.detail }

  return { message: "An error occurred" }
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

// ─── Token refresh ────────────────────────────────────────────────────────────

let isRefreshing = false
let refreshSubscribers: Array<(token: string | null) => void> = []

function subscribeRefresh(cb: (token: string | null) => void) {
  refreshSubscribers.push(cb)
}

function onRefreshDone(token: string | null) {
  refreshSubscribers.forEach((cb) => cb(token))
  refreshSubscribers = []
}

async function doRefresh(): Promise<string | null> {
  try {
    const res = await fetch(`${API_BASE}/api/v1/auth/refresh`, {
      method: "POST",
      credentials: "include",
    })
    if (!res.ok) {
      onRefreshDone(null)
      return null
    }
    onRefreshDone("refreshed")
    return "refreshed"
  } catch {
    onRefreshDone(null)
    return null
  } finally {
    isRefreshing = false
  }
}

// Routes that are publicly accessible — 401 on these means "unauthenticated", not "session expired"
const PUBLIC_PATHS = ["/markets", "/trades"]

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

      // 401 — attempt token refresh
      if (res.status === 401 && !headers?.["Authorization"]) {
        if (!isRefreshing) {
          isRefreshing = true
          doRefresh().then((token) => {
            if (!token) redirectToLogin()
          })
        }

        const token = await new Promise<string | null>((resolve) => {
          subscribeRefresh(resolve)
          setTimeout(() => resolve(null), 10_000)
        })

        if (!token) {
          throw new ApiError("Session expired. Please sign in again.", 401)
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
