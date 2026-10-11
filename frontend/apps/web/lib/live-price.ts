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
  volume?: number;
}

export type LivePricePoint = Record<string, number | string> & { time: number };

/** Minimal shape of the cached market detail we patch. */
export interface MarketPriceCache {
  yes_price?: string;
  no_price?: string;
  outcomes?: MarketOutcomeCache[];
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
 * Minimal shape of one REST price-history sample.
 */
export interface PriceHistorySample {
  timestamp: string;
  outcomes?: { id?: string; name?: string; price?: string | number }[];
}

/**
 * Map REST price-history samples onto chart points.
 *
 * Shared by the market page and the home-page cards so both draw the same curve
 * from the same data. The cards previously seeded two identical points and
 * waited for a WebSocket frame, which renders as a dead straight line whenever
 * nothing trades - a chart that looks broken rather than a flat market.
 *
 * Samples with no usable price are skipped rather than defaulted to 0: a
 * missing price is a gap, and a fabricated zero is a wrong price that also
 * stretches the y-domain.
 */
/**
 * Per-outcome prices, keyed by lower-cased outcome name.
 *
 * Preference order:
 *   1. `outcome.price` from the API - the backend prices every outcome from its
 *      own pool, so this is a real quote and works on first paint.
 *   2. An orderbook midpoint, only for an outcome the API did not price.
 *
 * The old code derived prices from the orderbook alone. On a thin market with no
 * resting orders that yields nothing, every outcome then fell back to the same
 * even split, and an eight-way market rendered as "Yes 75 / No 25" - two
 * numbers that were not any of its outcomes.
 *
 * Extracted from market-detail.tsx so the ordering is testable on its own; the
 * "prefer the API, fall back to the book" rule is the whole point and was
 * invisible when it lived inside a useMemo in a component.
 */
export function buildOutcomePrices(
  outcomes: { name?: string; price?: number | string | null }[] | null | undefined,
  orderbook?: Record<string, { bids?: { price: string | number }[]; asks?: { price: string | number }[] }> | null
): Record<string, number> {
  const map: Record<string, number> = {}

  for (const outcome of outcomes ?? []) {
    // null/undefined means "the API did not price this outcome". It must be
    // skipped explicitly rather than run through Number(), because Number(null)
    // is 0 - and 0 renders as a confident "0%, certain not to happen" for an
    // outcome nobody quoted.
    if (outcome?.name == null || outcome?.price == null) continue
    const price = Number(outcome.price)
    if (Number.isFinite(price)) {
      map[outcome.name.toLowerCase()] = price
    }
  }

  for (const [name, book] of Object.entries(orderbook ?? {})) {
    const key = name.toLowerCase()
    if (map[key] !== undefined) continue

    const bids = (book?.bids ?? [])
      .map((b) => Number(b.price))
      .filter((p) => Number.isFinite(p))
    const asks = (book?.asks ?? [])
      .map((a) => Number(a.price))
      .filter((p) => Number.isFinite(p))

    const bestBid = bids.length ? Math.max(...bids) : NaN
    const bestAsk = asks.length ? Math.min(...asks) : NaN

    if (Number.isFinite(bestBid) && Number.isFinite(bestAsk)) map[key] = (bestBid + bestAsk) / 2
    else if (Number.isFinite(bestAsk)) map[key] = bestAsk
    else if (Number.isFinite(bestBid)) map[key] = bestBid
  }

  return map
}

export function priceHistoryToPoints(
  samples: PriceHistorySample[] | undefined | null
): LivePricePoint[] {
  if (!samples?.length) return [];

  const points: LivePricePoint[] = [];
  for (const sample of samples) {
    const outcomes = sample.outcomes ?? [];
    const value = Number(outcomes[0]?.price);
    if (!Number.isFinite(value)) continue;

    const parsedTime = new Date(sample.timestamp).getTime() / 1000;
    if (!Number.isFinite(parsedTime)) continue;

    const point: LivePricePoint = { time: parsedTime, value };
    for (const outcome of outcomes) {
      const price = Number(outcome?.price);
      if (Number.isFinite(price) && outcome?.name) point[outcome.name] = price;
    }
    points.push(point);
  }
  return points;
}

/** Cached outcome shape, as the market detail query returns it. */
export interface MarketOutcomeCache {
  id?: string;
  name?: string;
  price?: number | string | null;
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

  // Per-outcome prices, for markets with 3+ outcomes.
  //
  // The header, the outcome selector and the order form all read their prices
  // from `buildOutcomePrices(market.outcomes, orderbook)`, which prefers the
  // API price over the book midpoint. `outcomes[].price` is only ever written by
  // the initial REST fetch, so on a multi-outcome market the API price always
  // won - and always won *stale*, freezing every per-outcome price in the UI even
  // though the chart lines beside them were moving. Writing them here is what
  // makes the numbers and the lines agree.
  //
  // Matched case-insensitively: the frame carries the canonical name from the DB
  // ("Yes") while the cached outcome is whatever the API echoed back.
  const outcomePrices = msg.outcome_prices;
  const outcomes = prev.outcomes;
  if (outcomePrices && Array.isArray(outcomes) && outcomes.length > 0) {
    let changed = false;
    const nextOutcomes = outcomes.map((outcome) => {
      const price = outcomePrices[outcome.name ?? ""] ?? outcomePrices[(outcome.name ?? "").toLowerCase()];
      if (!isFiniteNumber(price) || price === outcome.price) return outcome;
      changed = true;
      return { ...outcome, price };
    });
    if (changed) patch.outcomes = nextOutcomes;
  }

  if (Object.keys(patch).length === 0) return prev;

  return { ...prev, ...patch } as T;
}

/** The prices a `market:price_update` frame carries, as received. */
export interface LiveFrame {
  yes_price?: number;
  no_price?: number;
  outcome_prices?: Record<string, number>;
  /**
   * `market:resolved` rides the same aggregated batch as `market:price_update`.
   *
   * A grid that is never told a market settled keeps its subscription slot and
   * keeps painting a live-looking card for a market that can never move again.
   * It rides along because the grid was already receiving this batch - so it
   * costs one field rather than a second channel.
   */
  type?: string;
  status?: string;
  winning_outcome_id?: string;
  winning_outcome_name?: string;
  /**
   * Per-market frame sequence number.
   *
   * Carried through the grid's aggregated batches so a list of live cards keeps
   * the same gap detection a detail page has. Without it a grid cannot tell a
   * missed frame from a quiet market, which is the failure the heartbeat beacon
   * was added to close.
   */
  seq?: number;
  /**
   * The first `seq` this flush window saw for this market.
   *
   * Grid aggregation collapses repeated updates into one frame, so intermediate
   * sequence numbers are deliberately absent. Without this, a grid cannot tell a
   * collapsed update from a lost one - they look identical - and every busy
   * market reports itself as lossy on every tick, firing a full REST resync
   * hundreds of times a second.
   */
  seq_from?: number;
}

/**
 * Overlay a socket frame's prices onto a REST market, for render-from-props
 * consumers (the market cards).
 *
 * A card renders whatever it is handed, so it cannot be patched through the
 * query cache the way `patchMarketPrices` does - and the same market appears in
 * several differently-filtered lists, each with its own cache entry. Overlaying
 * at the card is the one place that reaches all of them.
 *
 * The rules mirror `patchMarketPrices` exactly, because two ways to price the
 * same market is how the numbers and the chart beside them drift apart:
 *
 *  - Only finite numbers are written. `NaN` in a price renders as garbage, and a
 *    missing price is a gap - never a fabricated `0`, which would read as a
 *    confident "certain not to happen".
 *  - An outcome the frame says nothing about keeps its REST price. Frames are
 *    partial by design (a binary frame carries no `outcome_prices` at all), and
 *    omitting an outcome is not saying that outcome is worth nothing.
 *  - Names match exactly first, then case-insensitively, because the frame
 *    carries the DB's canonical casing while the cached outcome is whatever the
 *    API echoed back.
 *  - A market with no `outcomes` array is left alone rather than throwing: a
 *    card may be handed a market shape it does not fully understand, and should
 *    render what it has instead of blanking the grid.
 *
 * Returns the same object reference when nothing changed, so a frame that
 * changes nothing cannot re-render every card on the page.
 */
export function applyLivePrices<
  T extends { yes_price?: unknown; no_price?: unknown; outcomes?: MarketOutcomeCache[] | null }
>(market: T, live?: LiveFrame | null): T {
  if (!live) return market;

  const patch: Record<string, unknown> = {};
  let changed = false;

  if (isFiniteNumber(live.yes_price)) {
    patch.yes_price = live.yes_price;
    changed = true;
  }
  if (isFiniteNumber(live.no_price)) {
    patch.no_price = live.no_price;
    changed = true;
  }

  const outcomes = market.outcomes;
  if (live.outcome_prices && Array.isArray(outcomes) && outcomes.length > 0) {
    let outcomesChanged = false;
    const next = outcomes.map((outcome) => {
      const name = outcome?.name ?? "";
      const price = live.outcome_prices![name] ?? live.outcome_prices![name.toLowerCase()];
      if (!isFiniteNumber(price) || price === outcome.price) return outcome;
      outcomesChanged = true;
      return { ...outcome, price };
    });
    if (outcomesChanged) {
      patch.outcomes = next;
      changed = true;
    }
  }

  return changed ? ({ ...market, ...patch } as T) : market;
}