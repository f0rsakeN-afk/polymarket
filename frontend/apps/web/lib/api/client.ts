import { config } from "@/lib/config"

const API_BASE = config.apiUrl

export class ApiError extends Error {
  constructor(
    message: string,
    public status: number,
    public data?: unknown
  ) {
    super(message)
    this.name = "ApiError"
  }
}

export interface ValidationErrorDetail {
  detail: string | ValidationErrorItem[]
}

export interface ValidationErrorItem {
  loc: (string | number)[]
  msg: string
  type: string
}

function extractMessage(data: unknown): string {
  if (!data || typeof data !== "object") return "An error occurred"
  const d = data as Record<string, unknown>
  if (Array.isArray(d.detail)) {
    return (d.detail as ValidationErrorItem[])
      .map((e) => e.msg || e.loc.join("."))
      .join("; ")
  }
  if (typeof d.detail === "string") return d.detail
  return "An error occurred"
}

// ─── Token refresh ───────────────────────────────────────────────────────────

let isRefreshing = false
let refreshSubscribers: Array<(token: string) => void> = []

function subscribeRefresh(cb: (token: string) => void) {
  refreshSubscribers.push(cb)
}

function onRefreshDone(token: string) {
  refreshSubscribers.forEach((cb) => cb(token))
  refreshSubscribers = []
}

async function doRefresh(): Promise<string> {
  const res = await fetch(`${API_BASE}/api/v1/auth/refresh`, {
    method: "POST",
    credentials: "include",
  })
  if (!res.ok) {
    isRefreshing = false
    // Refresh failed — clear all subscribers with empty string to trigger logout
    onRefreshDone("")
    throw new Error("Session expired")
  }
  isRefreshing = false
  onRefreshDone("refreshed")
  return "refreshed"
}

// ─── Pending request deduplication ──────────────────────────────────────────

const pendingRequests = new Map<string, Promise<unknown>>()

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const bodyKey =
    options.body && typeof options.body === "string"
      ? options.body
      : JSON.stringify(options.body ?? null)
  const cacheKey = `${options.method ?? "GET"}:${path}:${bodyKey}`

  if (options.method === "GET" || !options.method) {
    const existing = pendingRequests.get(cacheKey)
    if (existing) return existing as Promise<T>
  }

  const promise = (async () => {
    try {
      const res = await fetch(`${API_BASE}${path}`, {
        credentials: "include",
        headers: {
          "Content-Type": "application/json",
          ...options.headers,
        },
        ...options,
      })

      if (res.status === 401 && !(options.headers as Record<string, string>)?.["Authorization"]) {
        // Token expired — try refresh
        if (!isRefreshing) {
          isRefreshing = true
          doRefresh().catch(() => {
            // ponytail: redirect to login only if not already on an auth page (avoid redirect loops)
            if (typeof window !== "undefined" && !window.location.pathname.startsWith("/login") && !window.location.pathname.startsWith("/signup")) {
              window.location.href = "/login"
            }
          })
        }

        // Wait for refresh to complete (or fail)
        const token = await new Promise<string>((resolve) => {
          subscribeRefresh(resolve)
        })

        if (!token) {
          throw new ApiError("Session expired. Please sign in again.", 401)
        }

        // Retry with new token
        const retryRes = await fetch(`${API_BASE}${path}`, {
          credentials: "include",
          headers: {
            "Content-Type": "application/json",
            ...options.headers,
          },
          ...options,
        })

        if (!retryRes.ok) {
          const data = await retryRes.json().catch(() => ({}))
          throw new ApiError(extractMessage(data), retryRes.status, data)
        }
        return retryRes.json() as Promise<T>
      }

      if (!res.ok) {
        const data = await res.json().catch(() => ({}))
        throw new ApiError(extractMessage(data), res.status, data)
      }

      return res.json() as Promise<T>
    } finally {
      pendingRequests.delete(cacheKey)
    }
  })()

  if (options.method === "GET" || !options.method) {
    pendingRequests.set(cacheKey, promise)
  }

  return promise
}

export const api = {
  get: <T>(path: string, options?: RequestInit) =>
    request<T>(path, { ...options, method: "GET" }),

  post: <T>(path: string, body?: unknown, options?: RequestInit) =>
    request<T>(path, {
      ...options,
      method: "POST",
      body: body ? JSON.stringify(body) : undefined,
    }),

  patch: <T>(path: string, body?: unknown, options?: RequestInit) =>
    request<T>(path, {
      ...options,
      method: "PATCH",
      body: body ? JSON.stringify(body) : undefined,
    }),

  put: <T>(path: string, body?: unknown, options?: RequestInit) =>
    request<T>(path, {
      ...options,
      method: "PUT",
      body: body ? JSON.stringify(body) : undefined,
    }),

  delete: <T>(path: string, body?: unknown, options?: RequestInit) =>
    request<T>(path, {
      ...options,
      method: "DELETE",
      body: body ? JSON.stringify(body) : undefined,
    }),
}
