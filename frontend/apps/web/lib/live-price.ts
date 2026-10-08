/**
 * Pure helpers for the live `market:price_update` WebSocket frame.
 *
 * Extracted from market-detail's onMessage handler so the "a trade must move the
 * displayed price" rule is unit-testable without standing up React Query, the
 * socket provider and the full market page around it.
 *
 * Two rules live here, and both were bugs:
 *
 *  1. A frame that carries no usable price must produce NO point. Appending a
 *     value-less point makes the line render 0 and dive to the floor.
 *  2. The new price must be pushed into the cached market, as a string. The API
 *     models yes_price/no_price as Decimal -> string, so writing the WS number
 *     straight in would change the cache's shape under every reader.
 */

export interface PriceUpdateMessage {
  yes_price?: number;
  no_price?: number;
  outcome_prices?: Record<string, number>;
}

export type LivePricePoint = Record<string, number | string> & { time: number };

/** Minimal shape of the cached market detail we patch. */
export interface MarketPriceCache {
  yes_price?: string;
  no_price?: string;
  [key: string]: unknown;
}

const isFiniteNumber = (v: unknown): v is number => typeof v === "number" && Number.isFinite(v);

/**
 * Build the chart point for a price frame, or null when the frame carries no
 * usable price and should be dropped.
 */
export function buildLivePricePoint(
  msg: PriceUpdateMessage,
  now: number
): LivePricePoint | null {
  const point: LivePricePoint = { time: now };

  const entries = msg.outcome_prices ? Object.entries(msg.outcome_prices) : [];
  if (entries.length > 0) {
    // `value` drives the primary/animated line: use the first outcome's price.
    const first = entries[0];
    if (first && isFiniteNumber(first[1])) {
      point.value = first[1];
    } else {
      // No usable primary price -> this frame cannot move the chart.
      return null;
    }
    for (const [name, price] of entries) {
      if (isFiniteNumber(price)) point[name] = price;
    }
    return point;
  }

  if (isFiniteNumber(msg.yes_price) && isFiniteNumber(msg.no_price)) {
    // Binary: `value` tracks YES so the animated line stays smooth; the Yes/No
    // keys drive the two separately coloured series.
    point.value = msg.yes_price;
    point.Yes = msg.yes_price;
    point.No = msg.no_price;
    return point;
  }

  // Neither shape: a partial frame. Dropping it is what keeps a "no change"
  // market holding its current price instead of collapsing to zero.
  return null;
}

/**
 * Patch the cached market with the frame's prices.
 *
 * Returns the same object reference when there is nothing to write, so React
 * Query does not treat a no-op frame as new data.
 */
export function patchMarketPrices<T extends MarketPriceCache>(
  prev: T | undefined,
  msg: PriceUpdateMessage
): T | undefined {
  if (!prev) return prev;

  const patch: Partial<MarketPriceCache> = {};
  if (isFiniteNumber(msg.yes_price)) patch.yes_price = String(msg.yes_price);
  if (isFiniteNumber(msg.no_price)) patch.no_price = String(msg.no_price);

  if (Object.keys(patch).length === 0) return prev;

  return { ...prev, ...patch } as T;
}