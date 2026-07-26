import type { OHLCDataPoint } from "@workspace/ui/components/charts/candlestick-chart"
import type { LiveLinePoint } from "@workspace/ui/components/charts/live-line-chart"

/**
 * Convert a stream of price points into OHLC candles grouped by `intervalSeconds`.
 * Used to feed the candlestick chart from live price updates.
 */
export function priceToOHLC(
  history: LiveLinePoint[],
  intervalSeconds = 60
): OHLCDataPoint[] {
  if (history.length === 0) return []

  const buckets = new Map<number, number[]>()

  for (const pt of history) {
    const bucket = Math.floor(pt.time / intervalSeconds) * intervalSeconds
    if (!buckets.has(bucket)) buckets.set(bucket, [])
    buckets.get(bucket)!.push(pt.value)
  }

  const candles: OHLCDataPoint[] = []
  const sorted = [...buckets.entries()].sort(([a], [b]) => a - b)

  for (const [timeMs, values] of sorted) {
    const open = values[0]!
    const close = values[values.length - 1]!
    const high = Math.max(...values)
    const low = Math.min(...values)
    candles.push({ date: new Date(timeMs * 1000), open, high, low, close })
  }

  return candles
}

/**
 * Add a new price point to existing OHLC candles, creating/updating the current bucket.
 */
export function addPriceToOHLC(
  candles: OHLCDataPoint[],
  price: number,
  timestampSeconds: number,
  intervalSeconds = 60
): OHLCDataPoint[] {
  const bucket = Math.floor(timestampSeconds / intervalSeconds) * intervalSeconds
  const last = candles[candles.length - 1]
  const bucketMs = bucket * 1000

  if (last && last.date.getTime() === bucketMs) {
    // Update existing candle
    return [
      ...candles.slice(0, -1),
      {
        ...last,
        high: Math.max(last.high, price),
        low: Math.min(last.low, price),
        close: price,
      },
    ]
  }

  // New candle
  return [
    ...candles,
    { date: new Date(bucketMs), open: price, high: price, low: price, close: price },
  ]
}
