import { config } from "@/lib/config";

const API_BASE = config.apiUrl;

export class ApiError extends Error {
  constructor(
    message: string,
    public status: number,
    public data?: unknown
  ) {
    super(message);
    this.name = "ApiError";
  }
}

/** Backend validation error shape */
export interface ValidationErrorDetail {
  detail: string | ValidationErrorItem[];
}

export interface ValidationErrorItem {
  loc: (string | number)[];
  msg: string;
  type: string;
}

function extractMessage(data: unknown): string {
  if (!data || typeof data !== "object") return "An error occurred";

  const d = data as Record<string, unknown>;

  // FastAPI validation error list
  if (Array.isArray(d.detail)) {
    return (d.detail as ValidationErrorItem[])
      .map((e) => e.msg || e.loc.join("."))
      .join("; ");
  }

  // Simple string detail
  if (typeof d.detail === "string") return d.detail;

  // Fallback
  return "An error occurred";
}

const pendingRequests = new Map<string, Promise<unknown>>();

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const bodyKey =
    options.body && typeof options.body === "string"
      ? options.body
      : JSON.stringify(options.body ?? null);
  const cacheKey = `${options.method ?? "GET"}:${path}:${bodyKey}`;

  if (options.method === "GET" || !options.method) {
    const existing = pendingRequests.get(cacheKey);
    if (existing) return existing as Promise<T>;
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
      });

      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        throw new ApiError(extractMessage(data), res.status, data);
      }

      return res.json() as Promise<T>;
    } finally {
      pendingRequests.delete(cacheKey);
    }
  })();

  if (options.method === "GET" || !options.method) {
    pendingRequests.set(cacheKey, promise);
  }

  return promise;
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
};
