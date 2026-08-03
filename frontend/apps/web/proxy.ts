/**
 * Auth Middleware — validates session cookies on protected pages, redirects
 * unauthenticated users to login, injects user identity headers for API routes.
 */

import { NextRequest, NextResponse } from "next/server";

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
const SESSION_COOKIE = "access_token";

const PUBLIC_PATHS = ["/", "/markets", "/trades", "/faq", "/docs", "/legal", "/support"];
const PROTECTED_PATHS = ["/portfolio", "/orders", "/positions", "/transactions", "/wallet", "/settings"];

function getSessionCookie(request: NextRequest): string | null {
  return request.cookies.get(SESSION_COOKIE)?.value ?? null;
}

async function validateSession(request: NextRequest) {
  const sessionId = getSessionCookie(request);
  if (!sessionId) return null;

  try {
    const res = await fetch(`${API_BASE}/api/v1/auth/me`, {
      headers: { Cookie: `${SESSION_COOKIE}=${sessionId}`, "Content-Type": "application/json" },
      credentials: "include",
      cache: "no-store",
    });
    if (!res.ok) return null;
    const json = await res.json() as { success: boolean; data: { id: string; email: string; username: string; is_admin: boolean } };
    return json.data ?? null;
  } catch {
    return null;
  }
}

function setSecurityHeaders(response: NextResponse, request: NextRequest) {
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
    setSecurityHeaders(response, request);
    return response;
  }

  // Auth pages — redirect to portfolio if already logged in
  if (pathname.startsWith("/login") || pathname.startsWith("/signup")) {
    const user = await validateSession(request);
    if (user) {
      const next = request.nextUrl.searchParams.get("next") ?? "/portfolio";
      return NextResponse.redirect(new URL(next, request.url));
    }
    const response = NextResponse.next();
    setSecurityHeaders(response, request);
    return response;
  }

  // Protected pages — redirect to login if no session
  if (PROTECTED_PATHS.some((p) => pathname.startsWith(p))) {
    const user = await validateSession(request);
    if (!user) {
      const loginUrl = new URL("/login", request.url);
      loginUrl.searchParams.set("next", pathname);
      return NextResponse.redirect(loginUrl);
    }
    const response = NextResponse.next();
    response.headers.set("x-user-id", user.id);
    response.headers.set("x-user-email", user.email);
    setSecurityHeaders(response, request);
    return response;
  }

  // All other routes (including /api/*) — apply security headers only
  const response = NextResponse.next();
  setSecurityHeaders(response, request);
  return response;
}

export const config = {
  matcher: ["/((?!_next/static|_next/image|favicon.ico|opengraph-image).*)"],
};
