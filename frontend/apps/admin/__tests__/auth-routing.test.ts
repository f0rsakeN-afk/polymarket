/**
 * Where a terminal 401 sends the browser.
 *
 * ## The bug these exist for
 *
 * The shared client hardcoded the *storefront's* public routes — `["/", "/markets",
 * "/trades", …]` — inside a module the admin app also imports. The admin app has a
 * `/markets` route (the moderation queue) and its dashboard is at `/`. So
 * `isPublicPath` returned true for both, `redirectToLogin` returned early, and an
 * operator whose session had just expired was **left on the page** with
 * "unauthenticated" errors and no route out.
 *
 * Two failures in one: an expired session in the admin app, and a test that
 * asserts on `window.location.href` being assigned rather than on the *decision*,
 * which is the part that was wrong.
 */
import { describe, expect, it, vi } from "vitest";

import { configureAuthRouting, shouldRedirectToLogin } from "@workspace/api-client/client";

describe("shouldRedirectToLogin", () => {
  it("defaults to redirecting, because an unconfigured app has no known public routes", async () => {
    // A fresh module, because every other test here calls `configureAuthRouting`
    // and that mutates module state. Asserting the default *after* configuring it
    // is not testing the default at all — it is testing what the test just set.
    // That version of this test passed even with the storefront's hardcoded
    // routes put back, which is exactly the bug it exists to prevent.
    vi.resetModules();
    const fresh = await import("@workspace/api-client/client");

    expect(fresh.shouldRedirectToLogin("/")).toBe(true);
    expect(fresh.shouldRedirectToLogin("/markets")).toBe(true);
    expect(fresh.shouldRedirectToLogin("/users")).toBe(true);
    expect(fresh.shouldRedirectToLogin("/disputes")).toBe(true);
  });

  it("lets a declared public route answer with its own UI instead", () => {
    configureAuthRouting({
      publicPaths: ["/", "/markets"],
      loginPath: "/login",
    });

    expect(shouldRedirectToLogin("/")).toBe(false);
    expect(shouldRedirectToLogin("/markets")).toBe(false);
    // ...and everything else still redirects.
    expect(shouldRedirectToLogin("/wallet")).toBe(true);
  });

  it("matches subpaths of a public route", () => {
    configureAuthRouting({ publicPaths: ["/markets"], loginPath: "/login" });

    expect(shouldRedirectToLogin("/markets/some-market")).toBe(false);
  });

  it("does not treat a longer sibling path as public", () => {
    // `/marketsX` shares a prefix with `/markets`. Prefix matching without a
    // boundary is how `/private-markets` quietly becomes public.
    configureAuthRouting({ publicPaths: ["/markets"], loginPath: "/login" });

    expect(shouldRedirectToLogin("/marketsX")).toBe(true);
    expect(shouldRedirectToLogin("/private-markets")).toBe(true);
  });

  it("never redirects to the login page itself", () => {
    configureAuthRouting({ publicPaths: [], loginPath: "/login" });

    expect(shouldRedirectToLogin("/login")).toBe(false);
    expect(shouldRedirectToLogin("/login/reset")).toBe(false);
  });

  it("honours a custom login path", () => {
    configureAuthRouting({ publicPaths: [], loginPath: "/sign-in" });

    expect(shouldRedirectToLogin("/sign-in")).toBe(false);
    expect(shouldRedirectToLogin("/dashboard")).toBe(true);
  });

  it("is per-app, so the admin policy does not inherit the storefront's", () => {
    // The regression itself, stated as a test: the admin app's `/markets` and `/`
    // must redirect even though the storefront's do not.
    configureAuthRouting({
      publicPaths: ["/", "/markets", "/trades", "/faq", "/docs", "/legal", "/support"],
      loginPath: "/login",
    });
    expect(shouldRedirectToLogin("/markets")).toBe(false);

    configureAuthRouting({ publicPaths: [], loginPath: "/login" });
    expect(shouldRedirectToLogin("/markets")).toBe(true);
    expect(shouldRedirectToLogin("/")).toBe(true);
  });

  it("merges successive calls rather than dropping earlier keys", () => {
    configureAuthRouting({ publicPaths: ["/faq"], loginPath: "/login" });
    // `publicPaths` replaced wholesale, `loginPath` preserved.
    configureAuthRouting({ loginPath: "/login" });

    expect(shouldRedirectToLogin("/faq")).toBe(false);
    expect(shouldRedirectToLogin("/")).toBe(true);
  });
});