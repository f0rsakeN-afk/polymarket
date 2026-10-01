/**
 * NEXT_PUBLIC_API_URL / NEXT_PUBLIC_WS_URL are the API *origin*
 * (e.g. https://api.example.com) — NOT an origin+/api/v1.
 *
 * Normalising here means a misconfigured value can never produce
 * `https://host//api/v1/...` (trailing slash) or `.../api/v1/api/v1/...`
 * (someone appending the prefix by hand). Server code that builds canonical
 * URLs can rely on the same normalised value.
 */
function normalizeBase(raw: string | undefined, fallback: string): string {
  const value = (raw ?? "").trim() || fallback
  return value.replace(/\/+$/, "").replace(/\/api\/v1$/, "")
}

/** API origin — every client path in lib/api/* already starts with `/api/v1`. */
const apiOrigin = normalizeBase(process.env.NEXT_PUBLIC_API_URL, "http://localhost:8000")
const wsOrigin = normalizeBase(process.env.NEXT_PUBLIC_WS_URL, "ws://localhost:8000")

export const config = {
  apiUrl: apiOrigin,
  wsUrl: wsOrigin,
  /**
   * Public origin for canonical URLs, robots and sitemap.
   * Falls back to the deployed site origin when the API is not public.
   */
  siteUrl: normalizeBase(process.env.NEXT_PUBLIC_SITE_URL, apiOrigin),
} as const
