/**
 * Making a live grid legible.
 *
 * A grid of cards receives a new price for every market on every tick. Rendered
 * naively, two very different facts look identical: a market that moved 8 points
 * and one that moved 0.1; a price arriving live off the socket and one frozen in
 * the REST snapshot the page loaded with. Neither is visible, so the realtime
 * layer does work the user cannot perceive - which defeats its purpose.
 *
 * These pin that legibility, and pin that it stays *quiet*. A grid where thirty
 * cards all flash on every tick is worse than one that never moves: it makes the
 * cards that genuinely moved impossible to find.
 */
import { describe, expect, it, vi, beforeEach, afterEach } from "vitest"
import { act, cleanup, renderHook } from "@testing-library/react"
import { tickColor, usePriceTick } from "@/lib/use-price-tick"

beforeEach(() => {
  vi.useFakeTimers()
})
afterEach(() => {
  vi.useRealTimers()
  cleanup()
})

/** Render the hook and push a new price in. */
const step = (initial: number | null) => {
  const seen: Array<ReturnType<typeof usePriceTick>> = []
  const { rerender } = renderHook(({ price }: { price: number | null }) => {
    seen.push(usePriceTick(price))
    return null
  }, { initialProps: { price: initial } })
  return {
    latest: () => seen[seen.length - 1]!,
    set: (price: number | null) => act(() => rerender({ price })),
  }
}

describe("usePriceTick", () => {
  it("does not call the first value a move", () => {
    // Every card would light up on first paint, which says nothing about whether
    // anything has changed.
    const h = step(0.5)
    expect(h.latest().direction).toBe(0)
  })

  it("reports direction for a real move", () => {
    const h = step(0.5)
    h.set(0.58)
    expect(h.latest().direction).toBe(1)

    h.set(0.42)
    expect(h.latest().direction).toBe(-1)
  })

  it("animates a move that changes the number on screen", () => {
    // The case the old fixed 1-point threshold got wrong. The card renders
    // `Math.round(price * 100)`, so 50% -> 51% is plainly visible - and is only
    // half a point of movement. A fixed threshold silently dropped it.
    const h = step(0.5)
    h.set(0.505)
    expect(h.latest().direction).toBe(1)
  })

  it("ignores a move the user cannot see", () => {
    // ...and the converse, which the old threshold got wrong in the other
    // direction: a full point of movement that leaves the rendered number
    // identical is not something anyone could notice.
    const h = step(0.995)
    h.set(0.999)
    expect(h.latest().direction).toBe(0)
  })

  it("ignores a change too small to perceive", () => {
    // A grid of sub-perceptual churn is noise, and it buries the cards that
    // actually moved.
    const h = step(0.5)
    h.set(0.502)
    expect(h.latest().direction).toBe(0)
  })

  it("still tracks the baseline through ignored noise", () => {
    // If a sub-threshold tick did not update the baseline, a long run of small
    // drifts would accumulate into a phantom "move" on the next real tick, and
    // report a direction nobody observed.
    const h = step(0.5)
    // Drift that stays inside one rendered value (all of these read "50%"), so
    // none of it is worth showing.
    h.set(0.501)
    h.set(0.503)
    h.set(0.504)
    expect(h.latest().direction).toBe(0)

    // Then a real move. Up, not "up by however much accumulated" - a direction
    // the user never watched happen is not one they were shown.
    h.set(0.55)
    expect(h.latest().direction).toBe(1)
  })

  it("changes `at` on every real move so an animation can restart", () => {
    // The flash is driven by `key={at}`, which remounts the element. If `at` did
    // not change the highlight would play once and then never again.
    const h = step(0.5)
    h.set(0.6)
    const first = h.latest().at
    h.set(0.7)
    expect(h.latest().at).not.toBe(first)
  })

  it("marks the market active, then lets it settle", () => {
    const h = step(0.5)
    h.set(0.6)
    expect(h.latest().active).toBe(true)

    act(() => {
      vi.advanceTimersByTime(5_000)
    })
    // Settles back rather than staying lit forever. A card stuck in the "moving"
    // // state is worse than one that never highlights at all.
    expect(h.latest().active).toBe(false)
  })

  it("ignores a non-numeric price rather than treating it as a crash", () => {
    const h = step(0.5)
    h.set(Number.NaN)
    expect(h.latest().direction).toBe(0)
    h.set(null)
    expect(h.latest().direction).toBe(0)
  })

  it("recovers after a missing price", () => {
    // A market can arrive with no price yet, then start streaming.
    const h = step(null)
    expect(h.latest().direction).toBe(0)
    h.set(0.5)
    h.set(0.62)
    expect(h.latest().direction).toBe(1)
  })
})

describe("tickColor", () => {
  it("uses the convention for a price, not for a profit", () => {
    // Worth being explicit: this colours a *price*. Whether a move is good news
    // depends on which side you hold, which is why the bar under the number keeps
    // its own outcome colour - the two must never contradict each other.
    expect(tickColor(1)).toMatch(/emerald/)
    expect(tickColor(-1)).toMatch(/rose/)
    expect(tickColor(0)).toBeUndefined()
  })
})