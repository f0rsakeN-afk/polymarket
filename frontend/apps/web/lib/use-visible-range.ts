"use client"

/**
 * Which markets are actually on screen, as a windowed grid over a long list.
 *
 * Two things were scaling with the length of the catalogue rather than with what
 * the user can see, and both were paid for on every tick:
 *
 *   1. **Subscriptions.** The grid declared every market in the loaded array, so
 *      opening a long list meant the server held a channel for each one and
 *      buffered a price for each one per flush - including the hundreds that
 *      were nowhere near the viewport. That is the expensive part: the server was
 *      doing work for markets nobody was looking at, and the bound grew without
 *      limit.
 *
 *   2. **DOM nodes.** Every card was mounted. Live prices re-render their card,
 *      so a market ticking on page 40 would re-render a node that is scrolled far
 *      out of view.
 *
 * Windowing fixes both from one source of truth: only the visible range is
 * rendered, and only the visible range is declared to the server.
 *
 * ## Two things this must not break
 *
 * **The grid layout is product design, not incidental markup.** The list is a
 * responsive 1 / 2 / 3 column grid. A virtualizer that renders one item per row
 * is technically "working" and visibly broken - so `lanes` is driven by the same
 * breakpoints Tailwind uses, and an earlier version here that dropped `lanes`
 * collapsed the whole grid to a single column.
 *
 * **The page scrolls; the list is not a scroll container.** Introducing a nested
 * `overflow-y-auto` panel changes how the page feels, puts a scrollbar inside the
 * content, and breaks the infinite-scroll sentinel, which sits below the list and
 * measures against the viewport. So the window is the scroll element.
 */

import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react"
import { useVirtualizer } from "@tanstack/react-virtual"

/**
 * Columns per breakpoint.
 *
 * Must match the Tailwind classes the grid used before it was virtualised:
 * one column, two from `sm` (640px), three from `lg` (1024px).
 */
const COLUMN_BREAKPOINTS: Array<[query: string, columns: number]> = [
  ["(min-width: 1024px)", 3],
  ["(min-width: 640px)", 2],
]

/** Rows rendered beyond the viewport, so scrolling reveals already-live data. */
const OVERSCAN_ROWS = 2

/**
 * Subscribe to the responsive column count.
 *
 * `lanes` has to equal the real column count or the virtualizer reserves space
 * for columns that do not exist - which leaves gaps, or overlaps cards on top of
 * each other. Resizing the window therefore has to re-lane the list, not just
 * re-render it.
 */
function useResponsiveColumns(): number {
  const [columns, setColumns] = useState(1)

  useEffect(() => {
    const mqls = COLUMN_BREAKPOINTS.map(
      ([query, n]) => [window.matchMedia(query), n] as const,
    )
    const update = () => {
      for (const [mql, n] of mqls) {
        if (mql.matches) {
          setColumns(n)
          return
        }
      }
      setColumns(1)
    }
    update()
    for (const [mql] of mqls) mql.addEventListener("change", update)
    return () => {
      for (const [mql] of mqls) mql.removeEventListener("change", update)
    }
  }, [])

  return columns
}

export function useVisibleRange<T>(items: T[], estimateSize: (index: number) => number) {
  const columns = useResponsiveColumns()
  const listRef = useRef<HTMLDivElement | null>(null)
  /**
   * Distance from the top of the document to the top of the list.
   *
   * With the window as the scroll element, `row.start` is measured from the top
   * of the *document*, not from the top of the list. Without subtracting this the
   * whole grid is offset downward by however far down the page the list starts -
   * so it renders below where it should and the scroll height does not line up
   * with what is on screen.
   */
  const scrollMarginRef = useRef(0)
  const [scrollMargin, setScrollMargin] = useState(0)

  /** Re-measure the list's offset from the top of the document. */
  const measureScrollMargin = useCallback(() => {
    const el = listRef.current
    if (!el) return
    const next = el.getBoundingClientRect().top + window.scrollY
    if (Math.abs(next - scrollMarginRef.current) > 0.5) {
      scrollMarginRef.current = next
      setScrollMargin(next)
    }
  }, [])

  const virtualizer = useVirtualizer({
    count: items.length,
    // The window scrolls; the list is not a scroll container.
    getScrollElement: () =>
      typeof document !== "undefined" ? document.documentElement : null,
    estimateSize,
    lanes: columns,
    // Lanes are rows, so overscan has to scale with the column count or a
    // three-column grid renders only one extra row and reveals blank space when
    // scrolling down.
    overscan: OVERSCAN_ROWS,
    scrollMargin,
  })

  useLayoutEffect(() => {
    measureScrollMargin()
  }, [measureScrollMargin, items.length, columns])

  // The offset changes with anything above the list - header, filters, a resize.
  // Missing that leaves the windowed grid offset from where the document thinks
  // it starts, which shows up as blank space while scrolling.
  useEffect(() => {
    const onResize = () => {
      measureScrollMargin()
      virtualizer.measure()
    }
    window.addEventListener("resize", onResize)
    window.addEventListener("scroll", onResize, { passive: true })
    return () => {
      window.removeEventListener("resize", onResize)
      window.removeEventListener("scroll", onResize)
    }
  }, [measureScrollMargin, virtualizer])

  const range = virtualizer.getVirtualItems()

  // `range` is a fresh array every render, so memoising on its identity would hand
  // the subscription effect a new value on every tick and re-declare the grid each
  // time. Keying on the contents keeps it stable until the *set* of visible rows
  // actually changes - which is the only thing a subscription cares about.
  const visibleKey = range.map((v) => v.index).join(",")

  /** Indices actually rendered - what the grid should be subscribed to. */
  const visibleIndices = useMemo(
    () => (visibleKey ? visibleKey.split(",").map(Number) : []),
    [visibleKey],
  )

  return { virtualizer, listRef, scrollMarginRef, columns, visibleIndices }
}