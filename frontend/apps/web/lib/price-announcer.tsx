"use client"

/**
 * Announcing live prices to a screen reader.
 *
 * A prediction market is a number that changes. For a sighted user the flash and
 * the colour change on a card say "this moved"; for a screen-reader user, right
 * now, **nothing happens at all** - the number updates silently and the realtime
 * layer, which is the entire product, is invisible.
 *
 * ## Why this is not just `<div aria-live>{price}</div>`
 *
 * The naive version is worse than no version, and the reason is worth stating
 * because it is not obvious.
 *
 * A busy market produces a price frame many times a second. Speech cannot keep
 * up with that, and a live region does not queue politely - it interrupts. Speak
 * every tick and the user spends their time being interrupted by trivia they
 * cannot decline, which is the opposite of access. Meanwhile **only one live
 * region is reliably announced**; put `aria-live` on every card in a 200-market
 * grid and the screen reader arbitrates between them and announces nothing
 * useful. So this is one global region, fed by a store, rather than a region per
 * price.
 *
 * ## The rule: one announcement per market per window, about the total move
 *
 * Coalescing is not "drop the intermediate ticks". Two details matter:
 *
 *  - Significance is judged from the **last announced** price to the **newest**
 *    price, not tick to tick. Ten 0.3-point ticks are announced as one 3-point
 *    move; ten 0.05-point ticks are not announced at all. Tick-to-tick judging
 *    would announce the first and report the rest as drift, and would stay silent
 *    about a drift that has become a move.
 *  - The "from" in the message is the last **announced** price. Reading it from
 *    the previous tick produces a stutter of one-point moves that does not match
 *    anything the user was told a moment ago.
 *
 * ## Why it is opt-in
 *
 * Default off. Speaking is more intrusive than a flash - it cannot be looked
 * past, and it queues - and someone scanning a grid of thirty markets does not
 * want thirty markets read at them. A preference nobody asked for is an
 * interruption; this has to be chosen.
 */

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react"

import { isSignificant, useRealtimePrefs } from "./realtime-prefs"

// ─── The change ───────────────────────────────────────────────────────────────

export interface PriceChange {
  /** Identity of the market, so two markets never coalesce into one message. */
  marketId: string
  /** What to call it in the message. "Yes", "No", or an outcome's own name. */
  outcome: string
  /** Last announced price, 0-1. */
  from: number
  /** Newest price, 0-1. */
  to: number
  /** Epoch ms the frame arrived. */
  at: number
}

// ─── State ────────────────────────────────────────────────────────────────────

export interface AnnouncerState {
  /** market id → the price last spoken aloud. */
  announced: Record<string, number>
  /** market id → the newest change not yet spoken. */
  pending: Record<string, PriceChange>
}

export const EMPTY_STATE: AnnouncerState = { announced: {}, pending: {} }

/**
 * Fold a frame into the state, keeping only the newest change per market.
 *
 * Pure, so the coalescing can be tested directly rather than inferred from what a
 * component happens to render.
 */
export function stagePriceChange(state: AnnouncerState, change: PriceChange): AnnouncerState {
  const existing = state.pending[change.marketId]
  // The announcer owns the baseline, not the caller.
  //
  // `from` is anchored to the price last *spoken*, falling back to what the caller
  // supplied only for a market that has never been announced. Taking the
  // caller's word for it instead - which is what this did first - means two
  // independent baselines drift apart, and the message ends up describing a move
  // from a price the user was never told. Worse, the caller's baseline advances
  // per frame while this one advances per announcement, so a burst reports the
  // wrong origin.
  const from = existing?.from ?? state.announced[change.marketId] ?? change.from
  return {
    announced: state.announced,
    pending: { ...state.pending, [change.marketId]: { ...change, from } },
  }
}

export interface FlushOptions {
  /** Judged with the same rule the visual flash uses. */
  rule?: (from: number, to: number) => boolean
}

export interface FlushResult {
  state: AnnouncerState
  /** One message per market that crossed the threshold. Empty is common. */
  messages: string[]
}

/**
 * Decide what to say, and advance the "last announced" baseline.
 *
 * Everything below the threshold is *not* announced but its baseline is still
 * advanced, so a market that drifts slowly for an hour is judged on the total
 * move rather than on each invisible step.
 */
export function flushAnnouncements(
  state: AnnouncerState,
  { rule }: FlushOptions = {}
): FlushResult {
  const significant = rule ?? ((from: number, to: number) => isSignificant(from, to))

  const messages: string[] = []
  const announced = { ...state.announced }
  const pending: Record<string, PriceChange> = {}

  for (const [marketId, change] of Object.entries(state.pending)) {
    // A zero delta is never announced, whatever the rule says. `isSignificant`
    // already rejects it, but relying on that alone makes the announcer's
    // correctness depend on every caller supplying a rule that does - and the
    // consequence of getting it wrong is the screen reader repeating a price that
    // did not change.
    if (change.from === change.to) continue
    if (!significant(change.from, change.to)) continue
    messages.push(formatPriceChange(change))
    announced[marketId] = change.to
  }

  return { state: { announced, pending }, messages }
}

// ─── Wording ──────────────────────────────────────────────────────────────────

/**
 * "Yes 62%, up from 61%".
 *
 * The direction is carried by the words rather than by an arrow or a colour,
 * because a colour is exactly the thing a screen reader cannot see and the arrow
 * is exactly the thing it cannot describe.
 */
export function formatPriceChange(change: PriceChange): string {
  const from = Math.round(change.from * 100)
  const to = Math.round(change.to * 100)
  if (from === to) return `${change.outcome} ${to}%`
  const direction = to > from ? "up from" : "down from"
  return `${change.outcome} ${to}%, ${direction} ${from}%`
}

// ─── React ────────────────────────────────────────────────────────────────────

export interface PriceAnnouncerApi {
  /** Announce a market's newest price. No-ops unless the user opted in. */
  announce: (change: PriceChange) => void
  /** True while a region is mounted and announcements are enabled. */
  enabled: boolean
}

const Ctx = createContext<PriceAnnouncerApi | null>(null)

export interface PriceAnnouncerProviderProps {
  children: React.ReactNode
  /** Override for tests; defaults to the shortest interval that is still a throttle. */
  intervalMs?: number
  /** Override for tests. */
  enabled?: boolean
  /** Override for tests, so significance can be exercised without a grid. */
  significant?: (from: number, to: number) => boolean
}

export function PriceAnnouncerProvider({
  children,
  intervalMs,
  enabled,
  significant,
}: PriceAnnouncerProviderProps) {
  const { prefs } = useRealtimePrefs()

  const isEnabled = enabled ?? prefs.announcePrices
  const every = intervalMs ?? prefs.announceIntervalMs

  // Stable across renders. Built inline this is a new function every render, so
  // `announce` changes every render, so the context value changes every render -
  // and every consumer re-renders on every frame of anything else that moves.
  // That is a real cost on a page whose whole purpose is updating continuously.
  const isSignificantMove = useMemo(
    () => significant ?? ((from: number, to: number) => isSignificant(from, to)),
    [significant]
  )

  const [message, setMessage] = useState("")
  const stateRef = useRef<AnnouncerState>(EMPTY_STATE)
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  const announce = useCallback(
    (change: PriceChange) => {
      if (!isEnabled) return
      stateRef.current = stagePriceChange(stateRef.current, change)

      // Trailing edge, not leading: a leading flush would speak the first tick
      // and then have nothing new to say for the rest of the window, which is the
      // opposite of coalescing.
      if (timerRef.current) return
      timerRef.current = setTimeout(() => {
        timerRef.current = null
        const { state, messages } = flushAnnouncements(stateRef.current, {
          rule: isSignificantMove,
        })
        stateRef.current = state
        if (messages.length === 0) return
        // Clearing first is required: a live region only announces a *change*, so
        // re-setting identical text is silent and the second move would be lost.
        setMessage("")
        // ...and the new value lands on the next tick, or React coalesces the two
        // writes into one and the clear is what gets announced.
        setTimeout(() => setMessage(messages.join(". ")), 50)
      }, every)
    },
    [isEnabled, every, isSignificantMove]
  )

  useEffect(() => {
    return () => {
      if (timerRef.current) clearTimeout(timerRef.current)
    }
  }, [])

  const api = useMemo(() => ({ announce, enabled: isEnabled }), [announce, isEnabled])

  return (
    <Ctx.Provider value={api}>
      {children}
      {/* Exactly one region for the whole app. */}
      <div aria-live="polite" aria-atomic="true" role="status" className="sr-only" data-testid="price-announcer">
        {message}
      </div>
    </Ctx.Provider>
  )
}

/** Works without a provider, so a component rendered in isolation still runs. */
export function usePriceAnnouncer(): PriceAnnouncerApi {
  const ctx = useContext(Ctx)
  const fallback = useMemo(() => ({ announce: () => {}, enabled: false }), [])
  return ctx ?? fallback
}