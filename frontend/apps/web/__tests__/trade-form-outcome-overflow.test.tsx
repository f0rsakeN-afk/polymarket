/**
 * Long outcome names must not overflow the trade form.
 *
 * The bug: `OutcomeButton` rendered its label with no width constraint, inside
 * a `grid-cols-3`. A grid item defaults to `min-width: auto`, so one long name
 * set the track's minimum width and pushed the whole row past the card - worst
 * on an eight-way market at 360px, where "Golden State Warriors" gets ~90px of
 * track.
 *
 * Tailwind classes are not resolved to computed styles under jsdom, so these
 * assert the class contract - `min-w-0` on the button and the grid, a wrapping
 * rather than truncating label, and a responsive column count. That is the
 * durable part: the utilities that actually stop the overflow.
 */
import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import type { Outcome } from "@/hooks/api/types/market";

// Correct module paths: useCurrentUser lives in use-auth, the wallet hook in
// api/use-wallet.
// Authenticated: with no user the form renders a "Sign in to start trading"
// gate and no outcome buttons at all, which is what the first version of this
// test accidentally asserted against.
vi.mock("@/hooks/use-auth", () => ({
  useCurrentUser: () => ({
    data: { id: "u1", email: "demo@predictx.io", username: "demo", is_admin: false },
  }),
}));

vi.mock("@/hooks/api/use-wallet", () => ({
  useWallet: () => ({ data: { balance: "50000", available_balance: "50000" } }),
}));

vi.mock("@/lib/api/orders", () => ({
  getQuote: vi.fn().mockResolvedValue({ success: true, data: null }),
}));

import { TradeForm } from "@/components/markets/trade-form";

const EURO = [
  "France",
  "England",
  "Germany",
  "Spain",
  "Portugal",
  "Italy",
  "Netherlands",
  "Other",
];

const NBA = [
  "Boston Celtics",
  "Los Angeles Lakers",
  "Denver Nuggets",
  "Golden State Warriors",
  "Miami Heat",
  "Other",
];

function outcomes(names: string[]): Outcome[] {
  return names.map((name, i) => ({
    id: `o${i}`,
    name,
    outcome_index: i,
    price: 0.2,
  }));
}

function renderForm(names: string[]) {
  return render(
    <TradeForm
      // `marketId` only. An earlier version of this test also passed
      // `slug="multi"`, which `TradeFormProps` never declared - the component
      // resolves everything from `marketId`, so the prop was inert. It type-checked
      // as an excess-property error and broke `tsc --noEmit` for the whole app.
      marketId="m1"
      currentYesPrice={0.5}
      currentNoPrice={0.5}
      outcomePrices={Object.fromEntries(names.map((n) => [n.toLowerCase(), 0.2]))}
      outcomes={outcomes(names)}
      marketStatus="active"
      onSubmit={vi.fn()}
    />
  );
}

describe("trade form outcome buttons", () => {
  it("renders a button per outcome", () => {
    renderForm(EURO);
    for (const name of EURO) {
      expect(screen.getByText(name)).toBeTruthy();
    }
  });

  it("handles the longest realistic names without a clipping class", () => {
    renderForm(NBA);
    const label = screen.getByText("Golden State Warriors");
    const cls = label.className;

    // Wrapping, not truncation: this is a selector, and an outcome the user
    // cannot read is one they cannot pick. `truncate` / `line-clamp-1` here
    // would hide the outcome.
    expect(cls).not.toContain("truncate");
    expect(cls).not.toMatch(/line-clamp-1\b/);
    expect(cls).toContain("break-words");
    // Capped at two lines so one long name cannot stretch the row tall.
    expect(cls).toContain("line-clamp-2");
  });

  it("gives every outcome button min-w-0 so the grid track can shrink", () => {
    // The actual overflow cause: `min-width: auto` on a grid item means its
    // content sets a floor on the track width.
    renderForm(NBA);
    const label = screen.getByText("Los Angeles Lakers");
    const button = label.closest("button")!;
    expect(button.className).toContain("min-w-0");
  });

  it("lays the buttons out in a wrapping flex column inside each button", () => {
    renderForm(NBA);
    const button = screen.getByText("Los Angeles Lakers").closest("button")!;
    // flex-col keeps the name and price stacked even once the name wraps to
    // two lines, instead of the price drifting onto the same line.
    expect(button.className).toContain("flex-col");
  });

  it("drops to two columns on a phone and three when there is room", () => {
    renderForm(NBA);
    const grid = screen.getByText("Boston Celtics").closest("div.grid")!;
    const cls = grid.className;
    expect(cls).toContain("grid-cols-2");
    expect(cls).toContain("sm:grid-cols-3");
    // A bare `grid-cols-3` with no responsive prefix is the original bug.
    expect(cls).not.toMatch(/(^|\s)grid-cols-3(\s|$)/);
  });

  it("puts the full name in the title, since the label can be capped", () => {
    renderForm(NBA);
    const button = screen.getByText("Golden State Warriors").closest("button")!;
    expect(button.getAttribute("title")).toBe("Golden State Warriors");
  });

  it("keeps each outcome selectable", async () => {
    const { default: userEvent } = await import("@testing-library/user-event");
    const user = userEvent.setup();
    renderForm(EURO);

    const spain = screen.getByText("Spain").closest("button")!;
    expect(spain.getAttribute("aria-pressed")).toBe("false");
    await user.click(spain);
    expect(spain.getAttribute("aria-pressed")).toBe("true");
  });

  it("marks the selected outcome with aria-pressed, not colour alone", () => {
    renderForm(EURO);
    // Colour is not the only signal: an outcome cannot be identified by hue,
    // and the palette is now eight distinct colours rather than two states.
    const buttons = EURO.map((n) => screen.getByText(n).closest("button")!);
    for (const b of buttons) {
      expect(b.getAttribute("aria-pressed")).not.toBeNull();
    }
  });

  it("still shows YES/NO for a binary market", () => {
    renderForm(["Yes", "No"]);
    expect(screen.getByText("YES")).toBeTruthy();
    expect(screen.getByText("NO")).toBeTruthy();
  });
});