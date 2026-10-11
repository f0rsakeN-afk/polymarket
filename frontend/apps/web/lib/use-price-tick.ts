"use client"

/**
 * Turning a price stream into something a person can read.
 *
 * A grid of live cards receives a new price for every market on every tick, and
 * the naive rendering of that - same number, same colour, same weight - makes two
 * very different facts look identical:
 *
 *   - a market that moved 8 points, and one that moved 0.1
 *   - a price arriving live off the socket, and one still frozen from the REST
 *     snapshot the page loaded with
 *
 * Neither is visible, so the realtime layer does no work the user can perceive.
 * That is the whole point of the work, so this makes it legible - without
 * turning the page into a slot machine.
 *
 * Three ideas, all deliberately restrained:
 *
 * **Only real moves are moves.** Sub-perceptual changes are dropped rather than
 * rendered. A grid of thirty cards all flashing is not information; it is noise
 * that makes the cards that genuinely moved impossible to find.
 *
 * **The flash is a remount, not a timer.** Changing the element's `key` restarts
 * a CSS animation, so the highlight plays once and then the element reverts. No
 * JS timer, no state to keep in sync, and it cannot leave a card stuck lit.
 *
 * **Motion is suppressed for reduced-motion users.** The flash is exactly the
 * kind of repeated peripheral animation that triggers vestibular symptoms, and it
 * fires continuously on a live grid.
 */

import { useEffect, useRef, useState } from "react"

/**
 * Smallest price change worth showing, in probability points.
 *
 * Below this, movement is not perceivable on a number a user is scanning rather
 * than reading, so rendering it costs attention and buys nothing.
 */
export const SIGNIFICANT_MOVE = 0.01

/** How long a card stays flagged as having just moved. */
const ACTIVE_WINDOW_MS = 4_000

export type PriceTick = {
  /** `1` up, `-1` down, `0` no significant move yet. */
  direction: 0 | 1 | -1
  /**
   * Changes on every significant move, so it can drive an animation `key`.
   *
   * A monotonic counter, not a timestamp. Two moves inside the same millisecond
   * would share a timestamp, the element's `key` would not change, and the
   * highlight would silently fail to replay - which is the one job this value
   * has. It only has to be unique and ordered, so a counter is both cheaper and
   * more reliable than a clock.
   */
  at: number
  /** True while the market moved within `ACTIVE_WINDOW_MS`. */
  active: boolean
}

/**
 * Track the direction of the last *significant* price change.
 *
 * State is adjusted during render rather than in an effect on purpose: the
 * comparison has to happen when the new price arrives, and an effect would
 * render the card once with the old value and again with the new one - a
 * flash of a stale price on every tick, for every card.
 */
export function usePriceTick(price: number | null | undefined): PriceTick {
  const [tick, setTick] = useState<PriceTick>({ direction: 0, at: 0, active: false })
  // Compared against, so this hook can be called once per card with any price.
  const seen = useRef<number | null>(null)
  const seq = useRef(0)

  if (typeof price === "number" && Number.isFinite(price)) {
    const prev = seen.current
    if (prev === null) {
      // First value: baseline only. Treating it as a move would light up every
      // card on first paint, which says nothing about anything having changed.
      seen.current = price
    } else if (Math.abs(price - prev) >= SIGNIFICANT_MOVE) {
      seen.current = price
      seq.current += 1
      setTick({ direction: price > prev ? 1 : -1, at: seq.current, active: true })
    }
  }

  useEffect(() => {
    if (!tick.active) return
    const timer = setTimeout(
      () => setTick((t) => (t.active ? { ...t, active: false } : t)),
      ACTIVE_WINDOW_MS,
    )
    return () => clearTimeout(timer)
  }, [tick.active, tick.at])

  return tick
}

/**
 * Colour for a price change.
 *
 * Green up, red down - the convention for a *price*, not a P&L, and worth being
 * explicit about: a rising YES price is good news for YES and bad news for NO,
 * and the bar under the number is coloured by outcome, not by direction, so the
 * two never contradict each other.
 */
export function tickColor(direction: 0 | 1 | -1): string | undefined {
  if (direction === 1) return "text-emerald-600 dark:text-emerald-400"
  if (direction === -1) return "text-rose-600 dark:text-rose-400"
  return undefined
}