/**
 * The admin surface.
 *
 * These exist because the interesting failures in an operator tool are quiet
 * ones. A ban that cancels orders silently leaves a locked balance nobody can
 * reconcile; an audit list that only shows successes is a log of what was
 * permitted; a gate that renders an empty page instead of redirecting reads as
 * a broken app rather than "you are not an admin".
 */
import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

// `vi.mock` factories are hoisted above module-level code, so a plain `const`
// would not be initialised yet when the factory runs.
const adminApi = vi.hoisted(() => ({
  users: vi.fn(),
  user: vi.fn(),
  ban: vi.fn(),
  unban: vi.fn(),
  markets: vi.fn(),
  approveMarket: vi.fn(),
  rejectMarket: vi.fn(),
  actions: vi.fn(),
  auditEvents: vi.fn(),
}));

vi.mock("@workspace/api-client/admin", () => ({ adminApi }));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn() }),
  usePathname: () => "/admin/users",
  redirect: vi.fn(),
}));

const currentUser = { id: "u1", is_admin: true, email: "admin@x.com" };
vi.mock("@/hooks/use-auth", () => ({
  useCurrentUser: () => ({ data: currentUser, isLoading: false }),
}));

vi.mock("sileo", () => ({ sileo: { success: vi.fn(), error: vi.fn() } }));

import { AdminUsersClient } from "@/app/(admin)/users/AdminUsersClient";
import { AdminUserDetailClient } from "@/app/(admin)/users/[userId]/AdminUserDetailClient";
import { AdminAuditClient } from "@/app/(admin)/audit/AdminAuditClient";

function renderWithQuery(ui: React.ReactElement) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>);
}

const userRow = {
  id: "11111111-2222-3333-4444-555555555555",
  email: "trader@example.com",
  username: "trader",
  is_active: true,
  is_admin: false,
  is_email_verified: true,
  is_2fa_enabled: false,
  created_at: "2026-01-01T00:00:00Z",
};

const userDetail = {
  ...userRow,
  is_2fa_pending: false,
  referral_code: null,
  is_deleted: false,
  wallet: { balance: "1000.00", locked_balance: "0.00", currency: "USDC" },
  counts: {
    orders: 3,
    open_orders: 0,
    positions: 1,
    trades: 12,
    transactions: 20,
    disputes: 0,
  },
  findings: [] as string[],
};

beforeEach(() => {
  vi.clearAllMocks();
  adminApi.users.mockResolvedValue({
    data: [userRow],
    page: 1,
    page_size: 20,
    has_more: false,
    total: 1,
  });
  adminApi.user.mockResolvedValue({ success: true, data: userDetail });
  adminApi.ban.mockResolvedValue({
    success: true,
    data: { status: "banned", user_id: userRow.id, cancelled_order_ids: [] },
  });
  adminApi.unban.mockResolvedValue({
    success: true,
    data: { status: "unbanned", user_id: userRow.id },
  });
  adminApi.actions.mockResolvedValue({
    data: [],
    page: 1,
    page_size: 50,
    has_more: false,
    total: 0,
  });
  adminApi.auditEvents.mockResolvedValue({
    data: [],
    page: 1,
    page_size: 50,
    has_more: false,
    total: 0,
  });
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("admin users", () => {
  it("lists users and links to the investigation view", async () => {
    renderWithQuery(<AdminUsersClient />);
    expect(await screen.findByText("trader@example.com")).toBeTruthy();
    expect(screen.getByRole("link", { name: /trader@example.com/ }).getAttribute("href")).toBe(
      `/users/${userRow.id}`
    );
  });

  it("reports the orders a ban cancelled rather than doing it silently", async () => {
    // The funds released are the part an operator has to be able to reconcile,
    // so they are part of the confirmation rather than a hidden side effect.
    const { sileo } = await import("sileo");
    adminApi.ban.mockResolvedValue({
      success: true,
      data: { status: "banned", user_id: userRow.id, cancelled_order_ids: ["o1", "o2", "o3"] },
    });

    renderWithQuery(<AdminUsersClient />);
    const ban = await screen.findByRole("button", { name: /ban/i });
    ban.click();

    await waitFor(() =>
      expect(sileo.success).toHaveBeenCalledWith(
        expect.objectContaining({
          description: expect.stringContaining("3 open order(s) cancelled"),
        })
      )
    );
  });

  it("does not offer to ban another admin", async () => {
    // The server refuses this; a button that only ever 403s makes the tool look
    // broken and trains operators to click things that fail.
    adminApi.users.mockResolvedValue({
      data: [{ ...userRow, is_admin: true }],
      page: 1,
      page_size: 20,
      has_more: false,
      total: 1,
    });

    renderWithQuery(<AdminUsersClient />);
    await screen.findByText("trader@example.com");
    expect(screen.queryByRole("button", { name: /^ban$/i })).toBeNull();
  });

  it("offers unban for a banned account", async () => {
    adminApi.users.mockResolvedValue({
      data: [{ ...userRow, is_active: false }],
      page: 1,
      page_size: 20,
      has_more: false,
      total: 1,
    });

    renderWithQuery(<AdminUsersClient />);
    expect(await screen.findByRole("button", { name: /unban/i })).toBeTruthy();
    expect(screen.queryByRole("button", { name: /^ban$/i })).toBeNull();
  });

  it("says so when a search matches nothing", async () => {
    adminApi.users.mockResolvedValue({
      data: [],
      page: 1,
      page_size: 20,
      has_more: false,
      total: 0,
    });

    renderWithQuery(<AdminUsersClient />);
    expect(await screen.findByText(/no users found/i)).toBeTruthy();
  });
});

describe("admin user detail", () => {
  it("shows the wallet and the counts that answer a balance question", async () => {
    renderWithQuery(<AdminUserDetailClient userId={userRow.id} />);

    expect(await screen.findByText("1000.00 USDC")).toBeTruthy();
    // The ledger is the point of this page; showing the count but not the rows
    // would leave an operator exactly where they started.
    expect(screen.getByRole("button", { name: /transactions/i })).toBeTruthy();
    expect(screen.getByRole("button", { name: /trades/i })).toBeTruthy();
  });

  it("loads the ledger only when asked", async () => {
    renderWithQuery(<AdminUserDetailClient userId={userRow.id} />);
    await screen.findByText("1000.00 USDC");

    expect(adminApi.user).toHaveBeenCalledWith(userRow.id);

    const trades = screen.getByRole("button", { name: /trades/i });
    trades.click();

    await waitFor(() =>
      expect(adminApi.user).toHaveBeenCalledWith(userRow.id, ["trades"])
    );
  });

  it("surfaces the server's findings with an explanation", async () => {
    adminApi.user.mockResolvedValue({
      success: true,
      data: { ...userDetail, findings: ["has_open_orders"] },
    });

    renderWithQuery(<AdminUserDetailClient userId={userRow.id} />);

    expect(await screen.findByText(/has open orders/i)).toBeTruthy();
    // The hint is the difference between a flag and something actionable.
    expect(screen.getByText(/funds are reserved/i)).toBeTruthy();
  });

  it("reports a load failure instead of rendering an empty account", async () => {
    adminApi.user.mockRejectedValue(new Error("User not found"));

    renderWithQuery(<AdminUserDetailClient userId={userRow.id} />);

    expect(await screen.findByText(/could not load this account/i)).toBeTruthy();
  });
});

describe("admin audit", () => {
  it("puts failures one click away", async () => {
    // A trail holding only what went through is a log of what was permitted, so
    // the refused attempts are usually the thing being looked for.
    renderWithQuery(<AdminAuditClient />);

    const filter = await screen.findByRole("button", { name: /failures only/i });
    filter.click();

    await waitFor(() => expect(adminApi.actions).toHaveBeenCalledWith(expect.objectContaining({ success: "failure" })));
  });

  it("defaults to privileged actions, not auth events", async () => {
    renderWithQuery(<AdminAuditClient />);
    await waitFor(() => expect(adminApi.actions).toHaveBeenCalled());
    expect(adminApi.auditEvents).not.toHaveBeenCalled();
  });
});