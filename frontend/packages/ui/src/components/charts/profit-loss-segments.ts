/**
 * Split a series into contiguous runs of non-negative and negative values so a
 * profit/loss chart can colour each run independently.
 *
 * `profit-loss-line.tsx` consumes this to decide which gradient and stroke each
 * piece of the line gets, and to report `isPositive` for legend dimming.
 *
 * Sign convention: zero counts as positive, matching `segmentLegendIndex` in
 * profit-loss-line (which maps `value >= 0` to legend slot 0).
 */

/** One contiguous run of same-sign points. */
export interface ProfitLossSegment {
  data: Record<string, unknown>[];
  isPositive: boolean;
}

export interface SplitProfitLossSegmentsArgs {
  /** Rendered chart records, in x order. */
  data: readonly Record<string, unknown>[];
  /** Field holding the y value whose sign is being split on. */
  dataKey: string;
  /** Accepted for call-site compatibility; splitting does not need x. */
  xDataKey?: string;
  /** Accepted for call-site compatibility; splitting does not need x. */
  xAccessor?: (d: Record<string, unknown>) => Date;
}

export function splitProfitLossSegments({
  data,
  dataKey,
}: SplitProfitLossSegmentsArgs): ProfitLossSegment[] {
  const segments: ProfitLossSegment[] = [];
  let current: ProfitLossSegment | null = null;

  for (const point of data ?? []) {
    const raw = point?.[dataKey];

    // A non-finite sample is a gap, not a sign change. Ending the run here
    // keeps the two sides from being joined by an implied straight line.
    if (typeof raw !== "number" || !Number.isFinite(raw)) {
      current = null;
      continue;
    }

    const isPositive = raw >= 0;
    if (!current || current.isPositive !== isPositive) {
      current = { data: [], isPositive };
      segments.push(current);
    }
    current.data.push(point);
  }

  // A line path needs two points to be visible, so a lone point is dropped
  // rather than rendered as an invisible one-point stroke.
  return segments.filter((segment) => segment.data.length > 1);
}