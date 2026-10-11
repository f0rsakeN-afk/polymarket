"use client"

import { useEffect, useRef, memo, useCallback, useState } from "react"
import { useQueryClient } from "@tanstack/react-query"
import { MarketCard } from "./market-card"
import { SkeletonMarketGrid } from "@/components/shared/skeletons"
import { useMarketGrid } from "@/hooks/use-market-socket"
import type { LiveFrame } from "@/lib/live-price"
import { useVisibleRange } from "@/lib/use-visible-range"
import type { MarketResponse } from "@/hooks/api/types/market"

/** Latest socket prices, keyed by market id. */
type LivePrices = Record<string, LiveFrame>

/**
 * How often the grid applies buffered prices.
 *
 * A card shows a number that changes by hundredths; nobody can read one that
 * updates faster than this, and rendering every incoming frame is the single
 * biggest cost a live grid has.
 */
const FLUSH_INTERVAL_MS = 250

/**
 * Markets that will never trade again.
 *
 * Subscribing to one spends a per-connection subscription slot for the life of
 * the page in exchange for frames that never arrive. A list showing settled
 * markets would otherwise spend its entire budget on them.
 */
const DEAD_MARKET_STATUSES = new Set(["resolved", "closed"])

/**
 * Height of a market card, in pixels.
 *
 * Exact, not an estimate, and only because `MarketCard` is built to a fixed
 * shape: every card renders exactly two outcome rows whether it is binary or has
 * fifty outcomes, so one height fits all of them.
 *
 * Pinning it means the virtualizer never has to *measure*. That matters for more
 * than tidiness - measured heights are wrong on first paint, and correcting them
 * shifts rows under the user's cursor mid-scroll. A known height removes that
 * whole class of jump, and lets lanes be laid out without ever overlapping.
 *
 * Sizing it to content rather than to the tallest possible card is what keeps
 * the grid dense: at 300px a binary card was ~40% empty, which reads as broken
 * in a different way. 228 is the natural height of the fixed card shape.
 */
const CARD_HEIGHT_PX = 228

interface MarketListProps {
  markets: MarketResponse[]
  loading: boolean
  hasMore: boolean
  onLoadMore: () => void
}

const MarketList = memo(function MarketList({ markets, loading, hasMore, onLoadMore }: MarketListProps) {
  const sentinelRef = useRef<HTMLDivElement>(null)
  const qc = useQueryClient()
  const [live, setLive] = useState<LivePrices>({})

  // Buffer, then flush once.
  //
  // A grid subscribes to every visible market, so a busy page receives a frame
  // per market per tick. Writing each one straight into state re-renders the
  // entire grid that many times a second - thirty cards re-rendering thirty
  // times is how a realtime page ends up feeling *slower* than a static one, and
  // it burns mobile battery for a price that moved 0.1%.
  //
  // Coalescing keeps only the newest frame per market and flushes on a timer. A
  // price grid does not need 60fps: it is a number, not an animation, and a few
  // updates a second is indistinguishable from live to a human while cutting the
  // render count by an order of magnitude. Per-market coalescing also means a
  // market ticking ten times between flushes is applied once at its final price,
  // rather than ten times through ten intermediate values nobody can read.
  const pendingRef = useRef<LivePrices>({})
  const flushTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const needsResyncRef = useRef(false)
  /**
   * Markets this session has been told are settled.
   *
   * Kept for the life of the page, not cleared on flush: a settled market must
   * stop consuming a subscription slot immediately, and the query has not
   * necessarily refetched yet when that has to take effect. The row's `status`
   * arrives on the server's schedule; this does not wait for it.
   */
  const resolvedRef = useRef<Set<string>>(new Set())
  /** Highest `seq` seen per market • survives the aggregation */
  const seqRef = useRef<Map<string, number>>(new Map())

  const flush = useCallback(() => {
    flushTimerRef.current = null
    if (needsResyncRef.current) {
      needsResyncRef.current = false
      pendingRef.current = {}
      // Baselines go too: the next frame after a resync is a fresh start, and
      // keeping the old high-water mark would make it look like a gap.
      seqRef.current.clear()
      setLive({})
      qc.invalidateQueries({ queryKey: ["markets"] })
      return
    }
    const pending = pendingRef.current
    if (Object.keys(pending).length === 0) return
    pendingRef.current = {}
    setLive((prev) => ({ ...prev, ...pending }))
  }, [qc])

  const schedule = useCallback(() => {
    if (flushTimerRef.current !== null) return
    flushTimerRef.current = setTimeout(flush, FLUSH_INTERVAL_MS)
  }, [flush])

  // Every visible, *tradeable* market, through the one tab-wide socket.
  //
  // Both grids this backs - the home page and /markets - rendered prices frozen
  // at whatever the list query returned, sitting beside a live trending
  // carousel.
  //
  // Resolved and closed markets are excluded: they can never trade again, so a
  // subscription to one is a server-side slot held for the life of the page in
  // exchange for frames that will never arrive. On a list full of settled
  // markets that is the whole subscription budget spent on nothing.
  //
  // Cost tracks what is rendered rather than the size of the catalogue, which is
  // what keeps the server's per-connection subscription cap meaningful.
  //
  // `resolvedRef` covers the window between being told a market settled and the
  // refetch that would tell us so via `status`. Relying on the refetched row
  // alone leaves a slot pinned on a market that can never tick again for as long
  // as the request takes - and on a list that is mostly resolved markets, that
  // is the whole budget spent on markets that are already done.
  // Only what is on screen, plus a small overscan.
  //
  // Declaring every loaded market made the server hold a channel and buffer a
  // price for each one per flush - including the hundreds scrolled out of view.
  // That work was invisible in the UI and grew with the catalogue rather than
  // with the page, which is the wrong axis entirely: a user's screen shows the
  // same twenty markets whether the catalogue holds twenty or twenty thousand.
  //
  // The overscan is load-bearing, not cosmetic. A market subscribed only once it
  // scrolls into view arrives with whatever price the last REST response gave it
  // and stays there until something else moves it - so the first thing a user
  // sees after scrolling is a price that is conspicuously not live, which reads
  // as the realtime layer being broken precisely where they were looking.
  // Window the list. Rendering and subscription both follow the visible range,
  // so a long catalogue costs the same as a short one.
  const { virtualizer, listRef, scrollMarginRef, columns, visibleIndices } = useVisibleRange(
    markets,
    useCallback(() => CARD_HEIGHT_PX, [])
  )

  const marketIds = markets
    .filter((m) => !DEAD_MARKET_STATUSES.has(m.status ?? ""))
    .filter((m) => !resolvedRef.current.has(m.id))
    .filter((_, i) => visibleIndices.includes(i))
    .map((m) => m.id)
  const idsKey = marketIds.join("|")

  // One aggregated frame per flush, already batched server-side. The client no
  // longer subscribes per market and no longer receives one frame per market
  // per tick - it receives one frame carrying whatever changed.
  const handlePrices = useCallback(
    (prices: Record<string, Record<string, unknown>>) => {
      for (const [marketId, frame] of Object.entries(prices)) {
        const msg = frame as LiveFrame

        // A settled market leaves the grid.
        //
        // Without this a market that resolves keeps its subscription slot for the
        // life of the page, keeps painting a live-looking card, and keeps showing
        // prices that can never move again - the list believes it is tradeable
        // right up until someone reloads. The server now rides resolution along
        // on the same batch it was already sending, so this costs one field.
        if (msg.type === "market:resolved") {
          resolvedRef.current.add(marketId)
          // Drop the baseline immediately: those prices are final and must not
          // be re-applied on top of the refreshed row.
          delete pendingRef.current[marketId]
          seqRef.current.delete(marketId)
          setLive((prev) => {
            if (!(marketId in prev)) return prev
            const next = { ...prev }
            delete next[marketId]
            return next
          })
          continue
        }

        // Gap detection survives batching - but only because the server says what it
        // dropped. Aggregation collapses N updates per market into one frame, so
        // the intermediate `seq`s are *deliberately* absent: `seq_from` is the
        // first seq this flush window saw, `seq` the last.
        //
        // Judging contiguity on `seq` alone would read a collapsed update as
        // `4 -> 9` and call it loss, so every busy market would fire a full REST
        // resync on every tick - which is a self-inflicted load problem, not just
        // a wrong number. Comparing `seq_from` against what we last received
        // separates the two: coalescing stays contiguous, genuine transport loss
        // still shows up as a gap.
        const seq = msg.seq
        if (typeof seq === "number") {
          const seqFrom = typeof msg.seq_from === "number" ? msg.seq_from : seq
          const prev = seqRef.current.get(marketId)
          if (prev !== undefined && seqFrom > prev + 1) {
            // Provable loss - repair from REST rather than stitching across a
            // hole, exactly as a detail page does.
            needsResyncRef.current = true
            continue
          }
          seqRef.current.set(marketId, seq)
        }

        pendingRef.current[marketId] = {
          yes_price: msg.yes_price,
          no_price: msg.no_price,
          outcome_prices: msg.outcome_prices,
        }
      }
      // A settlement invalidates the query that produced the rows themselves -
      // status, winner, and whether the card still belongs in this filter. Doing
      // it here rather than on a timer is the difference between the list
      // correcting itself and the list being eventually right.
      if (resolvedRef.current.size > 0) {
        qc.invalidateQueries({ queryKey: ["markets"] })
      }
      schedule()
    },
    [schedule, qc]
  )

  useMarketGrid(marketIds, handlePrices)

  // Tear the flush timer down, or it outlives the component and writes state
  // into an unmounted grid.
  useEffect(
    () => () => {
      if (flushTimerRef.current !== null) clearTimeout(flushTimerRef.current)
    },
    []
  )

  // Forget markets that scrolled out, so the map cannot grow for the life of the
  // session as the user pages through the catalogue.
  useEffect(() => {
    const visible = new Set(idsKey ? idsKey.split("|") : [])
    setLive((prev) => {
      const next: LivePrices = {}
      let changed = false
      for (const [id, value] of Object.entries(prev)) {
        if (visible.has(id)) next[id] = value
        else changed = true
      }
      return changed ? next : prev
    })
    // A market that scrolled away must not keep a baseline: returning to it is
    // "arrived late", not "lost", and a stale baseline would trigger a spurious
    // resync the moment it comes back.
    // A market that scrolled away must not keep a baseline: coming back to it is
    // "arrived late", not "lost", and a stale baseline would trigger a spurious
    // resync the moment it reappears.
    if (idsKey) {
      const visible = new Set(idsKey.split("|"))
      for (const id of [...seqRef.current.keys()]) {
        if (!visible.has(id)) seqRef.current.delete(id)
      }
    } else {
      seqRef.current.clear()
    }
  }, [idsKey])

  const handleIntersect = useCallback((entry: IntersectionObserverEntry) => {
    if (entry?.isIntersecting && hasMore && !loading) {
      onLoadMore()
    }
  }, [hasMore, loading, onLoadMore])

  useEffect(() => {
    const el = sentinelRef.current
    if (!el) return

    const observer = new IntersectionObserver(
      (entries) => {
        if (entries[0]) handleIntersect(entries[0])
      },
      { threshold: 0.1, rootMargin: "400px" }
    )

    observer.observe(el)
    return () => observer.disconnect()
  }, [handleIntersect])

  if (loading && markets.length === 0) {
    return <SkeletonMarketGrid />
  }

  if (!loading && markets.length === 0) {
    return (
      <div className="py-12 text-center text-muted-foreground">
        No markets found
      </div>
    )
  }

  const rows = virtualizer.getVirtualItems()

  return (
    <div className="space-y-4">
      {/*
        Windowed, but still the same responsive grid it always was.

        The column count is the virtualizer's `lanes`, driven by the same
        breakpoints the Tailwind classes used - so cards keep their arrangement
        instead of collapsing to one per row, and the virtualizer reserves the
        right amount of space per row.

        The window is the scroll element rather than a nested `overflow-y-auto`
        panel: the page already scrolled, adding an inner scroller changes how it
        feels and puts a scrollbar inside the content.

        Each row is placed by `translateY` against a spacer of the full scroll
        height, so the document reports the true length of the list while only a
        handful of cards exist inside it. `width`/`left` come from the row's lane,
        which is what turns absolute positioning back into a grid.
      */}
      <div
        ref={listRef}
        data-testid="market-scroll"
        style={{ height: virtualizer.getTotalSize(), position: "relative" }}
      >
        {rows.map((row) => {
          const market = markets[row.index]
          if (!market) return null
          const widthPct = 100 / columns
          return (
            <div
              key={market.id}
              data-index={row.index}
              data-lane={row.lane}
              className="absolute top-0 px-2 pb-4"
              style={{
                left: `${(row.lane ?? 0) * widthPct}%`,
                width: `${widthPct}%`,
                // Fixed height for every cell. Without this the rows go ragged:
                // cards differ in content, so each one would measure differently
                // and a row of cards would end at three different bottoms.
                height: CARD_HEIGHT_PX,
                // `row.start` is document-relative because the window is the
                // scroll element; the list has to subtract its own offset or the
                // whole grid renders below where it belongs.
                transform: `translateY(${row.start - scrollMarginRef.current}px)`,
              }}
            >
              <MarketCard market={market} live={live[market.id]} />
            </div>
          )
        })}
      </div>
      <div ref={sentinelRef} className="flex justify-center py-4">
        {loading && <div className="flex items-center gap-1 text-muted-foreground"><div className="size-3 animate-spin rounded-full border-2 border-muted-foreground border-t-transparent" /> Loading...</div>}
        {!hasMore && markets.length > 0 && (
          <span className="text-xs text-muted-foreground">No more markets</span>
        )}
      </div>
    </div>
  )
})

export { MarketList }
export default MarketList
