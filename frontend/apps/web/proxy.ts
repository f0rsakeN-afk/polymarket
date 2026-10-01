/**
 * Proxy (Next 16's middleware) — validates session cookies on protected pages,
 * redirects unauthenticated users to login, rotates expired sessions.
 *
 * Runs on the Node.js runtime (Next 16: the `edge` runtime is not supported
 * here), so a plain `fetch` to the API is fine — but its cookies are NOT the
 * browser's. Every call must forward the incoming cookie explicitly and every
 * `Set-Cookie` the API returns must be replayed onto our own response, or the
 * rotated tokens never reach the browser.
 */

import { NextRequest, NextResponse } from "next/server";
// `config` is reserved below for Next's matcher — alias the app config.
import { config as appConfig } from "@/lib/config";

const API_BASE = appConfig.apiUrl;
const ACCESS_COOKIE = "access_token";
const REFRESH_COOKIE = "refresh_token";

const PUBLIC_PATHS = ["/", "/markets", "/trades", "/faq", "/docs", "/legal", "/support"];
const PROTECTED_PATHS = ["/portfolio", "/orders", "/positions", "/transactions", "/wallet", "/settings"];
const AUTH_PATHS = ["/login", "/signup", "/forgot-password", "/reset-password"];

/** Shape of GET /api/v1/auth/me → data */
interface Identity {
  id: string;
  email: string;
  username: string;
  is_admin: boolean;
}

interface SessionCheck {
  user: Identity | null;
  /** Set-Cookie headers returned by the API that must reach the browser. */
  setCookies: string[];
}

function getCookie(request: NextRequest, name: string): string | null {
  return request.cookies.get(name)?.value ?? null;
}

function readSetCookies(res: Response): string[] {
  const headers = res.headers as Headers & { getSetCookie?: () => string[] };
  if (typeof headers.getSetCookie === "function") return headers.getSetCookie();
  const raw = headers.get("set-cookie");
  return raw ? [raw] : [];
}

/** `Set-Cookie` must be appended one at a time — a single set overwrites. */
function applySetCookies(response: NextResponse, setCookies: string[]) {
  for (const cookie of setCookies) response.headers.append("set-cookie", cookie);
}

async function fetchMe(cookieHeader: string): Promise<Identity | null> {
  const res = await fetch(`${API_BASE}/api/v1/auth/me`, {
    headers: { Cookie: cookieHeader },
    cache: "no-store",
  });
  if (!res.ok) return null;
  const json = (await res.json()) as { success: boolean; data?: Identity };
  return json.data ?? null;
}

async function validateSession(request: NextRequest): Promise<SessionCheck> {
  const accessToken = getCookie(request, ACCESS_COOKIE);
  if (accessToken) {
    try {
      const user = await fetchMe(`${ACCESS_COOKIE}=${accessToken}`);
      if (user) return { user, setCookies: [] };
    } catch {
      // network error — fall through to refresh, then to "not logged in"
    }
  }

  // Access token missing/expired: rotate via the refresh token.
  const refreshToken = getCookie(request, REFRESH_COOKIE);
  if (!refreshToken) return { user: null, setCookies: [] };

  let refreshRes: Response;
  try {
    refreshRes = await fetch(`${API_BASE}/api/v1/auth/refresh`, {
      method: "POST",
      headers: { Cookie: `${REFRESH_COOKIE}=${refreshToken}` },
      cache: "no-store",
    });
  } catch {
    return { user: null, setCookies: [] };
  }

  const setCookies = readSetCookies(refreshRes);
  if (!refreshRes.ok) return { user: null, setCookies };

  const newAccess = setCookies
    .map((c) => c.split(";")[0]?.trim())
    .find((c) => c?.startsWith(`${ACCESS_COOKIE}=`));
  if (!newAccess) return { user: null, setCookies };

  try {
    return { user: await fetchMe(newAccess), setCookies };
  } catch {
    return { user: null, setCookies };
  }
}

function setSecurityHeaders(response: NextResponse) {
  response.headers.set("X-Content-Type-Options", "nosniff");
  response.headers.set("X-Frame-Options", "DENY");
  response.headers.set("X-XSS-Protection", "1; mode=block");
  response.headers.set("Referrer-Policy", "strict-origin-when-cross-origin");
  if (process.env.NODE_ENV === "production") {
    response.headers.set("Strict-Transport-Security", "max-age=31536000; includeSubDomains");
  }
}

function nextResponse(setCookies: string[] = []): NextResponse {
  const response = NextResponse.next();
  applySetCookies(response, setCookies);
  setSecurityHeaders(response);
  return response;
}

function isProtected(pathname: string): boolean {
  return PROTECTED_PATHS.some((p) => pathname === p || pathname.startsWith(`${p}/`));
}

export async function proxy(request: NextRequest) {
  const { pathname } = request.nextUrl;

  // Protected pages — checked BEFORE the public/static fast-path so that a
  // lookalike URL (e.g. `/settings/report.json`) can never skip authentication.
  if (isProtected(pathname)) {
    const { user, setCookies } = await validateSession(request);
    if (!user) {
      const loginUrl = new URL("/login", request.url);
      loginUrl.searchParams.set("next", pathname);
      const redirect = NextResponse.redirect(loginUrl);
      applySetCookies(redirect, setCookies);
      return redirect;
    }
    // Validate before setting — never trust a malformed backend payload.
    const isValidUuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(user.id);
    const isValidEmail = /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(user.email);
    if (!isValidUuid || !isValidEmail) {
      const redirect = NextResponse.redirect(new URL("/login", request.url));
      applySetCookies(redirect, setCookies);
      return redirect;
    }
    return nextResponse(setCookies);
  }

  // Auth pages — redirect to the target if already logged in
  if (AUTH_PATHS.some((p) => pathname === p || pathname.startsWith(`${p}/`))) {
    const { user, setCookies } = await validateSession(request);
    if (user) {
      const rawNext = request.nextUrl.searchParams.get("next") ?? "/portfolio";
      const target =
        rawNext.startsWith("/") && !rawNext.startsWith("//")
          ? rawNext
          : "/portfolio";
      const redirect = NextResponse.redirect(new URL(target, request.url));
      applySetCookies(redirect, setCookies);
      return redirect;
    }
    return nextResponse(setCookies);
  }

  // Static / public paths — no auth needed
  if (
    PUBLIC_PATHS.some((p) => pathname === p || pathname.startsWith(`${p}/`)) ||
    pathname.startsWith("/_next") ||
    pathname.startsWith("/favicon") ||
    pathname.includes(".")
  ) {
    return nextResponse();
  }

  // Everything else — apply security headers only.
  return nextResponse();
}

export const config = {
  matcher: ["/((?!_next/static|_next/image|favicon.ico|opengraph-image).*)"],
};
