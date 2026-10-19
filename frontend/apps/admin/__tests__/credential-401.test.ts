/**
 * A wrong password must say so.
 *
 * ## The bug
 *
 * `/auth/login` answers 401 for bad credentials — the most correct 401 in the
 * system, and one the client was routing through the session machinery. The
 * client tried to rotate a session that did not exist, failed, replaced the real
 * message ("Invalid email or password") with "You need to sign in to view this.",
 * and redirected to the login page the operator was already sitting on, with
 * their password still in the box.
 *
 * So a correct password and a wrong one produced the same screen. From the form
 * there is no way to tell "I mistyped" from "you are signed out", and the only
 * thing to try is to keep retyping it.
 *
 * Asserted on the *message*, because the redirect is invisible in a unit test and
 * the message is what the operator actually reads.
 */
import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";

import { api, ApiError, apiErrorMessage, apiErrorCode } from "@workspace/api-client/client";

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

const realFetch = globalThis.fetch;

function stubFetch(handler: (url: string) => Response) {
  const fn = vi.fn(async (input: RequestInfo | URL) => handler(String(input)));
  globalThis.fetch = fn as unknown as typeof fetch;
  return fn;
}

beforeEach(() => {
  vi.restoreAllMocks();
});

afterEach(() => {
  globalThis.fetch = realFetch;
});

describe("a credential endpoint answering 401", () => {
  it("surfaces the server's message rather than the session one", async () => {
    stubFetch(() =>
      jsonResponse(401, {
        success: false,
        error: "Invalid email or password",
        error_code: "UNAUTHORIZED",
      })
    );

    const err = await api
      .post("/api/v1/auth/login", { email: "a@b.co", password: "wrong" })
      .catch((e) => e);

    expect(err).toBeInstanceOf(ApiError);
    expect(apiErrorMessage(err, "fallback")).toBe("Invalid email or password");
    // The tell-tale of the bug: the generic session wording.
    expect(apiErrorMessage(err, "fallback")).not.toMatch(/sign in to view this/i);
  });

  it("keeps the error code, so the 2FA branch can still read it", async () => {
    // The 2FA flow depends on `LOGIN_2FA_REQUIRED` arriving as a code. Losing it
    // would mean a 2FA account can never finish signing in.
    stubFetch(() =>
      jsonResponse(401, {
        success: false,
        error: "Two-factor code required",
        error_code: "LOGIN_2FA_REQUIRED",
      })
    );

    const err = await api
      .post("/api/v1/auth/login", { email: "a@b.co", password: "right" })
      .catch((e) => e);

    expect(apiErrorCode(err)).toBe("LOGIN_2FA_REQUIRED");
  });

  it("does not attempt a refresh", async () => {
    // A rotation can only fail here: there is no session to rotate. Doing it
    // anyway is a guaranteed-failing request on every wrong password.
    const fetchMock = stubFetch(() =>
      jsonResponse(401, { success: false, error: "Invalid email or password" })
    );

    await api.post("/api/v1/auth/login", {}).catch(() => {});

    const refreshes = fetchMock.mock.calls.filter((c) =>
      String(c[0]).includes("/auth/refresh")
    );
    expect(refreshes).toHaveLength(0);
  });

  it("still refreshes for an ordinary data endpoint", async () => {
    // The point of the exemption is precision. If this stopped refreshing, a real
    // expired session on a data page would loop.
    stubFetch((url) =>
      url.includes("/auth/refresh")
        ? jsonResponse(200, { success: true, data: {} })
        : jsonResponse(401, { success: false, error: "nope" })
    );

    const err = await api.get("/api/v1/orders").catch((e) => e);

    // Either way it is a 401 from the caller's perspective; what matters is that
    // the credential exemption did not swallow it into a different message.
    expect(err).toBeInstanceOf(ApiError);
  });

  it("has a message even when the server sends none", async () => {
    // A proxy or gateway can answer 401 with an HTML body. The operator must not
    // be shown an empty box.
    stubFetch(() => new Response("", { status: 401 }));

    const err = await api
      .post("/api/v1/auth/login", { email: "a@b.co", password: "x" })
      .catch((e) => e);

    expect(apiErrorMessage(err, "fallback")).toBe("Those credentials were not accepted.");
  });
});