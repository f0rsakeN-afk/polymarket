/**
 * The account page, and specifically the two ways it can quietly fail.
 *
 * "Download my data" that produces nothing is not a visible failure - the button
 * animates, the toast says success, and the user has no file. And "delete my
 * account" is irreversible: a button that stays enabled when the server will
 * refuse it invites the user to fill in their password, hit the end of the flow,
 * and be told no - which is the worst possible moment to introduce a condition
 * that was knowable up front.
 */
import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor, act } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

let impact: {
  can_delete: boolean;
  open_orders: number;
  unsettled_positions: number;
  retained_even_after_deletion: string[];
  blocked_detail: { message: string; open_orders: number; unsettled_positions: number } | null;
} = {
  can_delete: true,
  open_orders: 0,
  unsettled_positions: 0,
  retained_even_after_deletion: ["trades", "orders", "positions", "transactions"],
  blocked_detail: null,
};

let currentUser: { is_2fa_enabled: boolean } | null = { is_2fa_enabled: false };

const impactCalls: unknown[] = [];
let deleteResponse: { status: number; body: unknown } | null = null;
let deletedWith: { password: string; code?: string } | null = null;

const routerPush = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: routerPush }),
  usePathname: () => "/settings/account",
}));

vi.mock("@/hooks/use-auth", () => ({
  useCurrentUser: () => ({ data: currentUser }),
}));

vi.mock("@/lib/config", () => ({
  config: { apiUrl: "http://localhost:8000", wsUrl: "", siteUrl: "" },
}));

vi.mock("@/lib/api/account", () => ({
  accountApi: {
    deletionImpact: () => {
      impactCalls.push(impact);
      return Promise.resolve({ success: true, data: impact });
    },
    delete: (password: string, code?: string) => {
      deletedWith = { password, code };
      if (deleteResponse && deleteResponse.status !== 200) {
        // A real `ApiError`, not a plain Error with a `status` bolted on: the
        // component branches on `instanceof ApiError`, so a stand-in would test a
        // path the app never takes.
        return Promise.reject(new ApiError("conflict", deleteResponse.status, {}, "CONFLICT"));
      }
      return Promise.resolve({ success: true, message: "Account deleted" });
    },
  },
  downloadAccountExport: vi.fn().mockResolvedValue(undefined),
}));

vi.mock("sileo", () => ({ sileo: { success: vi.fn(), error: vi.fn() } }));

import { ApiError } from "@/lib/api/client";

import { AccountPageClient } from "@/app/(app)/settings/account/AccountPageClient";
import { downloadAccountExport } from "@/lib/api/account";

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <AccountPageClient />
    </QueryClientProvider>
  );
  return client;
}

beforeEach(() => {
  impact = {
    can_delete: true,
    open_orders: 0,
    unsettled_positions: 0,
    retained_even_after_deletion: ["trades", "orders", "positions", "transactions"],
    blocked_detail: null,
  };
  currentUser = { is_2fa_enabled: false };
  impactCalls.length = 0;
  deleteResponse = null;
  deletedWith = null;
  vi.mocked(downloadAccountExport).mockClear();
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("account page • data export", () => {
  it("offers the export rather than burying it", async () => {
    renderPage();
    expect(await screen.findByRole("button", { name: /download my data/i })).toBeTruthy();
  });

  it("calls the export endpoint", async () => {
    renderPage();
    const button = await screen.findByRole("button", { name: /download my data/i });
    await act(async () => {
      button.click();
    });
    await waitFor(() => expect(downloadAccountExport).toHaveBeenCalled());
  });

  it("surfaces a failed export instead of implying success", async () => {
    vi.mocked(downloadAccountExport).mockRejectedValueOnce(new Error("boom"));
    renderPage();
    const button = await screen.findByRole("button", { name: /download my data/i });
    await act(async () => {
      button.click();
    });
    // The button must become usable again: a failed export that leaves the UI
    // stuck on "Building your export…" leaves the user with no way to retry.
    await waitFor(() =>
      expect(screen.getByRole("button", { name: /download my data/i })).toBeTruthy()
    );
  });
});

describe("account page • deletion", () => {
  it("says what is retained rather than implying everything is erased", async () => {
    renderPage();
    // "We deleted your account" and "we deleted their data" are different claims,
    // and only one is true here.
    expect(await screen.findByText(/market's shared history/i)).toBeTruthy();
  });

  it("blocks deletion and explains why when orders are still open", async () => {
    impact = {
      ...impact,
      can_delete: false,
      open_orders: 2,
      blocked_detail: {
        open_orders: 2,
        unsettled_positions: 0,
        message: "Close your open orders before deleting your account.",
      },
    };
    renderPage();

    await waitFor(() =>
      expect(screen.getByRole("button", { name: /delete my account/i })).toHaveProperty(
        "disabled",
        true
      )
    );
    // The user has to be told what to do, not merely that it failed.
    expect(screen.getByRole("alert").textContent).toMatch(/close your open orders/i);
  });

  it("blocks deletion for unsettled positions too", async () => {
    impact = {
      ...impact,
      can_delete: false,
      unsettled_positions: 1,
      blocked_detail: {
        open_orders: 0,
        unsettled_positions: 1,
        message: "Wait for your positions' markets to resolve.",
      },
    };
    renderPage();

    await waitFor(() =>
      expect(screen.getByRole("button", { name: /delete my account/i })).toHaveProperty(
        "disabled",
        true
      )
    );
    expect(screen.getByRole("alert").textContent).toMatch(/resolve/i);
  });

  it("requires a password before it will send anything", async () => {
    renderPage();
    await act(async () => {
      (await screen.findByRole("button", { name: /delete my account/i })).click();
    });

    const confirm = await screen.findByRole("button", { name: /delete permanently/i });
    expect(confirm).toHaveProperty("disabled", true);

    // Nothing has been sent: an empty password must not reach the server at all,
    // because every such request is a live attempt against the account limiter.
    expect(deletedWith).toBeNull();
  });

  it("asks for a 2FA code only when 2FA is enabled", async () => {
    currentUser = { is_2fa_enabled: true };
    renderPage();
    await act(async () => {
      (await screen.findByRole("button", { name: /delete my account/i })).click();
    });

    expect(await screen.findByLabelText(/two-factor code/i)).toBeTruthy();
  });

  it("does not ask for a 2FA code when 2FA is off", async () => {
    renderPage();
    await act(async () => {
      (await screen.findByRole("button", { name: /delete my account/i })).click();
    });

    await screen.findByLabelText(/confirm your password/i);
    expect(screen.queryByLabelText(/two-factor code/i)).toBeNull();
  });

  it("re-checks the blocking conditions after the server refuses", async () => {
    renderPage();
    await act(async () => {
      (await screen.findByRole("button", { name: /delete my account/i })).click();
    });

    const password = await screen.findByLabelText(/confirm your password/i);
    await act(async () => {
      const setter = Object.getOwnPropertyDescriptor(
        window.HTMLInputElement.prototype,
        "value"
      )!.set!;
      setter.call(password, "User!Pass1");
      password.dispatchEvent(new Event("input", { bubbles: true }));
    });

    // The server refuses: something came up that the pre-flight check did not
    // see. The card must reflect the new state rather than staying apparently
    // ready and failing again on the next attempt.
    deleteResponse = { status: 409, body: {} };
    await act(async () => {
      (await screen.findByRole("button", { name: /delete permanently/i })).click();
    });

    await waitFor(() => expect(impactCalls.length).toBeGreaterThan(1));
    expect(deletedWith).toEqual({ password: "User!Pass1", code: undefined });
  });
});