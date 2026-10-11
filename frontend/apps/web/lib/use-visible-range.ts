"use client"

/**
 * Which markets are actually on screen, as a scrollable window over a long list.
 *
 * Two things were scaling with the length of the catalogue rather than with what
 * the user can see, and both were paid for on every tick:
 *
 *   1. **Subscriptions.** The grid declared every market in the loaded array, so
 *      opening a long list meant the server held a channel for each one and
 *      buffered a price for each one per flush - including the hundreds that
 *      were nowhere near the viewport. That is the expensive part: the server
 *      was doing work for markets nobody was looking at, and the bound grew
 *      without limit.
 *
 *   2. **DOM nodes.** Every card was mounted. Live prices re-render their card,
 *      so a market ticking on page 40 would re-render a node that is scrolled
 *      far out of view.
 *
 * Windowing fixes both from one source of truth: only the visible range is
 * rendered, and only the visible range is declared to the server. Scrollback and
 * scroll-forward keep working because `estimateSize` drives a measured virtual
 * list rather than a fixed-height assumption.
 *
 * Overscan is deliberate. A market must be subscribed *before* it scrolls into
 * view, or it arrives with a static price and only starts moving once something
 * else about it changes - which looks exactly like the realtime layer being
 * broken, on exactly the markets the user scrolled to see.
 */

import { useMemo, useRef } from "react"
import { useVirtualizer } from "@tanstack/react-virtual"

/** Markets rendered beyond the viewport on each side, so scrolling reveals live data. */
const OVERSCAN = 4

export function useVisibleRange<T>(items: T[], estimateSize: (index: number) => number) {
  const scrollRef = useRef<HTMLDivElement | null>(null)
  const virtualizer = useVirtualizer({
    count: items.length,
    getScrollElement: () => scrollRef.current,
    estimateSize,
    overscan: OVERSCAN,
  })

  const range = virtualizer.getVirtualItems()

  // `range` is a fresh array every render, so memoising on its identity would
  // hand the subscription effect a new value on every tick and re-declare the
  // grid each time. Keying on the contents keeps it stable until the *set* of
  // visible rows actually changes - which is the only thing a subscription cares
  // about.
  const visibleKey = range.map((v) => v.index).join(",")

  /** Indices actually rendered - what the grid should be subscribed to. */
  const visibleIndices = useMemo(
    () => visibleKey ? visibleKey.split(",").map(Number) : [],
    [visibleKey]
  )

  return { virtualizer, scrollRef, visibleIndices }
}