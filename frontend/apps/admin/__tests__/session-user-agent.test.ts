/**
 * The proxy's session check, and the User-Agent it must forward.
 *
 * ## The bug this pins
 *
 * The backend fingerprints every refresh token by `User-Agent` and revokes it on
 * a mismatch (`Device mismatch`). In the browser that is free — `fetch` sends the
 * real UA — so the storefront never noticed anything was wrong. In a proxy it is
 * not: `validateSessionCookies` runs in Node, whose `fetch` sends its own UA.
 *
 * The result was that the *first* refresh after the access token expired (15
 * minutes) looked like a different device, the token was revoked, and the
 * operator was bounced to the login screen — on the admin app specifically, and
 * with their storefront session destroyed as a side effect, because the
 * fingerprint check revokes the shared token rather than just refusing.
 *
 * Asserted here because the failure is invisible from the outside: the proxy
 * still works for the fifteen minutes a token lasts, and every test that signs
 * in with a fresh token passes.
 */
import { describe, expect, it, vi } from "vitest";

import {
  ACCESS_COOKIE,
  REFRESH_COOKIE,
  refreshRequestHeaders,
  validateSessionCookies,
} from "@workspace/api-client/session";

const API = "https://api.test";
const UA = "Mozilla/5.0 (X11; Linux x86_64) Chrome/131";

/**
 * A real UUID and a dotted email, because `isPlausibleIdentity` rejects anything
 * else — the proxy refuses to trust a redirect target built from `user.id`, so
 * it checks the shape before use. A fixture that does not satisfy it makes every
 * test here assert against `user: null` and pass for the wrong reason.
 */
const IDENTITY = {
  id: "11111111-2222-4333-8444-555555555555",
  email: "admin@predictx.test",
  is_admin: true,
};

function ok(body: unknown, headers: Record<string, string> = {}) {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { "content-type": "application/json", ...headers },
  });
}

describe("refresh headers", () => {
  it("forwards the browser's User-Agent", () => {
    const headers = refreshRequestHeaders("tok", UA);

    // Without this the backend sees Node's UA, calls it a different device, and
    // revokes a token the user is still holding.
    expect(headers["User-Agent"]).toBe(UA);
    expect(headers.Cookie).toBe(`${REFRESH_COOKIE}=tok`);
  });

  it("omits the header entirely when there is no UA, rather than sending an empty one", () => {
    // An empty header is still a value, and the backend compares it against the
    // fingerprint and finds it different — the same failure wearing a disguise.
    // With no header it falls back to what the client sends, which is strictly
    // better than asserting a device that isn't there.
    const headers = refreshRequestHeaders("tok", null);

    expect("User-Agent" in headers).toBe(false);
    expect(headers.Cookie).toBe(`${REFRESH_COOKIE}=tok`);
    expect(headers["User-Agent"]).toBeUndefined();
  });
});

describe("validateSessionCookies", () => {
  it("sends the caller's User-Agent on the refresh", async () => {
    const urls: string[] = [];
    const seen: Array<Record<string, string>> = [];
    const fetchImpl = vi.fn(async (url: string, init?: RequestInit) => {
      urls.push(url);
      seen.push((init?.headers ?? {}) as Record<string, string>);
      if (url.endsWith("/auth/refresh")) {
        return ok(
          { success: true, data: { status: "refreshed" } },
          { "set-cookie": `${ACCESS_COOKIE}=new; Path=/` }
        );
      }
      return ok({ success: true, data: IDENTITY });
    }) as unknown as typeof fetch;

    await validateSessionCookies({
      apiBase: API,
      accessToken: null, // force the refresh path
      refreshToken: "rt",
      userAgent: UA,
      fetchImpl,
    });

    // A successful refresh is followed by a `/auth/me` read to learn who the new
    // token belongs to, so two calls is correct — the assertion is on the *first*
    // one, which is the refresh.
    const refreshAt = urls.findIndex((u) => u.endsWith("/auth/refresh"));
    expect(refreshAt).toBe(0);
    expect(seen[refreshAt]?.["User-Agent"]).toBe(UA);
  });

  it("still works when no UA is supplied", async () => {
    const fetchImpl = vi.fn(async (url: string) =>
      url.endsWith("/auth/refresh")
        ? ok(
            { success: true, data: { status: "refreshed" } },
            { "set-cookie": `${ACCESS_COOKIE}=new; Path=/` }
          )
        : ok({ success: true, data: IDENTITY })
    ) as unknown as typeof fetch;

    const result = await validateSessionCookies({
      apiBase: API,
      accessToken: null,
      refreshToken: "rt",
      userAgent: null,
      fetchImpl,
    });

    expect(result.user).toMatchObject({ is_admin: true });
    expect(result.setCookies.length).toBeGreaterThan(0);
  });
});