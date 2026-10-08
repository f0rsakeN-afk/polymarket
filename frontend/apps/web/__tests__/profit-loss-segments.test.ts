/**
 * Tests for the sign-splitting helper that profit-loss-line.tsx consumes.
 *
 * The module was missing from the tree entirely (imported but never created),
 * which is what left `packages/ui` failing `tsc` after the module-resolution
 * fix. These tests pin the contract the call site depends on.
 */
import { describe, expect, it } from "vitest";
import { splitProfitLossSegments } from "@workspace/ui/components/charts/profit-loss-segments";

const pt = (value: unknown) => ({ date: "2024-01-01", value });

describe("splitProfitLossSegments", () => {
  it("keeps an all-positive series as one run", () => {
    const segments = splitProfitLossSegments({
      data: [pt(1), pt(2), pt(3)],
      dataKey: "value",
    });

    expect(segments).toHaveLength(1);
    expect(segments[0]!.isPositive).toBe(true);
    expect(segments[0]!.data).toHaveLength(3);
  });

  it("keeps an all-negative series as one run", () => {
    const segments = splitProfitLossSegments({
      data: [pt(-1), pt(-2), pt(-3)],
      dataKey: "value",
    });

    expect(segments).toHaveLength(1);
    expect(segments[0]!.isPositive).toBe(false);
  });

  it("starts a new run when the sign flips", () => {
    const segments = splitProfitLossSegments({
      data: [pt(1), pt(2), pt(-1), pt(-2), pt(3)],
      dataKey: "value",
    });

    expect(segments.map((s) => s.isPositive)).toEqual([true, false]);
    expect(segments[0]!.data).toHaveLength(2);
    expect(segments[1]!.data).toHaveLength(2);
    // Trailing positive singleton is dropped: a line needs two points.
    expect(segments).toHaveLength(2);
  });

  it("treats zero as positive", () => {
    // Matches segmentLegendIndex, which maps `value >= 0` to slot 0.
    const segments = splitProfitLossSegments({
      data: [pt(-1), pt(0), pt(1)],
      dataKey: "value",
    });

    expect(segments.map((s) => s.isPositive)).toEqual([true]);
    expect(segments[0]!.data).toHaveLength(2);
  });

  it("breaks the run on a gap rather than bridging it", () => {
    const segments = splitProfitLossSegments({
      data: [pt(1), pt(2), pt(Number.NaN), pt(3), pt(4)],
      dataKey: "value",
    });

    expect(segments).toHaveLength(2);
    expect(segments[0]!.data).toHaveLength(2);
    expect(segments[1]!.data).toHaveLength(2);
  });

  it("drops runs that cannot draw a line", () => {
    const segments = splitProfitLossSegments({
      data: [pt(1), pt(-1)],
      dataKey: "value",
    });

    expect(segments).toHaveLength(0);
  });

  it("tolerates empty input and a missing field", () => {
    expect(splitProfitLossSegments({ data: [], dataKey: "value" })).toEqual([]);
    expect(
      splitProfitLossSegments({ data: [pt(1), pt(2)], dataKey: "nope" })
    ).toEqual([]);
  });
});