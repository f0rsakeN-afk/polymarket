/**
 * Preferences, and the judgement call they encode.
 *
 * The significance threshold that ships as a constant is a guess about how much
 * movement is worth interrupting someone for. These pin the *rule* rather than
 * the guess, so the guess can be changed - by a user, or by us - without the
 * behaviour quietly becoming wrong.
 *
 * The important case is the one the original constant got wrong in both
 * directions, and it only became visible by asking what the user can actually
 * see rather than what the number did.
 */
import { describe, expect, it } from "vitest"
import { DEFAULT_PREFS, isSignificant } from "@/lib/realtime-prefs"

/** What the card puts on screen for a price. */
const shown = (p: number) => `${Math.round(p * 100)}%`

describe("isSignificant", () => {
  it("asks whether the rendered number changed", () => {
    // The definition of perceptible. It self-adjusts across the 3-95 cent range,
    // where a fixed threshold is most wrong: 1 point means wildly different
    // things at those prices, and the card's formatter is the thing that
    // decides whether it is visible at all.
    expect(shown(0.5)).toBe("50%")
    expect(isSignificant(0.5, 0.505)).toBe(true) // 50% -> 51%
    expect(isSignificant(0.995, 0.999)).toBe(false) // 100% -> 100%
  })

  it("catches a visible move a fixed threshold missed", () => {
    // The bug. Half a point of movement, plainly visible on screen, and below
    // the 1-point constant that shipped with the first version - so the number
    // changed in front of the user with no indication that it had.
    expect(Math.abs(0.505 - 0.5)).toBeLessThan(DEFAULT_PREFS.absolute)
    expect(isSignificant(0.5, 0.505)).toBe(true)
  })

  it("does not fire on a move the user cannot see", () => {
    // 0.995 -> 0.999 is 0.4 points of movement and renders as 100% both times.
    // Under the old constant this *did* fire, so a price that had not visibly
    // changed still flashed - which trains people to ignore the flash.
    expect(Math.abs(0.999 - 0.995)).toBeLessThan(DEFAULT_PREFS.absolute)
    expect(shown(0.995)).toBe(shown(0.999))
    expect(isSignificant(0.995, 0.999)).toBe(false)
  })

  it("treats a low-priced market's move as significant", () => {
    // 3c -> 4c is a third of the price. A relative rule gets this for free; a
    // fixed one has to be told to.
    expect(isSignificant(0.03, 0.04, "relative", { relative: 0.02 })).toBe(true)
    // 0.03 -> 0.0302 is 0.67% relative: below the bar, so nothing to report.
    expect(isSignificant(0.03, 0.0302, "relative", { relative: 0.02 })).toBe(false)
  })

  it("treats a high-priced market's move by the same relative yardstick", () => {
    expect(isSignificant(0.5, 0.55, "relative", { relative: 0.02 })).toBe(true)
    expect(isSignificant(0.5, 0.505, "relative", { relative: 0.02 })).toBe(false)
  })

  it("supports a fixed threshold for views that render more precision", () => {
    // The card is not the only surface - a detail page or a sparkline can show
    // finer detail, and there "did the visible number change" is the wrong
    // question because the visible number is not an integer percentage.
    expect(isSignificant(0.5, 0.52, "absolute", { absolute: 0.01 })).toBe(true)
    expect(isSignificant(0.5, 0.505, "absolute", { absolute: 0.01 })).toBe(false)
  })

  it("never treats a non-move as one", () => {
    expect(isSignificant(0.5, 0.5)).toBe(false)
    expect(isSignificant(0.5, Number.NaN)).toBe(false)
    expect(isSignificant(Number.NaN, 0.5)).toBe(false)
    expect(isSignificant(0.5, Number.POSITIVE_INFINITY)).toBe(false)
  })

  it("treats equivalent moves the same in either direction", () => {
    // A fall is as much a move as a rise - direction is carried separately for
    // colour, and deciding whether to *show* it must not depend on which way it
    // went, or a falling market would go silent and look broken.
    expect(isSignificant(0.5, 0.52)).toBe(isSignificant(0.5, 0.48))
  })

  it("does not fire when the displayed value is unchanged in either direction", () => {
    // 0.500 and 0.495 both render "50%", so nothing on screen moved. This is not
    // an asymmetry to be smoothed over - it is the rule working: perceptibility
    // is bucketed, and these two prices genuinely share a bucket.
    expect(shown(0.5)).toBe(shown(0.495))
    expect(isSignificant(0.5, 0.495)).toBe(false)
  })
})

describe("defaults", () => {
  it("follows the OS rather than assuming animation is wanted", () => {
    // Not "off" by default - motion is informative - but the OS preference
    // overrides it, and that is asserted by the resolver, not by this constant.
    expect(DEFAULT_PREFS.motion).toBe("significant")
  })

  it("uses perceptibility rather than a magic number", () => {
    expect(DEFAULT_PREFS.rule).toBe("display")
  })

  it("keeps the live badge and the active tint on", () => {
    // These are the parts that make the realtime layer perceptible at all;
    // defaulting them off would ship the feature invisible.
    expect(DEFAULT_PREFS.showLiveBadge).toBe(true)
    expect(DEFAULT_PREFS.showActiveTint).toBe(true)
  })
})