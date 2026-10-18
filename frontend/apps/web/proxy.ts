/**
 * Proxy (Next 16's middleware) • validates session cookies on protected pages,
 * redirects unauthenticated users to login, rotates expired sessions.
 *
 * Runs on the Node.js runtime (Next 16: the `edge` runtime is not supported
 * here), so a plain `fetch` to the API is fine • but its cookies are NOT the
 * browser's. Every call must forward the incoming cookie explicitly and every
 * `Set-Cookie` the API returns must be replayed onto our own response, or the
 * rotated tokens never reach the browser.
 *
 * That mechanism now lives in `@workspace/api-client/session`, because the admin
 * app needs the same thing and a second copy of cookie-replay logic is a second
 * copy of the bug where `Headers.set` overwrites the access cookie with the
 * refresh cookie. Only the *policy* below is app-specific — the storefront
 * protects `/portfolio` and leaves the homepage public; the admin app protects
 * everything but `/login`. Two apps, two honest disagreements, one implementation.
 */

import { NextRequest, NextResponse } from "next/server";
// `config` is reserved below for Next's matcher • alias the app config.
import { config as appConfig } from "@/lib/config";
import {
  ACCESS_COOKIE,
  REFRESH_COOKIE,
  applySecurityHeaders,
  applySetCookies,
  isPlausibleIdentity,
  validateSessionCookies,
} from "@workspace/api-client/session";

const API_BASE = appConfig.apiUrl;

const PUBLIC_PATHS = ["/", "/markets", "/trades", "/faq", "/docs", "/legal", "/support"];

/**
 * Checked before the public fast-path, so the ordering is what makes this work:
 * `/markets` is public, but `/markets/mine` and `/markets/new` are matched here
 * first and never reach it. Listing only `/markets` in either array would leave
 * both of them readable while signed out.
 */
const PROTECTED_PATHS = [
  "/portfolio",
  "/orders",
  "/positions",
  "/transactions",
  "/wallet",
  "/settings",
  "/markets/mine",
  "/markets/new",
];
const AUTH_PATHS = ["/login", "/signup", "/forgot-password", "/reset-password"];

function getCookie(request: NextRequest, name: string): string | null {
  return request.cookies.get(name)?.value ?? null;
}

function nextResponse(setCookies: readonly string[] = []): NextResponse {
  const response = NextResponse.next();
  applySetCookies(response, setCookies);
  applySecurityHeaders(response.headers);
  return response;
}

async function validateSession(request: NextRequest) {
  return validateSessionCookies({
    apiBase: API_BASE,
    accessToken: getCookie(request, ACCESS_COOKIE),
    refreshToken: getCookie(request, REFRESH_COOKIE),
  });
}

function isProtected(pathname: string): boolean {
  return PROTECTED_PATHS.some((p) => pathname === p || pathname.startsWith(`${p}/`));
}

export async function proxy(request: NextRequest) {
  const { pathname } = request.nextUrl;

  // Protected pages • checked BEFORE the public/static fast-path so that a
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
    // Validate before setting • never trust a malformed backend payload.
    if (!isPlausibleIdentity(user)) {
      const redirect = NextResponse.redirect(new URL("/login", request.url));
      applySetCookies(redirect, setCookies);
      return redirect;
    }
    return nextResponse(setCookies);
  }

  // Auth pages • redirect to the target if already logged in
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

  // Static / public paths • no auth needed
  if (
    PUBLIC_PATHS.some((p) => pathname === p || pathname.startsWith(`${p}/`)) ||
    pathname.startsWith("/_next") ||
    pathname.startsWith("/favicon") ||
    pathname.includes(".")
  ) {
    return nextResponse();
  }

  // Everything else • apply security headers only.
  return nextResponse();
}

export const config = {
  matcher: ["/((?!_next/static|_next/image|favicon.ico|opengraph-image).*)"],
};
