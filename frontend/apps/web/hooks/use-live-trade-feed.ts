/**
 * A live trade feed on top of a REST page.
 *
 * `/trades` and the home page's "Global Activity" both render the platform-wide
 * tape, and both need the same three things to be correct:
 *
 *  1. WS frames are prepended, newest first, without duplicating a trade the
 *     REST page already returned.
 *  2. A frame arriving *while* the REST request is in flight is not rendered
 *     twice when the response lands. `seenIds` guards arrival order only; the
 *     merge has to dedupe, because that is the only place both sources are
 *     visible at once.
 *  3. A reconnect re-reads the page. The feed carries no sequence numbers - it
 *     is a firehose reconciled by trade id - so trades that happened during an
 *     outage are unrecoverable from the socket, and without a refetch the tape
 *     reconnects cleanly and is quietly missing a window.
 *
 * Extracted so both surfaces run the same tested logic rather than two copies
 * that drift.
 */
import { useCallback, useRef, useState } from "react"
import { useGlobalTradesSocket } from "@/hooks/use-global-trades-socket"
import { toTrade, type GlobalTradeFrame } from "@/lib/global-trade-frame"
import type { Trade } from "@/hooks/api/types/market"

/** Synthetic frame: the socket reconnected and the tape may have holes. */
const RESYNC = "__ws_resync__"

export function useLiveTradeFeed(
  restTrades: Trade[] | undefined,
  refetch: () => unknown,
  max: number
) {
  const [wsTrades, setWsTrades] = useState<Trade[]>([])
  const [pendingCount, setPendingCount] = useState(0)
  /** Ids already rendered, so a REST refetch cannot produce a duplicate row. */
  const seenIdsRef = useRef<Set<string>>(new Set())

  const handleMessage = useCallback(
    (msg: unknown) => {
      const frame = msg as GlobalTradeFrame

      if (frame.type === RESYNC) {
        // Anything the socket missed is gone for good; REST is the only complete
        // picture. Clearing the dedupe set alongside is deliberate - the rows
        // about to arrive are the same trades, and a stale set would suppress
        // them.
        setWsTrades([])
        setPendingCount(0)
        seenIdsRef.current.clear()
        void refetch()
        return
      }

      if (frame.type !== "trade:new") return

      const trade = toTrade(frame)
      if (!trade) return
      if (seenIdsRef.current.has(trade.id)) return
      seenIdsRef.current.add(trade.id)

      setWsTrades((prev) => {
        if (prev.some((t) => t.id === trade.id)) return prev
        // Full: the row still belongs in the feed, it just waits behind the
        // "N new trades" button rather than pushing everything else out of view.
        if (prev.length >= max) {
          setPendingCount((c) => c + 1)
          return prev
        }
        return [trade, ...prev]
      })
    },
    [refetch, max]
  )

  const { status } = useGlobalTradesSocket({ onMessage: handleMessage })

  const scrollToTop = useCallback(() => {
    setWsTrades([])
    setPendingCount(0)
  }, [])

  return { wsTrades, pendingCount, status, scrollToTop }
}