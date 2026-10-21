/**
 * Submitting a market, and following up on it.
 *
 * These exist because the feature was invisible, not because it was broken. The
 * backend endpoint had been there the whole time; a complete form had been
 * sitting in the repo with no route pointing at it. A passing test suite said
 * nothing about that, which is the part worth guarding: the assertions below are
 * mostly about *existence and wiring*, not about logic.
 *
 * The bugs they specifically pin, each of which was real:
 *
 * - `asChild` on a Base UI `Button` is silently ignored, so the market link
 *   rendered as a bare button that navigated nowhere.
 * - an untouched optional number submitted `NaN` and failed the API's `ge=0.01`,
 *   so every user who skipped the field got an error on it;
 * - the slug regex in the form was looser than the API's, so the form accepted
 *   `---foo---` and the submission then failed;
 * - offering "Add Outcome" built markets the API rejects outright, since
 *   `outcome_index` is capped at 1.
 */
import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

const createMarket = vi.hoisted(() => vi.fn());
const listMyMarkets = vi.hoisted(() => vi.fn());

vi.mock("@/lib/api/markets", () => ({ createMarket, listMyMarkets }));
vi.mock("@/hooks/use-auth", () => ({
  useCurrentUser: () => ({ data: { id: "u1", email: "a@b.c" }, isLoading: false }),
}));
vi.mock("sileo", () => ({ sileo: { success: vi.fn(), error: vi.fn() } }));

const push = vi.hoisted(() => vi.fn());
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push }),
  useSearchParams: () => new URLSearchParams(),
}));

import { CreateMarketForm, slugify } from "@/components/markets/create-market-form";
import MyMarketsClient from "@/app/(app)/markets/mine/MyMarketsClient";

function renderWithQuery(ui: React.ReactElement) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>);
}

const pending = {
  id: "m1",
  slug: "will-it-rain",
  question: "Will it rain in Lisbon on 1 July?",
  description: null,
  category: "Weather",
  subcategory: null,
  image_url: null,
  resolution_criteria: "Resolves Yes if it rains.",
  resolution_source: null,
  status: "pending_review",
  total_liquidity: "0",
  total_volume: "0",
  yes_price: "0.5",
  no_price: "0.5",
  closes_at: "2027-07-01T12:00:00Z",
  winning_outcome_id: null,
  winning_outcome_name: null,
  outcomes: null,
  rejection_reason: null,
  rejected_at: null,
};

const declined = {
  ...pending,
  id: "m2",
  slug: "no-clear-answer",
  question: "Will something vague happen?",
  status: "rejected",
  rejection_reason: "The resolution criteria name no date, so it can never settle.",
  rejected_at: "2026-03-04T10:00:00Z",
};

beforeEach(() => {
  vi.clearAllMocks();
  createMarket.mockResolvedValue({ success: true, data: { slug: "will-it-rain", id: "m1" } });
  listMyMarkets.mockResolvedValue({
    data: [pending, declined],
    total: 2,
    page: 1,
    page_size: 20,
    has_more: false,
  });
});

afterEach(() => vi.restoreAllMocks());

// ── The slug is derived, and the derived value is one the API accepts ─────────

describe("slug derivation", () => {
  it("produces something the server's own pattern accepts", () => {
    // The server requires ^[a-z0-9]+(?:-[a-z0-9]+)*$. The old form validated
    // against ^[a-z0-9-]+$, which permits leading, trailing and doubled hyphens —
    // so the form happily produced slugs the API then rejected with a 422.
    const questions = [
      "Will it rain in Lisbon on 1 July?",
      "Café culture — will it survive?",
      "  spaced  out  words  ",
      "What about (parens) & symbols?!",
      "Who will win?",
    ];
    for (const q of questions) {
      expect(slugify(q)).toMatch(/^[a-z0-9]+(?:-[a-z0-9]+)*$/);
    }
  });

  it("yields nothing rather than a placeholder when there is nothing to derive", () => {
    // Input with no usable characters has no honest slug. Emitting "untitled" or
    // a bare "-" would pass the regex and produce a real URL nobody chose, which
    // is worse than leaving the field for the user to fill.
    expect(slugify("!!! ???")).toBe("");
    expect(slugify("")).toBe("");
  });

  it("does not end in a hyphen", () => {
    // The 255-character slice can land mid-word and leave a trailing separator.
    const long = "a".repeat(300);
    expect(slugify(long)).not.toMatch(/-$/);
    expect(slugify(long).length).toBeLessThanOrEqual(255);
  });
});

// ── The form submits what the API accepts ────────────────────────────────────

describe("proposing a market", () => {
  it("fills the slug from the question", async () => {
    const user = userEvent.setup();
    renderWithQuery(<CreateMarketForm />);

    await user.type(screen.getByLabelText(/question/i), "Will it rain tomorrow?");

    expect(screen.getByLabelText(/^url\s*\*?$/i)).toHaveValue("will-it-rain-tomorrow");
  });

  it("sends the optional number fields as absent when left blank", async () => {
    // The bug: `valueAsNumber` on an untouched input yields NaN, which fails the
    // API's `ge=0.01` — so skipping an *optional* field produced an error on it.
    const user = userEvent.setup();
    renderWithQuery(<CreateMarketForm />);

    await user.type(screen.getByLabelText(/question/i), "Will it rain tomorrow?");
    await user.type(screen.getByLabelText(/closes at/i), "2027-07-01T12:00");
    await user.click(screen.getByRole("button", { name: /submit for review/i }));

    await waitFor(() => expect(createMarket).toHaveBeenCalled());
    const body = (createMarket.mock.calls[0]?.[0] ?? {}) as Record<string, unknown>;
    expect(body.initial_probability).toBeUndefined();
    expect(body.initial_liquidity).toBe(0);
  });

  it("sends the resolution criteria it collected", async () => {
    const user = userEvent.setup();
    renderWithQuery(<CreateMarketForm />);

    await user.type(screen.getByLabelText(/question/i), "Will it rain tomorrow?");
    await user.type(screen.getByLabelText(/closes at/i), "2027-07-01T12:00");
    await user.type(
      screen.getByLabelText(/how does this resolve/i),
      "Resolves Yes if the official forecast says rain."
    );
    await user.click(screen.getByRole("button", { name: /submit for review/i }));

    await waitFor(() => expect(createMarket).toHaveBeenCalled());
    expect((createMarket.mock.calls[0]?.[0] as Record<string, unknown>).resolution_criteria).toBe(
      "Resolves Yes if the official forecast says rain."
    );
  });

  it("defaults to Yes / No", async () => {
    const user = userEvent.setup();
    renderWithQuery(<CreateMarketForm />);

    await user.type(screen.getByLabelText(/question/i), "Will it rain tomorrow?");
    await user.type(screen.getByLabelText(/closes at/i), "2027-07-01T12:00");
    await user.click(screen.getByRole("button", { name: /submit for review/i }));

    await waitFor(() => expect(createMarket).toHaveBeenCalled());
    expect((createMarket.mock.calls[0]?.[0] as Record<string, unknown>).outcomes_create).toEqual([
      { name: "Yes", outcome_index: 0 },
      { name: "No", outcome_index: 1 },
    ]);
  });

  it("can build a market with more than two outcomes", async () => {
    // It could not before. `outcome_index` was capped at 1 in the request schema
    // while the rest of the system had been written for N, so "Add outcome"
    // produced markets the API rejected - a control that looked broken rather
    // than one that was unavailable.
    const user = userEvent.setup();
    renderWithQuery(<CreateMarketForm />);

    await user.type(screen.getByLabelText(/question/i), "Who wins the league?");
    await user.type(screen.getByLabelText(/closes at/i), "2027-07-01T12:00");
    await user.click(screen.getByRole("radio", { name: /named outcomes/i }));

    await user.clear(screen.getByLabelText(/^outcome 1$/i));
    await user.type(screen.getByLabelText(/^outcome 1$/i), "Manchester City");
    await user.clear(screen.getByLabelText(/^outcome 2$/i));
    await user.type(screen.getByLabelText(/^outcome 2$/i), "Arsenal");
    await user.click(screen.getByRole("button", { name: /add outcome/i }));
    await user.type(screen.getByLabelText(/^outcome 3$/i), "Liverpool");

    await user.click(screen.getByRole("button", { name: /submit for review/i }));

    await waitFor(() => expect(createMarket).toHaveBeenCalled());
    // Indices are positional and rebuilt on submit, so removing from the middle
    // cannot leave a gap the server rejects.
    expect((createMarket.mock.calls[0]?.[0] as Record<string, unknown>).outcomes_create).toEqual([
      { name: "Manchester City", outcome_index: 0 },
      { name: "Arsenal", outcome_index: 1 },
      { name: "Liverpool", outcome_index: 2 },
    ]);
  });

  it("refuses two outcomes that share a name", async () => {
    // Parimutuel pricing would happily divide the pool between two legs that
    // cannot be told apart, and nobody would notice until settlement.
    const user = userEvent.setup();
    renderWithQuery(<CreateMarketForm />);

    await user.type(screen.getByLabelText(/question/i), "Who wins?");
    await user.click(screen.getByRole("radio", { name: /named outcomes/i }));
    await user.clear(screen.getByLabelText(/^outcome 1$/i));
    await user.type(screen.getByLabelText(/^outcome 1$/i), "Arsenal");
    await user.clear(screen.getByLabelText(/^outcome 2$/i));
    await user.type(screen.getByLabelText(/^outcome 2$/i), "arsenal");

    expect((await screen.findAllByText(/cannot share a name/i)).length).toBeGreaterThan(0);
  });

  it("will not remove the last two outcomes", async () => {
    const user = userEvent.setup();
    renderWithQuery(<CreateMarketForm />);

    await user.click(screen.getByRole("radio", { name: /named outcomes/i }));

    expect(screen.getByRole("button", { name: /remove outcome 1/i })).toBeDisabled();
    expect(screen.getByRole("button", { name: /remove outcome 2/i })).toBeDisabled();
  });

  it("sends the user to their markets afterwards, not to the catalogue", async () => {
    // The create form used to reset and stay put, which looks like a failure even
    // on success — the market is not live yet, so nothing visibly changed.
    const user = userEvent.setup();
    renderWithQuery(<CreateMarketForm />);

    await user.type(screen.getByLabelText(/question/i), "Will it rain tomorrow?");
    await user.type(screen.getByLabelText(/closes at/i), "2027-07-01T12:00");
    await user.click(screen.getByRole("button", { name: /submit for review/i }));

    await waitFor(() => expect(push).toHaveBeenCalled());
    expect(push.mock.calls[0]?.[0]).toContain("/markets/mine");
  });
});

// ── Following up on a submission ─────────────────────────────────────────────

describe("my markets", () => {
  it("lists every submission, including the unpublished ones", async () => {
    renderWithQuery(<MyMarketsClient />);

    // The public catalogue hides pending_review and rejected from everyone,
    // including their own author. Showing them here is the whole point.
    expect(await screen.findByText(pending.question)).toBeTruthy();
    expect(screen.getByText(declined.question)).toBeTruthy();
  });

  it("shows the decline reason in full, not behind a hover", async () => {
    renderWithQuery(<MyMarketsClient />);

    // The author has nowhere else to look, so a truncated reason is a reason
    // they never read.
    expect(await screen.findByText(declined.rejection_reason)).toBeTruthy();
  });

  it("distinguishes the states instead of showing one badge for everything", async () => {
    renderWithQuery(<MyMarketsClient />);

    expect(await screen.findByText("In review")).toBeTruthy();
    expect(screen.getByText(/why it was declined/i)).toBeTruthy();
  });

  it("does not offer a link to a market that cannot be traded", async () => {
    renderWithQuery(<MyMarketsClient />);

    // A "View market" link onto a page that says not found is precisely the dead
    // end this page exists to remove.
    await screen.findByText(pending.question);
    expect(screen.queryByRole("link", { name: /view market/i })).toBeNull();
  });

  it("offers an empty state that explains what to do, not a blank list", async () => {
    listMyMarkets.mockResolvedValue({
      data: [],
      total: 0,
      page: 1,
      page_size: 20,
      has_more: false,
    });
    renderWithQuery(<MyMarketsClient />);

    expect(await screen.findByText(/have not proposed a market yet/i)).toBeTruthy();
    expect(screen.getByRole("link", { name: /propose your first market/i })).toBeTruthy();
  });

  it("asks for no page controls when everything fits on one", async () => {
    // A permanently disabled "Previous" teaches people the control does nothing.
    renderWithQuery(<MyMarketsClient />);

    await screen.findByText(pending.question);
    expect(screen.queryByRole("button", { name: /^previous$/i })).toBeNull();
  });
});