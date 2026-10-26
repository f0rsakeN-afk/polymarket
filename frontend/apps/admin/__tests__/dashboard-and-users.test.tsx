/**
 * The dashboard counters and the users list filters.
 *
 * ## Why these tests exist at all
 *
 * Two of the dashboard's counters, and the users page header, were reading a
 * value that could never be anything but `undefined` - the query unwrapped the
 * response to its `data` array and then read `total` off the array. Every
 * assertion still passed. There were no tests over these two screens, and the
 * numbers simply read `0` in production, forever.
 *
 * So the first tests here are deliberately blunt: they assert the number the
 * operator is shown is the number the API returned. Not that the component
 * renders. That it renders the *truth*.
 *
 * ## The failure-mode tests
 *
 * A stat card that cannot distinguish "loading" from "failed" shows a spinner
 * forever. On the landing page of an operator tool, that is the worst possible
 * behaviour for the moment the API is already misbehaving - which is the moment
 * somebody opened it.
 */
import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

const adminApi = vi.hoisted(() => ({
  users: vi.fn(),
  markets: vi.fn(),
  actions: vi.fn(),
  disputes: vi.fn(),
  treasury: vi.fn(),
}));

vi.mock("@workspace/api-client/admin", () => ({ adminApi }));
vi.mock("sileo", () => ({ sileo: { success: vi.fn(), error: vi.fn() } }));
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn() }),
  usePathname: () => "/admin",
  redirect: vi.fn(),
}));

import { AdminDashboardClient } from "@/app/(admin)/AdminDashboardClient";
import { AdminUsersClient } from "@/app/(admin)/users/AdminUsersClient";

function wrap(ui: React.ReactElement) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>);
}

/**
 * The whole stat card behind a label - value and hint together.
 *
 * Scoped to the enclosing link rather than a bare text match, because a label
 * like "Failed privileged actions" is both a card title and the heading of the
 * feed below it. Matching the label alone finds the wrong one.
 */
function statFor(label: string): string {
  const node = screen
    .getAllByText(label)
    .map((el) => el.closest("a"))
    .find(Boolean);
  if (!node) throw new Error(`no stat card labelled ${label}`);
  return node.textContent ?? "";
}

const page = <T,>(data: T[], total: number) => ({
  data,
  page: 1,
  page_size: 20,
  has_more: false,
  total,
});

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

beforeEach(() => {
  vi.clearAllMocks();
  adminApi.markets.mockResolvedValue(page([], 0));
  adminApi.actions.mockResolvedValue(page([], 0));
  adminApi.disputes.mockResolvedValue(page([], 0));
  adminApi.users.mockResolvedValue(page([], 0));
  adminApi.treasury.mockResolvedValue({
    success: true,
    data: {
      balance: "0.00000000",
      total_fees_collected: "0.00000000",
      total_fees_distributed: "0.00000000",
    },
  });
});

describe("dashboard counters report what the API said", () => {
  /**
   * The regression. `total` sits on the response envelope, not on the row array,
   * so unwrapping first and reading `total` second yields `undefined` and the
   * card prints zero - a queue of forty markets reading as an empty one.
   */
  it("shows the real pending count rather than zero", async () => {
    adminApi.markets.mockImplementation(({ status }: { status?: string }) =>
      Promise.resolve(page([], status === "pending_review" ? 41 : 500)),
    );

    wrap(<AdminDashboardClient />);

    await waitFor(() => expect(statFor("Awaiting review")).toContain("41"));
    expect(statFor("Awaiting review")).not.toContain("0 markets");
  });

  it("shows the real open dispute count", async () => {
    adminApi.disputes.mockResolvedValue(page([], 7));

    wrap(<AdminDashboardClient />);

    await waitFor(() => expect(statFor("Open disputes")).toContain("7"));
  });

  it("shows the real failed-action count", async () => {
    adminApi.actions.mockResolvedValue(page([], 3));

    wrap(<AdminDashboardClient />);

    await waitFor(() => expect(statFor("Failed privileged actions")).toContain("3"));
  });

  it("groups large platform counts and puts the total beside live markets", async () => {
    adminApi.users.mockResolvedValue(page([], 12345));
    adminApi.markets.mockImplementation(({ status }: { status?: string }) =>
      Promise.resolve(page([], status === "active" ? 27 : 1204)),
    );

    wrap(<AdminDashboardClient />);

    await waitFor(() => expect(statFor("Users")).toContain("12,345"));
    expect(statFor("Live markets")).toContain("27");
    // The operator needs to know what 27 is a fraction of.
    expect(statFor("Live markets")).toContain("1,204");
  });
});

describe("a dashboard that cannot load says so", () => {
  it("reports the failure instead of spinning forever", async () => {
    adminApi.markets.mockRejectedValue(new Error("boom"));

    wrap(<AdminDashboardClient />);

    await waitFor(() =>
      // Three market-derived cards fail together, so this is not a single card.
      expect(screen.getAllByText("Could not load").length).toBeGreaterThan(0),
    );
  });

  /**
   * A silent failure is worse than a loud one here. "Loading…" forever invites
   * the operator to wait and then act on a stale impression, or to blame the app
   * for a backend outage they could otherwise report.
   *
   * Checked per card rather than by counting "Could not load" occurrences: a
   * count couples the assertion to how many queries happen to be on the screen
   * today, so the next dashboard addition would break a test about honesty.
   */
  it("never leaves the failed cards looking like they are still working", async () => {
    adminApi.markets.mockRejectedValue(new Error("boom"));
    adminApi.users.mockRejectedValue(new Error("boom"));

    wrap(<AdminDashboardClient />);

    await waitFor(() =>
      expect(statFor("Awaiting review")).toContain("Could not load"),
    );
    for (const label of ["Live markets", "Users"]) {
      expect(statFor(label)).toContain("Could not load");
    }
    // The loading affordance is gone for the failed cards.
    expect(screen.queryByText(/^Loading Users$/)).toBeNull();
  });
});

describe("the treasury balance is a string end to end", () => {
  it("renders a balance without float artefacts", async () => {
    // 0.1 + 0.2 = 0.30000000000000004 in binary floating point. Nothing that
    // reads like that belongs in front of an operator.
    adminApi.treasury.mockResolvedValue({
      success: true,
      data: {
        balance: "500000.30000000",
        total_fees_collected: "12000.75000000",
        total_fees_distributed: "4000.00000000",
      },
    });

    wrap(<AdminDashboardClient />);

    await waitFor(() => expect(statFor("Treasury balance")).toContain("500,000.3"));
    const card = statFor("Treasury balance");
    expect(card).not.toMatch(/\d\.\d{9,}/);
    expect(card).toContain("12,000.75");
  });

  it("keeps a whole-number balance whole", async () => {
    // The failure a naive trailing-zero trim introduces: "100" -> "1".
    adminApi.treasury.mockResolvedValue({
      success: true,
      data: {
        balance: "100.00000000",
        total_fees_collected: "0.00000000",
        total_fees_distributed: "0.00000000",
      },
    });

    wrap(<AdminDashboardClient />);

    await waitFor(() => expect(statFor("Treasury balance")).toContain("100"));
    expect(statFor("Treasury balance")).not.toMatch(/\b1\b/);
  });
});

describe("the users list", () => {
  it("shows the real account count in its header", async () => {
    // Also a regression: the header read `total` off the row array, so it said
    // "Loading…" for the life of the app.
    adminApi.users.mockResolvedValue(page([userRow], 1284));

    wrap(<AdminUsersClient />);

    await waitFor(() =>
      expect(screen.getByText("1,284 accounts")).toBeTruthy(),
    );
    expect(screen.queryByText("Loading…")).toBeNull();
  });

  it("pluralises a single account", async () => {
    adminApi.users.mockResolvedValue(page([userRow], 1));

    wrap(<AdminUsersClient />);

    await waitFor(() => expect(screen.getByText("1 account")).toBeTruthy());
  });

  it("asks the API for banned accounts when that filter is chosen", async () => {
    const user = userEvent.setup();
    adminApi.users.mockResolvedValue(page([], 0));
    wrap(<AdminUsersClient />);

    await user.click(screen.getByLabelText("Filter accounts by state"));
    await user.click(await screen.findByRole("option", { name: "Banned" }));

    await waitFor(() =>
      expect(adminApi.users).toHaveBeenCalledWith(
        expect.objectContaining({ status: "banned" }),
      ),
    );
  });

  it("passes the sort through", async () => {
    const user = userEvent.setup();
    wrap(<AdminUsersClient />);

    await user.click(screen.getByLabelText("Sort accounts"));
    await user.click(await screen.findByRole("option", { name: "Email A-Z" }));

    await waitFor(() =>
      expect(adminApi.users).toHaveBeenCalledWith(
        expect.objectContaining({ sort: "email" }),
      ),
    );
  });

  /**
   * Changing a filter while on page 7 shows page 7 of the new result. A
   * banned-only filter over forty accounts leaves page 7 empty, and an empty
   * filtered list reads as "nobody is banned" - the precise opposite of the
   * truth, during the moment somebody is trying to establish it.
   */
  it("returns to the first page when the filter changes", async () => {
    const user = userEvent.setup();
    adminApi.users.mockResolvedValue(page([userRow], 400));
    wrap(<AdminUsersClient />);

    // Walk forward to a later page using the paginator.
    const next = await screen.findByRole("button", { name: /next/i });
    await user.click(next);
    await waitFor(() =>
      expect(adminApi.users).toHaveBeenCalledWith(expect.objectContaining({ page: 2 })),
    );

    await user.click(screen.getByLabelText("Filter accounts by state"));
    await user.click(await screen.findByRole("option", { name: "Banned" }));

    await waitFor(() =>
      expect(adminApi.users).toHaveBeenCalledWith(
        expect.objectContaining({ status: "banned", page: 1 }),
      ),
    );
  });

  it("distinguishes an empty filter result from an empty platform", async () => {
    const user = userEvent.setup();
    adminApi.users.mockResolvedValue(page([], 0));
    wrap(<AdminUsersClient />);

    await user.click(screen.getByLabelText("Filter accounts by state"));
    await user.click(await screen.findByRole("option", { name: "Banned" }));

    // "No users found" during an incident would be read as "nothing is banned".
    await waitFor(() => expect(screen.getByText("No accounts match")).toBeTruthy());
    expect(screen.getByText(/No accounts are banned/)).toBeTruthy();
  });

  it("clears the filter and the search together", async () => {
    const user = userEvent.setup();
    adminApi.users.mockResolvedValue(page([userRow], 5));
    wrap(<AdminUsersClient />);

    await user.type(screen.getByLabelText("Search users"), "trader");
    await user.click(screen.getByRole("button", { name: /^search$/i }));
    await waitFor(() =>
      expect(adminApi.users).toHaveBeenCalledWith(
        expect.objectContaining({ search: "trader" }),
      ),
    );

    await user.click(screen.getByLabelText("Filter accounts by state"));
    await user.click(await screen.findByRole("option", { name: "Banned" }));

    await user.click(await screen.findByRole("button", { name: /clear filters/i }));

    await waitFor(() =>
      expect(adminApi.users).toHaveBeenLastCalledWith(
        expect.objectContaining({ search: undefined, status: "all" }),
      ),
    );
    expect(screen.queryByRole("button", { name: /clear filters/i })).toBeNull();
  });
});
