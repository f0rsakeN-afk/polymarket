/**
 * Two screens that existed as endpoints and as nothing else.
 *
 * `GET /admin/disputes/{id}` and `GET /treasury/logs` were both implemented,
 * tested on the backend, and never called from the admin app. A dispute row
 * carried a truncated evidence snippet and a "Resolve" button, with the
 * resolution criteria — the thing a ruling is actually judged against — visible
 * nowhere. And a treasury balance had no history behind it, so fees accruing
 * from trades were indistinguishable from money that had appeared.
 */
import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

const adminApi = vi.hoisted(() => ({
  dispute: vi.fn(),
  disputes: vi.fn(),
  treasuryLogs: vi.fn(),
  adjudicate: vi.fn(),
}));

vi.mock("@workspace/api-client/admin", () => ({ adminApi }));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn() }),
  usePathname: () => "/disputes",
}));

vi.mock("sileo", () => ({ sileo: { success: vi.fn(), error: vi.fn() } }));

import { DisputeDetailDialog } from "@/components/dispute-detail-dialog";
import { TreasuryHistory } from "@/components/treasury-history";

const disputeRow = {
  id: "d1",
  market_id: "m1",
  market_slug: "epl-2027-champion",
  market_question: "Which team wins the 2026-27 Premier League?",
  market_status: "dispute_window",
  proposed_outcome_id: "o1",
  user_id: "u1",
  proposer_username: "alice",
  evidence: "The final table published two hours ago.",
  evidence_url: "https://example.com/table",
  status: "open",
  created_at: "2026-10-01T00:00:00Z",
};

function detail(overrides: Record<string, unknown> = {}) {
  return {
    ...disputeRow,
    resolution_criteria: "Resolves to the team top of the official final table.",
    resolution_source: "https://premierleague.com/table",
    proposed_outcome_name: "Arsenal",
    ...overrides,
  };
}

function wrap(ui: React.ReactElement) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>);
}

beforeEach(() => {
  vi.clearAllMocks();
  adminApi.dispute.mockResolvedValue({ success: true, data: detail() });
  adminApi.treasuryLogs.mockResolvedValue({ data: [], total: 0, page: 1, page_size: 20, has_more: false });
});

// ── Dispute detail ───────────────────────────────────────────────────────────

describe("reading a dispute before ruling on it", () => {
  it("shows the resolution criteria, which the list never did", async () => {
    wrap(
      <DisputeDetailDialog dispute={disputeRow} onOpenChange={vi.fn()} onRule={vi.fn()} />
    );

    // The list row carried a comment claiming this was shown. It was not, because
    // the detail endpoint was never called - and a ruling is judged against this.
    expect(
      await screen.findByText("Resolves to the team top of the official final table.")
    ).toBeTruthy();
  });

  it("names the outcome being disputed, not an opaque id", async () => {
    wrap(
      <DisputeDetailDialog dispute={disputeRow} onOpenChange={vi.fn()} onRule={vi.fn()} />
    );

    expect(await screen.findByText("Arsenal")).toBeTruthy();
  });

  it("warns that a market with no criteria cannot be judged", async () => {
    adminApi.dispute.mockResolvedValue({ success: true, data: detail({ resolution_criteria: null }) });
    wrap(
      <DisputeDetailDialog dispute={disputeRow} onOpenChange={vi.fn()} onRule={vi.fn()} />
    );

    // The absence is usually *why* the dispute exists. An operator who does not
    // know that will rule on the evidence alone and believe they were careful.
    expect(await screen.findByText(/states no resolution criteria/i)).toBeTruthy();
  });

  it("shows the proposer's evidence in full, whitespace preserved", async () => {
    wrap(
      <DisputeDetailDialog dispute={disputeRow} onOpenChange={vi.fn()} onRule={vi.fn()} />
    );

    // Quoted text reflowed into a single line stops being quotable.
    const evidence = await screen.findByText(/final table published/);
    expect(evidence.className).toContain("whitespace-pre-wrap");
  });

  it("says so when no evidence was given", async () => {
    adminApi.dispute.mockResolvedValue({
      success: true,
      data: detail({ evidence: null, evidence_url: null }),
    });
    wrap(
      <DisputeDetailDialog dispute={disputeRow} onOpenChange={vi.fn()} onRule={vi.fn()} />
    );

    // Its own fact to weigh, not an empty box.
    expect(await screen.findByText(/no evidence was supplied/i)).toBeTruthy();
  });

  it("does not let anyone rule on something they have not read", async () => {
    let release: (v: unknown) => void = () => {};
    adminApi.dispute.mockReturnValue(
      new Promise((resolve) => {
        release = resolve;
      })
    );

    wrap(
      <DisputeDetailDialog dispute={disputeRow} onOpenChange={vi.fn()} onRule={vi.fn()} />
    );

    // Ruling resolves a market and queues settlement. It pays real money, and it
    // is irreversible.
    expect(screen.getByRole("button", { name: /rule on this dispute/i })).toBeDisabled();

    release({ success: true, data: detail() });
    await waitFor(() =>
      expect(screen.getByRole("button", { name: /rule on this dispute/i })).not.toBeDisabled()
    );
  });

  it("does not show an empty panel when the detail fails to load", async () => {
    adminApi.dispute.mockRejectedValue(new Error("boom"));
    wrap(
      <DisputeDetailDialog dispute={disputeRow} onOpenChange={vi.fn()} onRule={vi.fn()} />
    );

    expect(await screen.findByText(/could not load this dispute/i)).toBeTruthy();
  });
});

// ── Treasury history ─────────────────────────────────────────────────────────

describe("treasury movement history", () => {
  it("signs the amounts, because direction is the whole point", async () => {
    adminApi.treasuryLogs.mockResolvedValue({
      data: [
        { id: "1", event: "fee_collected", amount: "962.8861455", reference_type: "trade", reference_id: "t1", created_at: "2026-10-01T00:00:00Z" },
        { id: "2", event: "distribution", amount: "1665.10836805", reference_type: "liquidity", reference_id: null, created_at: "2026-10-02T00:00:00Z" },
      ],
      total: 2,
      page: 1,
      page_size: 20,
      has_more: false,
    });

    wrap(<TreasuryHistory />);

    // A column of positive amounts, half of which is money leaving, is a column
    // that lies about direction.
    expect(await screen.findByText(/^\+962\.8861455$/)).toBeTruthy();
    expect(screen.getByText(/^−1,665\.10836805$/)).toBeTruthy();
  });

  it("labels direction in words as well as in the icon", async () => {
    adminApi.treasuryLogs.mockResolvedValue({
      data: [
        { id: "1", event: "fee_collected", amount: "10", reference_type: null, reference_id: null, created_at: "2026-10-01T00:00:00Z" },
        { id: "2", event: "distribution", amount: "5", reference_type: null, reference_id: null, created_at: "2026-10-02T00:00:00Z" },
      ],
      total: 2,
      page: 1,
      page_size: 20,
      has_more: false,
    });

    wrap(<TreasuryHistory />);

    // The arrow is not an accessible signal.
    expect(await screen.findByText("Fees collected")).toBeTruthy();
    expect(screen.getByText("Distributed")).toBeTruthy();
  });

  it("shows where a balance has no history, rather than a blank panel", async () => {
    wrap(<TreasuryHistory />);

    // A balance with nothing behind it is indistinguishable from one that was
    // invented, which is exactly why this list exists.
    expect(await screen.findByText(/no movements recorded/i)).toBeTruthy();
  });

  it("paginates when there is more than one page", async () => {
    adminApi.treasuryLogs.mockResolvedValue({
      data: [
        { id: "1", event: "fee_collected", amount: "1", reference_type: null, reference_id: null, created_at: "2026-10-01T00:00:00Z" },
      ],
      total: 100,
      page: 1,
      page_size: 20,
      has_more: true,
    });

    wrap(<TreasuryHistory />);

    expect(await screen.findByRole("button", { name: /next/i })).toBeTruthy();
    // Rendered but disabled rather than absent, so the controls do not move when
    // the operator reaches page two.
    expect(screen.getByRole("button", { name: /previous/i })).toBeDisabled();
  });

  it("asks the API for a specific page rather than refetching everything", async () => {
    adminApi.treasuryLogs.mockResolvedValue({
      data: [
        { id: "1", event: "fee_collected", amount: "1", reference_type: null, reference_id: null, created_at: "2026-10-01T00:00:00Z" },
      ],
      total: 100,
      page: 1,
      page_size: 20,
      has_more: true,
    });

    const user = userEvent.setup();
    wrap(<TreasuryHistory />);

    await user.click(await screen.findByRole("button", { name: /next/i }));

    await waitFor(() =>
      expect(adminApi.treasuryLogs).toHaveBeenCalledWith({ page: 2, pageSize: 20 })
    );
  });
});