"use client"

/**
 * Preferences for how the realtime layer behaves on screen.
 *
 * These are judgement calls, not facts. Whether a 1-point move is worth
 * interrupting someone for, whether the live dot reads as "live" or as
 * decoration, and whether the grid animates at all are opinions about attention -
 * and opinions about attention should be adjustable by whoever has to live with
 * them, not frozen into a constant and re-deployed.
 *
 * They are configurable here for three reasons, in order of importance:
 *
 *   1. **The OS already has an opinion.** `prefers-reduced-motion` is the user
 *      telling the system something about their needs. Honoring it is not a
 *      feature, it is the floor - and then letting them override *that* is what
 *      makes it a preference rather than a setting imposed from above.
 *   2. **The thresholds are unvalidated.** A significance threshold picked by
 *      reasoning rather than by users is a guess. Making it adjustable means the
 *      guess can be corrected without a deploy.
 *   3. **Density is contextual.** Someone scanning a 200-market grid wants less
 *      motion than someone watching a single market.
 *
 * ## The significance rule, and why the shipped one was wrong
 *
 * The original threshold was "1 percentage point". That is simply incorrect,
 * because the card renders `Math.round(price * 100)` - an *integer* percentage.
 *
 *   0.50 -> 0.505   renders 50% -> 51%   visibly changed, but only 0.005
 *   0.995 -> 0.999  renders 100% -> 100% unchanged, and only 0.004
 *
 * So a fixed threshold misses moves the user can plainly see. It does not
 * over-fire here, because the rounding window is exactly as wide as the old
 * threshold - but that is coincidence rather than design, and the rule stays with
 * perceptibility because that is the thing it is actually for. The default asks
 * the only question that
 * matters: **does this change the number on screen?** That is the definition of
 * perceptible, it self-adjusts across the 3-95 cent range where a fixed
 * threshold is most wrong, and it cannot drift out of sync with the formatter
 * the way a magic number can - if the display gains a decimal place, the rule
 * follows it automatically.
 *
 * `absolute` and `relative` remain available because they are right in cases
 * where the display is not the signal - a sparkline, a colour, or a view that
 * renders more precision than the card does.
 */

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
} from "react"

/** How much of the grid animates. */
export type MotionMode =
  /** Never animate. Cheapest, and the right answer for a dense grid. */
  | "off"
  /** Animate only changes the user can actually perceive. The default. */
  | "significant"
  /** Animate every price change, however small. */
  | "all"

/** What counts as perceptible. */
export type SignificanceRule =
  /** Does the rendered value change? Matches the card's integer percentage. */
  | "display"
  /** A fixed number of probability points. */
  | "absolute"
  /** A fraction of the current price, so moves scale with how the market is priced. */
  | "relative"

export interface RealtimePrefs {
  motion: MotionMode
  rule: SignificanceRule
  /** Only used when `rule === "absolute"`. */
  absolute: number
  /** Only used when `rule === "relative"`. */
  relative: number
  /** Show the "streaming" dot on cards fed by the socket. */
  showLiveBadge: boolean
  /** Show the quiet border tint on a card that just moved. */
  showActiveTint: boolean
}

export const DEFAULT_PREFS: RealtimePrefs = {
  motion: "significant",
  rule: "display",
  // Kept for the `absolute` rule. 1pp is the old default, retained because it is
  // a sane starting point for a view that renders more precision than the card.
  absolute: 0.01,
  // 2% is where a move reads as a move rather than as drift.
  relative: 0.02,
  showLiveBadge: true,
  showActiveTint: true,
}

const STORAGE_KEY = "predictx:realtime-prefs"

/** How the card renders a price - the granularity a move must cross to be seen. */
const displayedPercent = (price: number) => Math.round(price * 100)

/**
 * Is this change worth showing?
 *
 * Pure and total on purpose: it takes the two prices and returns one decision,
 * with no state and no thresholds hidden inside, so it can be reasoned about and
 * tested directly rather than inferred from a component's behaviour.
 */
export function isSignificant(
  from: number,
  to: number,
  rule: SignificanceRule = DEFAULT_PREFS.rule,
  { absolute = DEFAULT_PREFS.absolute, relative = DEFAULT_PREFS.relative } = {},
): boolean {
  if (!Number.isFinite(from) || !Number.isFinite(to)) return false
  const delta = Math.abs(to - from)
  if (delta === 0) return false

  switch (rule) {
    case "absolute":
      return delta >= absolute
    case "relative":
      return from !== 0 && delta / Math.abs(from) >= relative
    case "display":
    default:
      // The honest default: a move the user cannot see is not worth a flash.
      return displayedPercent(from) !== displayedPercent(to)
  }
}

/** Does the OS ask for reduced motion? */
export function prefersReducedMotion(): boolean {
  if (typeof window === "undefined" || !window.matchMedia) return false
  return window.matchMedia("(prefers-reduced-motion: reduce)").matches
}

function readStored(): Partial<RealtimePrefs> {
  if (typeof localStorage === "undefined") return {}
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    return raw ? (JSON.parse(raw) as Partial<RealtimePrefs>) : {}
  } catch {
    // Private browsing, disabled storage, corrupt value. A missing preference is
    // a normal state, not an error worth surfacing to someone browsing markets.
    return {}
  }
}

interface RealtimePrefsContext {
  prefs: RealtimePrefs
  /** The user's explicit choice about motion, or `null` to follow the OS. */
  motionOverride: MotionMode | null
  setMotion: (mode: MotionMode | null) => void
  set: <K extends keyof RealtimePrefs>(key: K, value: RealtimePrefs[K]) => void
  reset: () => void
  /** The OS setting, for showing "following your system preference". */
  systemReducedMotion: boolean
}

const Ctx = createContext<RealtimePrefsContext | null>(null)

export function RealtimePrefsProvider({ children }: { children: React.ReactNode }) {
  const [stored, setStored] = useState<Partial<RealtimePrefs>>(() => readStored())
  const [systemReducedMotion, setSystemReducedMotion] = useState(() => prefersReducedMotion())
  const [motionOverride, setMotionOverride] = useState<MotionMode | null>(
    () => stored.motion ?? null,
  )

  // Track the OS setting live. Someone can turn reduced motion on mid-session,
  // and a grid that keeps animating after they asked it to stop has ignored them.
  useEffect(() => {
    if (typeof window === "undefined" || !window.matchMedia) return
    const mql = window.matchMedia("(prefers-reduced-motion: reduce)")
    const onChange = () => setSystemReducedMotion(mql.matches)
    mql.addEventListener("change", onChange)
    return () => mql.removeEventListener("change", onChange)
  }, [])

  const persist = useCallback((next: Partial<RealtimePrefs>) => {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(next))
    } catch {
      // A preference that cannot be saved is still applied for this session.
      // Failing to persist must never break rendering the page.
    }
  }, [])

  const set = useCallback(
    <K extends keyof RealtimePrefs>(key: K, value: RealtimePrefs[K]) => {
      setStored((prev) => {
        const next = { ...prev, [key]: value }
        persist(next)
        return next
      })
    },
    [persist],
  )

  const setMotion = useCallback(
    (mode: MotionMode | null) => {
      setMotionOverride(mode)
      setStored((prev) => {
        const next = { ...prev }
        if (mode === null) delete next.motion
        else next.motion = mode
        persist(next)
        return next
      })
    },
    [persist],
  )

  const reset = useCallback(() => {
    setStored({})
    setMotionOverride(null)
    try {
      localStorage.removeItem(STORAGE_KEY)
    } catch {
      /* see above - a preference that cannot be cleared is still cleared in memory */
    }
  }, [])

  const prefs = useMemo<RealtimePrefs>(() => {
    const merged = { ...DEFAULT_PREFS, ...stored }
    // Motion resolves OS-first unless the user has said otherwise. The override
    // exists because "the OS is right about me in general" and "I want to see
    // these flash anyway" are both legitimate positions, and only the user can
    // tell which applies today.
    if (motionOverride) merged.motion = motionOverride
    else if (systemReducedMotion) merged.motion = "off"
    return merged
  }, [stored, motionOverride, systemReducedMotion])

  const value = useMemo(
    () => ({ prefs, motionOverride, setMotion, set, reset, systemReducedMotion }),
    [prefs, motionOverride, setMotion, set, reset, systemReducedMotion],
  )

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>
}

/**
 * Read the realtime preferences.
 *
 * Works without a provider - returning the defaults - so a card rendered outside
 * the app shell (a test, an isolated story) behaves rather than throwing. Missing
 * a provider should degrade to "the shipped defaults", not to a blank page.
 */
export function useRealtimePrefs(): RealtimePrefsContext {
  const ctx = useContext(Ctx)
  const fallback = useMemo(
    () => ({
      prefs: DEFAULT_PREFS,
      motionOverride: null,
      setMotion: () => {},
      set: () => {},
      reset: () => {},
      systemReducedMotion: false,
    }),
    [],
  )
  return ctx ?? fallback
}