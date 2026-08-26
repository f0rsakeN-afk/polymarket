/**
 * Auth Middleware — validates session cookies on protected pages, redirects
 * unauthenticated users to login, injects user identity headers for API routes.
 */

import { NextRequest, NextResponse } from "next/server";

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
const ACCESS_COOKIE = "access_token";
const REFRESH_COOKIE = "refresh_token";

const PUBLIC_PATHS = ["/", "/markets", "/trades", "/faq", "/docs", "/legal", "/support"];
const PROTECTED_PATHS = ["/portfolio", "/orders", "/positions", "/transactions", "/wallet", "/settings"];

function getCookie(request: NextRequest, name: string): string | null {
  return request.cookies.get(name)?.value ?? null;
}

async function tryRefresh(request: NextRequest): Promise<{ ok: boolean }> {
  try {
    const refreshToken = getCookie(request, REFRESH_COOKIE);
    if (!refreshToken) return { ok: false };
    const res = await fetch(`${API_BASE}/api/v1/auth/refresh`, {
      method: "POST",
      credentials: "include",
      cache: "no-store",
    });
    return { ok: res.ok };
  } catch {
    return { ok: false };
  }
}

async function validateSession(request: NextRequest): Promise<{
  user: { id: string; email: string; username: string; is_admin: boolean } | null;
  refreshed: boolean;
}> {
  // Try with current access token
  const accessToken = getCookie(request, ACCESS_COOKIE);
  if (accessToken) {
    try {
      const res = await fetch(`${API_BASE}/api/v1/auth/me`, {
        headers: { Cookie: `${ACCESS_COOKIE}=${accessToken}`, "Content-Type": "application/json" },
        credentials: "include",
        cache: "no-store",
      });
      if (res.ok) {
        const json = await res.json() as {
          success: boolean;
          data: { id: string; email: string; username: string; is_admin: boolean };
        };
        return { user: json.data ?? null, refreshed: false };
      }
      // 401 — token expired, try refresh
      if (res.status === 401) {
        const refreshed = await tryRefresh(request);
        if (!refreshed.ok) return { user: null, refreshed: false };
        // Retry /me with new cookies
        const retryRes = await fetch(`${API_BASE}/api/v1/auth/me`, {
          credentials: "include",
          cache: "no-store",
        });
        if (retryRes.ok) {
          const json = await retryRes.json() as {
            success: boolean;
            data: { id: string; email: string; username: string; is_admin: boolean };
          };
          return { user: json.data ?? null, refreshed: true };
        }
      }
    } catch {
      // network error — let through, client will handle
    }
  }

  return { user: null, refreshed: false };
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

export default async function proxy(request: NextRequest) {
  const { pathname } = request.nextUrl;

  // Static / public paths — no auth needed
  if (
    PUBLIC_PATHS.some((p) => pathname === p || pathname.startsWith(`${p}/`)) ||
    pathname.startsWith("/_next") ||
    pathname.startsWith("/favicon") ||
    pathname.includes(".")
  ) {
    const response = NextResponse.next();
    setSecurityHeaders(response);
    return response;
  }

  // Auth pages — redirect to portfolio if already logged in
  if (pathname.startsWith("/login") || pathname.startsWith("/signup")) {
    const { user } = await validateSession(request);
    if (user) {
      const rawNext = request.nextUrl.searchParams.get("next") ?? "/portfolio";
    if (!rawNext.startsWith("/") || rawNext.includes("//")) {
      return NextResponse.redirect(new URL("/portfolio", request.url));
    }
    return NextResponse.redirect(new URL(rawNext, request.url));
    }
    const response = NextResponse.next();
    setSecurityHeaders(response);
    return response;
  }

  // Protected pages — redirect to login if no session
  if (PROTECTED_PATHS.some((p) => pathname.startsWith(p))) {
    const { user } = await validateSession(request);
    if (!user) {
      const loginUrl = new URL("/login", request.url);
      loginUrl.searchParams.set("next", pathname);
      return NextResponse.redirect(loginUrl);
    }
    // Validate before setting — never trust raw backend response
    const isValidUuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(user.id)
    const isValidEmail = /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(user.email)
    if (!isValidUuid || !isValidEmail) {
      // Malformed identity — treat as unauthenticated rather than leak garbage
      return NextResponse.redirect(new URL("/login", request.url))
    }

    const response = NextResponse.next();
    response.headers.set("x-user-id", user.id);
    response.headers.set("x-user-email", user.email);
    setSecurityHeaders(response);
    return response;
  }

  // All other routes (including /api/*) — apply security headers only
  const response = NextResponse.next();
  setSecurityHeaders(response);
  return response;
}

export const config = {
  matcher: ["/((?!_next/static|_next/image|favicon.ico|opengraph-image).*)"],
};
