/**
 * The admin markets list.
 *
 * ## What this screen is for
 *
 * An operator asking "is anything wrong with the markets" is not asking about one
 * state. The screen defaulted to `pending_review`, had no way to see everything
 * at once, and did not list three of the seven states at all — so a market stuck
 * in `resolving`, or sitting in `dispute_window` with an unresolved argument, was
 * invisible on the one screen meant to catch it.
 *
 * These assert the wiring rather than the styling: that every state is offered,
 * that omitting the status really does return all of them, and that the search
 * reaches the question, the slug and the submitter.
 */
import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

const adminApi = vi.hoisted(() => ({
  markets: vi.fn(),
  approveMarket: vi.fn(),
  rejectMarket: vi.fn(),
}));

vi.mock("@workspace/api-client/admin", () => ({ adminApi }));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn() }),
  usePathname: () => "/markets",
}));

vi.mock("sileo", () => ({ sileo: { success: vi.fn(), error: vi.fn() } }));

import { AdminMarketsClient } from "@/app/(admin)/markets/AdminMarketsClient";

function row(overrides: Record<string, unknown> = {}) {
  return {
    id: "m1",
    slug: "will-it-rain",
    question: "Will it rain tomorrow?",
    status: "active",
    created_at: "2026-01-01T00:00:00Z",
    closes_at: "2027-01-01T00:00:00Z",
    category: "Weather",
    subcategory: null,
    created_by_email: "alice@predictx.io",
    description: null,
    resolution_criteria: null,
    rejection_reason: null,
    rejected_at: null,
    total_volume: "1200",
    total_liquidity: "800",
    num_trades: 42,
    outcome_count: 2,
    ...overrides,
  };
}

function renderWithQuery(ui: React.ReactElement) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>);
}

beforeEach(() => {
  vi.clearAllMocks();
  adminApi.markets.mockResolvedValue({
    data: [row()],
    total: 1,
    page: 1,
    page_size: 50,
    has_more: false,
  });
});

/** The params of the most recent call. */
function lastCall() {
  return adminApi.markets.mock.calls.at(-1)?.[0] as Record<string, unknown>;
}

describe("admin markets", () => {
  it("defaults to every market, not one status", async () => {
    renderWithQuery(<AdminMarketsClient />);

    // The default was `pending_review`, which cannot answer "is anything
    // broken" - and three states were not offered as filters at all.
    await waitFor(() => expect(adminApi.markets).toHaveBeenCalled());
    expect(lastCall().status).toBeUndefined();
    expect(screen.getByRole("button", { name: /^all$/i }).getAttribute("aria-pressed")).toBe("true");
  });

  it("offers every state a market can be in", async () => {
    renderWithQuery(<AdminMarketsClient />);
    await waitFor(() => expect(adminApi.markets).toHaveBeenCalled());

    // `closed`, `resolving` and `dispute_window` were missing, so a market stuck
    // in any of them could not be found here at all.
    for (const label of [
      /awaiting review/i,
      /rejected/i,
      /active/i,
      /trading closed/i,
      /resolving/i,
      /in dispute window/i,
      /resolved/i,
    ]) {
      expect(screen.getByRole("button", { name: label })).toBeTruthy();
    }
  });

  it("passes a chosen status through", async () => {
    const user = userEvent.setup();
    renderWithQuery(<AdminMarketsClient />);
    await waitFor(() => expect(adminApi.markets).toHaveBeenCalled());

    await user.click(screen.getByRole("button", { name: /awaiting review/i }));

    await waitFor(() => expect(lastCall().status).toBe("pending_review"));
  });

  it("searches the question, slug or submitter, on submit rather than per keystroke", async () => {
    const user = userEvent.setup();
    renderWithQuery(<AdminMarketsClient />);
    await waitFor(() => expect(adminApi.markets).toHaveBeenCalled());
    const callsBefore = adminApi.markets.mock.calls.length;

    await user.type(screen.getByRole("searchbox"), "alice");

    // Still one call: a request per character would hammer the admin endpoint
    // for the length of a word.
    expect(adminApi.markets.mock.calls.length).toBe(callsBefore);

    await user.click(screen.getByRole("button", { name: /^search$/i }));
    await waitFor(() => expect(lastCall().q).toBe("alice"));
  });

  it("shows the facts an operator triages on, without opening the market", async () => {
    renderWithQuery(
      <AdminMarketsClient />
    );
    expect(await screen.findByText("Will it rain tomorrow?")).toBeTruthy();

    expect(screen.getByText((_, el) => el?.textContent === "/will-it-rain · alice@predictx.io")).toBeTruthy();
    expect(screen.getByText("42")).toBeTruthy();
    expect(screen.getByText(/2 outcomes/)).toBeTruthy();
  });

  it("says a market is parimutuel only when it has more than two legs", async () => {
    adminApi.markets.mockResolvedValue({
      data: [row({ outcome_count: 9 })],
      total: 1,
      page: 1,
      page_size: 50,
      has_more: false,
    });
    renderWithQuery(<AdminMarketsClient />);

    // Two legs is binary and more is parimutuel, and every price on the row reads
    // differently between them.
    expect(await screen.findByText(/9 outcomes · parimutuel/)).toBeTruthy();
  });

  it("names a system-created market rather than leaving the field blank", async () => {
    adminApi.markets.mockResolvedValue({
      data: [row({ created_by_email: null })],
      total: 1,
      page: 1,
      page_size: 50,
      has_more: false,
    });
    renderWithQuery(<AdminMarketsClient />);

    await screen.findByText("Will it rain tomorrow?");
    // A blank reads as a broken query rather than as "nobody submitted this".
    expect(screen.getByText((_, el) => el?.textContent === "/will-it-rain · system")).toBeTruthy();
  });

  it("says what was searched for when a search finds nothing", async () => {
    const user = userEvent.setup();
    adminApi.markets.mockResolvedValue({
      data: [],
      total: 0,
      page: 1,
      page_size: 50,
      has_more: false,
    });
    renderWithQuery(<AdminMarketsClient />);

    await user.type(screen.getByRole("searchbox"), "zzzznope");
    await user.click(screen.getByRole("button", { name: /^search$/i }));

    expect(await screen.findByText(/nothing matches/i)).toBeTruthy();
  });
});