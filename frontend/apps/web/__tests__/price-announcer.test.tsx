/**
 * Live price announcements to a screen reader.
 *
 * The interesting failures here are all about *volume*. A market produces frames
 * many times a second; speech cannot keep up; and a live region interrupts rather
 * than queues. So the assertions are mostly about what did NOT get announced -
 * because a version that announced every tick would pass a naive "does it announce
 * price changes?" test while being unusable in exactly the way this feature exists
 * to avoid.
 */
import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import { act, render, screen } from "@testing-library/react";

import {
  EMPTY_STATE,
  flushAnnouncements,
  formatPriceChange,
  stagePriceChange,
  PriceAnnouncerProvider,
  usePriceAnnouncer,
} from "@/lib/price-announcer";

/** Every frame moves at least a whole rendered percentage point, so nothing is filtered as drift. */
const alwaysSignificant = () => true;

function frame(over: Partial<Parameters<typeof stagePriceChange>[1]> = {}) {
  return { marketId: "m1", outcome: "Yes", from: 0.5, to: 0.5, at: 0, ...over };
}

describe("price announcements • coalescing", () => {
  it("says nothing when nothing moved", () => {
    const staged = stagePriceChange(EMPTY_STATE, frame({ from: 0.5, to: 0.5 }));
    expect(flushAnnouncements(staged, { rule: alwaysSignificant }).messages).toEqual([]);
  });

  it("announces one move", () => {
    const staged = stagePriceChange(EMPTY_STATE, frame({ from: 0.5, to: 0.62 }));
    const { messages } = flushAnnouncements(staged, { rule: alwaysSignificant });
    expect(messages).toEqual(["Yes 62%, up from 50%"]);
  });

  it("collapses a burst into ONE announcement about the total move", () => {
    // Ten frames ten times a second is an ordinary busy market. Announcing each
    // one would leave the user being interrupted continuously by trivia they
    // cannot decline - strictly worse than no announcements.
    let state = EMPTY_STATE;
    for (let i = 1; i <= 10; i++) {
      state = stagePriceChange(state, frame({ from: 0.5 + i * 0.003, to: 0.53, at: i * 100 }));
    }

    const { messages } = flushAnnouncements(state, { rule: alwaysSignificant });

    expect(messages).toHaveLength(1);
    expect(messages[0]).toContain("53%");
  });

  it("reports the move from what was last SPOKEN, not from the previous tick", () => {
    // Otherwise a burst reads as a stutter of one-point moves that contradicts
    // what the user was just told.
    let state = stagePriceChange(EMPTY_STATE, frame({ from: 0.5, to: 0.53, at: 0 }));
    state = flushAnnouncements(state, { rule: alwaysSignificant }).state;

    state = stagePriceChange(state, frame({ from: 0.6, to: 0.68, at: 2000 }));

    const { messages } = flushAnnouncements(state, { rule: alwaysSignificant });
    expect(messages[0]).toBe("Yes 68%, up from 53%");
  });

  it("judges significance across the whole burst, not tick to tick", () => {
    // Ten 0.05-point ticks are individually invisible. Together they are a
    // half-point move, which crosses the displayed-percentage boundary and is a
    // real move. Tick-to-tick judging would stay silent about it.
    let state = EMPTY_STATE;
    for (let i = 1; i <= 10; i++) {
      state = stagePriceChange(state, frame({ from: 0.6 + i * 0.0005, to: 0.605, at: i }));
    }

    // The default rule is "does the displayed number change".
    const { messages } = flushAnnouncements(state);
    expect(messages).toHaveLength(1);
    expect(messages[0]).toContain("61%");
  });

  it("stays silent about a drift that never becomes a move", () => {
    let state = EMPTY_STATE;
    for (let i = 1; i <= 10; i++) {
      state = stagePriceChange(state, frame({ from: 0.6 + i * 0.0001, to: 0.601, at: i }));
    }

    expect(flushAnnouncements(state).messages).toEqual([]);
  });

  it("keeps two markets apart", () => {
    let state = stagePriceChange(EMPTY_STATE, frame({ marketId: "a", outcome: "Yes", from: 0.5, to: 0.6 }));
    state = stagePriceChange(state, frame({ marketId: "b", outcome: "No", from: 0.5, to: 0.4 }));

    const { messages } = flushAnnouncements(state, { rule: alwaysSignificant });
    expect(messages).toHaveLength(2);
  });
});

describe("price announcements • wording", () => {
  it("carries direction in words, not colour or an arrow", () => {
    // A colour is precisely what a screen reader cannot see.
    expect(formatPriceChange(frame({ from: 0.61, to: 0.62 }))).toBe("Yes 62%, up from 61%");
    expect(formatPriceChange(frame({ from: 0.62, to: 0.61 }))).toBe("Yes 61%, down from 62%");
  });

  it("names the outcome on a parimutuel market", () => {
    expect(formatPriceChange(frame({ outcome: "Team A", from: 0.3, to: 0.44 }))).toBe(
      "Team A 44%, up from 30%"
    );
  });
});

describe("price announcements • the live region", () => {
  function Harness() {
    const { announce } = usePriceAnnouncer();
    return <button onClick={() => announce(frame({ from: 0.5, to: 0.62 }))}>move</button>;
  }

  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("is off unless the user turned it on", async () => {
    render(
      <PriceAnnouncerProvider enabled={false} intervalMs={1000} significant={alwaysSignificant}>
        <Harness />
      </PriceAnnouncerProvider>
    );

    await act(async () => {
      screen.getByRole("button").click();
    });
    await act(async () => {
      vi.advanceTimersByTime(2000);
    });

    expect(screen.getByTestId("price-announcer").textContent).toBe("");
  });

  it("speaks a significant move once enabled", async () => {
    render(
      <PriceAnnouncerProvider enabled intervalMs={1000} significant={alwaysSignificant}>
        <Harness />
      </PriceAnnouncerProvider>
    );

    await act(async () => {
      screen.getByRole("button").click();
    });
    // Trailing edge: nothing is said until the window closes.
    await act(async () => {
      vi.advanceTimersByTime(1000);
    });
    // The provider clears, then writes on a follow-up tick; both need advancing.
    await act(async () => {
      vi.advanceTimersByTime(100);
    });

    expect(screen.getByTestId("price-announcer").textContent).toContain("Yes 62%");
  });

  it("clears before setting, or a repeated identical move is silent", async () => {
    // A live region only announces a *change*. Re-setting the same text produces
    // nothing, so a second move that renders identically would be lost - and
    // "Yes 62%, up from 61%" twice is exactly what a user would hear.
    render(
      <PriceAnnouncerProvider enabled intervalMs={1000} significant={alwaysSignificant}>
        <Harness />
      </PriceAnnouncerProvider>
    );

    await act(async () => {
      screen.getByRole("button").click();
    });
    await act(async () => {
      vi.advanceTimersByTime(1000);
    });
    await act(async () => {
      vi.advanceTimersByTime(100);
    });
    expect(screen.getByTestId("price-announcer").textContent).toContain("Yes 62%");

    await act(async () => {
      screen.getByRole("button").click();
    });
    await act(async () => {
      vi.advanceTimersByTime(1000);
    });
    await act(async () => {
      vi.advanceTimersByTime(100);
    });

    // Announced again, and the clear is observable - which is what makes the
    // second announcement happen at all.
    expect(screen.getByTestId("price-announcer").textContent).toContain("Yes 62%");
  });

  it("renders exactly one live region for the whole app", async () => {
    // Only one region is reliably announced; a region per price on a 200-card
    // grid makes the screen reader arbitrate and announce nothing useful.
    render(
      <PriceAnnouncerProvider enabled intervalMs={1000}>
        <div>
          <Harness />
          <Harness />
        </div>
      </PriceAnnouncerProvider>
    );

    expect(screen.getAllByRole("status")).toHaveLength(1);
  });
});