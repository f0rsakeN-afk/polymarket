/**
 * Bulk approval on the moderation queue.
 *
 * The failure modes that matter here are all quiet. A selection that widens past
 * what the operator can see publishes markets nobody looked at. A summary that
 * says "20 approved" after nineteen succeeded hides a market that did not
 * publish. A selection that outlives its page sends ids for markets that have
 * already moved on. Every test here is one of those.
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

const sileo = vi.hoisted(() => ({ success: vi.fn(), error: vi.fn() }));
vi.mock("sileo", () => ({ sileo }));

const searchParams = vi.hoisted(() => ({ current: new URLSearchParams() }));
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn() }),
  usePathname: () => "/markets",
  useSearchParams: () => searchParams.current,
}));

import { AdminMarketsClient } from "@/app/(admin)/markets/AdminMarketsClient";

const MARKET_ID = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee";

function row(overrides: Record<string, unknown> = {}) {
  return {
    id: MARKET_ID,
    slug: "bitcoin-150k-2027",
    question: "Will Bitcoin reach $150k in 2027?",
    status: "pending_review",
    num_trades: 0,
    total_volume: "0",
    total_liquidity: "0",
    outcome_count: 2,
    created_by_email: "trader@example.com",
    created_at: "2026-01-01T00:00:00Z",
    closes_at: "2027-01-01T00:00:00Z",
    rejection_reason: null,
    ...overrides,
  };
}

const page = <T,>(data: T[]) => ({
  data,
  total: data.length,
  page: 1,
  page_size: 50,
  has_more: false,
});

function wrap() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <AdminMarketsClient />
    </QueryClientProvider>
  );
}

/** The bulk bar's text. The count is split across spans, so match the region. */
function barText(): string {
  return screen.getByRole("region", { name: /bulk actions/i }).textContent ?? "";
}

/** Get to the pending queue, where the bulk controls exist. */
async function openPendingQueue() {
  const user = userEvent.setup();
  wrap();
  await user.click(await screen.findByRole("button", { name: /awaiting review/i }));
  return user;
}

beforeEach(() => {
  vi.clearAllMocks();
  searchParams.current = new URLSearchParams();
  adminApi.markets.mockResolvedValue(page([row()]));
  adminApi.approveMarket.mockResolvedValue({ success: true, data: { status: "active" } });
});

describe("the bulk controls only exist where they can act", () => {
  it("offers no selection on the default list", async () => {
    wrap();
    await screen.findByText(row().question);

    // "All" includes approved, closed and rejected markets. A checkbox there
    // offers to select things the Approve button cannot act on.
    expect(screen.queryByRole("checkbox")).toBeNull();
  });

  it("offers selection on the pending queue", async () => {
    await openPendingQueue();

    expect(
      await screen.findByRole("checkbox", { name: /select will bitcoin/i }),
    ).toBeTruthy();
  });

  it("keeps the single-market Approve button alongside it", async () => {
    await openPendingQueue();

    expect(
      (await screen.findAllByRole("button", { name: /^approve$/i })).length,
    ).toBeGreaterThan(0);
  });
});

describe("selecting", () => {
  it("counts the selection and offers to approve it", async () => {
    const user = await openPendingQueue();

    await user.click(
      await screen.findByRole("checkbox", { name: /select will bitcoin/i }),
    );

    await waitFor(() => expect(barText()).toContain("1 of 1 selected"));
    expect(screen.getByRole("button", { name: /approve 1/i })).toBeTruthy();
  });

  it("says how many are selected rather than only what is not", async () => {
    adminApi.markets.mockResolvedValue(
      page([row(), row({ id: "2", question: "Second?" }), row({ id: "3", question: "Third?" })]),
    );
    const user = await openPendingQueue();

    await user.click(await screen.findByRole("checkbox", { name: /select will bitcoin/i }));

    // With two of three chosen, "3 selected" would be a lie and "1" would not
    // say which. The count is the whole point of the bar.
    await waitFor(() => expect(barText()).toContain("of 3 selected"));
  });

  it("clears the selection on request", async () => {
    const user = await openPendingQueue();

    await user.click(await screen.findByRole("checkbox", { name: /select will bitcoin/i }));
    await user.click(await screen.findByRole("button", { name: /clear/i }));

    await waitFor(() => expect(screen.queryByText(/selected/)).toBeNull());
  });

  it("does nothing to the queue just by selecting", async () => {
    const user = await openPendingQueue();

    await user.click(await screen.findByRole("checkbox", { name: /select will bitcoin/i }));

    // Selection is not approval. An accidental tick must never publish.
    expect(adminApi.approveMarket).not.toHaveBeenCalled();
  });
});

describe("confirming", () => {
  it("names the market before publishing it", async () => {
    const user = await openPendingQueue();

    await user.click(await screen.findByRole("checkbox", { name: /select will bitcoin/i }));
    await user.click(await screen.findByRole("button", { name: /approve 1/i }));

    // The question is on the last screen before it goes live - named in the
    // dialog, not merely counted.
    await waitFor(() =>
      expect(
        screen.getAllByText(row().question).length,
      ).toBeGreaterThan(1),
    );
    expect(adminApi.approveMarket).not.toHaveBeenCalled();
  });

  it("abandons the approval on cancel", async () => {
    const user = await openPendingQueue();

    await user.click(await screen.findByRole("checkbox", { name: /select will bitcoin/i }));
    await user.click(await screen.findByRole("button", { name: /approve 1/i }));
    await user.click(await screen.findByRole("button", { name: /cancel/i }));

    expect(adminApi.approveMarket).not.toHaveBeenCalled();
  });

  it("publishes only after the confirmation", async () => {
    const user = await openPendingQueue();

    await user.click(await screen.findByRole("checkbox", { name: /select will bitcoin/i }));
    await user.click(await screen.findByRole("button", { name: /approve 1/i }));
    await user.click(await screen.findByRole("button", { name: /^approve 1$/i, hidden: false }));

    await waitFor(() => expect(adminApi.approveMarket).toHaveBeenCalledTimes(1));
    expect(adminApi.approveMarket).toHaveBeenCalledWith(MARKET_ID);
  });
});

describe("the outcome is reported honestly", () => {
  /**
   * The failure that matters most. Nineteen of twenty going through is a fact
   * about the queue, and "20 approved" would leave a submittable market sitting
   * untradable with nothing pointing at it.
   */
  it("reports a partial failure as a partial failure", async () => {
    adminApi.markets.mockResolvedValue(
      page([row(), row({ id: "2", question: "Second?" })]),
    );
    adminApi.approveMarket
      .mockResolvedValueOnce({ success: true, data: { status: "active" } })
      .mockRejectedValueOnce(new Error("nope"));

    const user = await openPendingQueue();

    await user.click(await screen.findByRole("checkbox", { name: /select will bitcoin/i }));
    await user.click(await screen.findByRole("checkbox", { name: /select all/i }));
    await user.click(await screen.findByRole("button", { name: /approve 2/i }));
    await user.click(await screen.findByRole("button", { name: /^approve 2$/i, hidden: false }));

    await waitFor(() =>
      expect(sileo.error).toHaveBeenCalledWith(
        expect.objectContaining({ title: "1 approved, 1 failed" }),
      ),
    );
    expect(sileo.success).not.toHaveBeenCalled();
  });

  it("names the market that did not publish, not just its id", async () => {
    adminApi.markets.mockResolvedValue(
      page([row({ id: "2", question: "The stubborn one?" })]),
    );
    adminApi.approveMarket.mockRejectedValue(new Error("nope"));

    const user = await openPendingQueue();

    await user.click(
      await screen.findByRole("checkbox", { name: /select the stubborn one/i }),
    );
    await user.click(await screen.findByRole("button", { name: /approve 1/i }));
    await user.click(await screen.findByRole("button", { name: /^approve 1$/i, hidden: false }));

    // An operator chasing the failure needs the submission, and "1 of them" does
    // not survive being pasted into a ticket. The id is no use to them either.
    await waitFor(() => {
      const call = sileo.error.mock.calls[0]?.[0] as
        | { description?: string }
        | undefined;
      expect(call?.description).toContain("The stubborn one?");
      expect(call?.description).not.toContain(MARKET_ID);
    });
  });

  it("does not claim success when everything failed", async () => {
    adminApi.markets.mockResolvedValue(
      page([row(), row({ id: "2", question: "Second?" })]),
    );
    adminApi.approveMarket.mockRejectedValue(new Error("nope"));

    const user = await openPendingQueue();

    await user.click(await screen.findByRole("checkbox", { name: /select will bitcoin/i }));
    await user.click(await screen.findByRole("checkbox", { name: /select all/i }));
    await user.click(await screen.findByRole("button", { name: /approve 2/i }));
    await user.click(await screen.findByRole("button", { name: /^approve 2$/i, hidden: false }));

    await waitFor(() =>
      expect(sileo.error).toHaveBeenCalledWith(
        expect.objectContaining({ title: "Nothing was approved" }),
      ),
    );
    expect(sileo.success).not.toHaveBeenCalled();
  });

  it("reports a clean run as a clean run", async () => {
    const user = await openPendingQueue();

    await user.click(await screen.findByRole("checkbox", { name: /select will bitcoin/i }));
    await user.click(await screen.findByRole("button", { name: /approve 1/i }));
    await user.click(await screen.findByRole("button", { name: /^approve 1$/i, hidden: false }));

    await waitFor(() =>
      expect(sileo.success).toHaveBeenCalledWith(
        expect.objectContaining({ title: "1 market approved" }),
      ),
    );
  });

  it("clears the selection afterwards, so nothing is approved twice", async () => {
    const user = await openPendingQueue();

    await user.click(await screen.findByRole("checkbox", { name: /select will bitcoin/i }));
    await user.click(await screen.findByRole("button", { name: /approve 1/i }));
    await user.click(await screen.findByRole("button", { name: /^approve 1$/i, hidden: false }));

    await waitFor(() => expect(screen.queryByText(/selected/)).toBeNull());
  });

  it("approves every selected market, not just the first", async () => {
    adminApi.markets.mockResolvedValue(
      page([row(), row({ id: "2" }), row({ id: "3" })]),
    );
    const user = await openPendingQueue();

    const boxes = await screen.findAllByRole("checkbox", { name: /select will bitcoin/i });
    await user.click(boxes[0]!);
    await user.click(await screen.findByRole("checkbox", { name: /select all/i }));
    await user.click(await screen.findByRole("button", { name: /approve 3/i }));
    await user.click(await screen.findByRole("button", { name: /^approve 3$/i, hidden: false }));

    await waitFor(() => expect(adminApi.approveMarket).toHaveBeenCalledTimes(3));
    expect(adminApi.approveMarket).toHaveBeenNthCalledWith(1, MARKET_ID);
    expect(adminApi.approveMarket).toHaveBeenNthCalledWith(3, "3");
  });
});

describe("the dispute queue's link to a market", () => {
  /**
   * Every dispute row links its market question to `/markets?market=<id>`, and
   * until the page read that parameter the link landed on an unfiltered first
   * page. The operator following it lost the one thing they were looking at.
   */
  it("searches for the market the link names", async () => {
    searchParams.current = new URLSearchParams(`market=${MARKET_ID}`);
    wrap();

    await waitFor(() =>
      expect(adminApi.markets).toHaveBeenCalledWith(
        expect.objectContaining({ q: MARKET_ID }),
      ),
    );
  });

  it("shows the id in the search box, so the list is not mysterious", async () => {
    searchParams.current = new URLSearchParams(`market=${MARKET_ID}`);
    wrap();

    await waitFor(() =>
      expect(
        (screen.getByLabelText(/search/i) as HTMLInputElement).value,
      ).toBe(MARKET_ID),
    );
  });

  it("does not search for a market when no id was given", async () => {
    wrap();

    await waitFor(() => expect(adminApi.markets).toHaveBeenCalled());
    expect(adminApi.markets).toHaveBeenCalledWith(
      expect.objectContaining({ q: undefined }),
    );
  });
});
