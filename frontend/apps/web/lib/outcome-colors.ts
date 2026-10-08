/**
 * Colours for multi-outcome (parimutuel) series.
 *
 * One palette, shared by the market page chart and the home-page card, so an
 * outcome keeps the same colour everywhere. A card that showed France in blue
 * while its chart showed her in green would make the two impossible to read
 * together.
 *
 * Why a dedicated palette rather than `--chart-1..5`: those are five lightnesses
 * of a single green (hue 149-153°), which suits a two-series chart but not an
 * eight-way one - at a 2px stroke, L=0.85 and L=0.95 are the same line. These
 * eight are separated by hue, so any two adjacent entries read as different.
 *
 * `--chart-*` is left alone deliberately: the binary convention is green YES,
 * red NO, and retuning those would change every existing chart.
 */

/** Ordered so the leading outcome gets the most distinguishable colour. */
export const OUTCOME_CHART_COLORS = [
  "var(--outcome-1)", // blue
  "var(--outcome-2)", // amber
  "var(--outcome-3)", // violet
  "var(--outcome-4)", // teal
  "var(--outcome-5)", // rose
  "var(--outcome-6)", // orange
  "var(--outcome-7)", // green
  "var(--outcome-8)", // fuchsia
] as const;

/**
 * How many series to actually draw.
 *
 * Eight lines on a ~600px-wide chart are unreadable whatever the colours, so the
 * chart shows the leaders and the header lists the rest with their prices. This
 * is a legibility limit, not a data limit - `outcomeCount` below is what the UI
 * should report as the market's real breadth.
 */
export const MAX_PLOTTED_OUTCOMES = 4;

/**
 * Colour for the outcome at `index`.
 *
 * Cycles past the end of the palette rather than returning undefined, which is
 * what `var(--chart-6)` used to do: those variables were never defined, so a
 * market with more outcomes than the palette had silently rendered lines in no
 * colour at all.
 */
export function outcomeColor(index: number): string {
  if (!Number.isFinite(index) || index < 0) return OUTCOME_CHART_COLORS[0];
  return OUTCOME_CHART_COLORS[
    Math.floor(index) % OUTCOME_CHART_COLORS.length
  ] as string;
}

/**
 * Colours for the outcomes a chart should draw, in display order.
 *
 * Returns pairs so the caller cannot pair a name with the wrong colour by
 * re-deriving the index.
 */
export function plottedOutcomeColors(
  names: string[]
): { name: string; color: string }[] {
  return names
    .slice(0, MAX_PLOTTED_OUTCOMES)
    .map((name, i) => ({ name, color: outcomeColor(i) }));
}