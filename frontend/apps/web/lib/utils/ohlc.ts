/**
 * Candle building for the market chart.
 *
 * ## Where the four prices come from
 *
 * The price history endpoint buckets the per-minute snapshots the worker
 * writes and returns one price per outcome per bucket, plus the open, high,
 * low and close of that bucket. The range is computed server-side because it
 * is the only place the individual snapshots still exist — the client is handed
 * one row per bucket and cannot recover the high and low from it.
 *
 * ## Why this is not built client-side
 *
 * Bucketing the samples again on the client produced a body with no range: one
 * sample per bucket means open, high, low and close are all the same number,
 * so every candle was a flat doji and every one of them was drawn as a rise.
 * A chart where every candle is green says nothing about direction, which is
 * the one thing a candle chart exists to say.
 */

export interface OHLCPoint {
  /** Unix seconds at the start of the bucket. */
  time: number
  open: number
  high: number
  low: number
  close: number
  /** Total volume traded in the bucket, for the tooltip. */
  volume?: number
}

/**
 * Candle widths.
 *
 * These are the intervals the price history endpoint understands, so asking
 * for a different one here would mean the server bucketing at a different
 * rate than the candles are drawn at.
 */
export const INTERVAL_OPTIONS = [
  { value: 60, label: "1m" },
  { value: 300, label: "5m" },
  { value: 900, label: "15m" },
  { value: 3600, label: "1h" },
  { value: 14400, label: "4h" },
  { value: 86400, label: "1d" },
] as const

/**
 * The interval the price history endpoint buckets at, for a given candle
 * width. They are the same set of values, so this is a lookup rather than a
 * conversion — but it is a lookup, because the two have to agree and a
 * conversion would be a place for them to drift.
 */
export function intervalToQueryParam(seconds: number): string {
  const match = INTERVAL_OPTIONS.find((o) => o.value === seconds)
  return match ? match.label : "5m"
}

/**
 * Build candles from a price history response.
 *
 * `points` is the API's shape. Each entry is one bucket, already carrying
 * the four prices for its outcome.
 *
 * A bucket the server could not give a full range for — an outcome with no
 * snapshot in it, carried forward from the last one that had — is drawn flat
 * rather than being dropped: the price was real, it just did not move.
 */
export function buildCandles(
  points: {
    timestamp: string
    outcomes: {
      id: string
      name: string
      price: string
      open?: string
      high?: string
      low?: string
      close?: string
    }[]
    total_volume: string
  }[],
  outcomeId?: string
): OHLCPoint[] {
  if (!points || points.length === 0) return []

  const candles: OHLCPoint[] = []

  for (const p of points) {
    // The named outcome, or the first one the server returned. The server
    // sorts outcomes by name, so "the first" is a stable choice rather than
    // an arbitrary one.
    const outcome =
      (outcomeId ? p.outcomes.find((o) => o.id === outcomeId) : undefined) ??
      p.outcomes[0]
    if (!outcome) continue

    const close = Number(outcome.close ?? outcome.price)
    if (!Number.isFinite(close)) continue

    const open = Number(outcome.open ?? close)
    const high = Number(outcome.high ?? close)
    const low = Number(outcome.low ?? close)

    const time = Math.floor(new Date(p.timestamp).getTime() / 1000)
    if (!Number.isFinite(time)) continue

    candles.push({
      time,
      // A range the server did not provide is the close itself, not zero: a
      // zero would draw a candle from the floor of the chart, which is a
      // rendering artefact rather than a price anybody quoted.
      open: Number.isFinite(open) ? open : close,
      // The close has to sit inside the range, or the body would be drawn
      // outside its own wick.
      high: Number.isFinite(high) ? Math.max(high, open, close) : Math.max(open, close),
      low: Number.isFinite(low) ? Math.min(low, open, close) : Math.min(open, close),
      close,
      volume: Number(p.total_volume) || 0,
    })
  }

  return candles.sort((a, b) => a.time - b.time)
}

/** Human-readable interval label, e.g. 300 → "5m". */
export function getIntervalLabel(seconds: number): string {
  if (seconds >= 86400) return `${Math.floor(seconds / 86400)}d`
  if (seconds >= 3600) return `${Math.floor(seconds / 3600)}h`
  if (seconds >= 60) return `${Math.floor(seconds / 60)}m`
  return `${seconds}s`
}

/**
 * A price as the market quotes it: cents.
 *
 * A prediction market's price is a probability, so 0.65 is "65¢". Showing
 * the raw fraction on an axis makes the reader do the conversion, and shows
 * it differently from every other price on the page.
 */
export function formatCents(value: number): string {
  if (!Number.isFinite(value)) return "—"
  return `${Math.round(value * 100)}¢`
}
