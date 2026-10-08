/**
 * Regression tests for the live price chart reading "zero" when the price was
 * actually steady.
 *
 * The bug: <LiveLine dataKey="Yes"/> reads `d["Yes"]` from the chart's
 * contextData, but contextData used to be rebuilt containing only
 * value/yes_price/no_price. Every "Yes" lookup missed and getY fell through to
 * its literal `: 0` fallback, so a YES price of 0.6 rendered as 0.00 with the
 * whole line pinned to y=0. The virtual "now" tip point dropped the keys too,
 * which is why the line dived even once real points were fixed.
 */
import { describe, expect, it } from "vitest";
import { render, act } from "@testing-library/react";
import { createElement } from "react";
import {
  LiveLineChart,
  type LiveLinePoint,
} from "@workspace/ui/components/charts/live-line-chart";
import { LiveLine } from "@workspace/ui/components/charts/live-line";

const NOW = Math.floor(Date.now() / 1000);
const HEIGHT = 220;

function renderChart(
  data: LiveLinePoint[],
  props: Record<string, unknown>,
  dataKey: string
) {
  const { container } = render(
    createElement(
      LiveLineChart as never,
      {
        data,
        window: 60,
        numXTicks: 5,
        height: HEIGHT,
        margin: { top: 16, right: 36, bottom: 40, left: 48 },
        ...props,
      } as never,
      createElement(LiveLine as never, { dataKey } as never)
    )
  );
  return container;
}

/** The stroked path is the line; the area fill has no stroke. */
function linePath(container: HTMLElement) {
  return Array.from(container.querySelectorAll("path")).find((p) =>
    (p.getAttribute("stroke") ?? "").includes("url")
  );
}

/**
 * Every y coordinate in the path, at sub-pixel precision.
 *
 * NaN must be stripped AFTER pairing: a gap is written as a real "NaN" token,
 * so dropping it first would shift every later coordinate by one and report an
 * x as if it were a y.
 */
function pathYs(path: SVGPathElement | undefined): number[] {
  // Match numbers explicitly rather than stripping letters: d3 writes a gap as
  // the literal token "NaN", and blanking the letters turns it into "" which
  // Number() reads as 0 - i.e. a fabricated zero out of a genuine gap.
  const tokens = (path?.getAttribute("d") ?? "").match(
    /NaN|-?\d*\.?\d+(?:[eE][-+]?\d+)?/g
  );
  if (!tokens) return [];
  const nums = tokens.map((t) => (t === "NaN" ? Number.NaN : Number(t)));

  const ys: number[] = [];
  for (let i = 0; i + 1 < nums.length; i += 2) {
    const y = nums[i + 1];
    if (typeof y === "number" && Number.isFinite(y)) ys.push(y);
  }
  return ys;
}

function badgeTexts(container: HTMLElement) {
  return Array.from(container.querySelectorAll("text")).map((t) => t.textContent);
}

/**
 * The chart eases its y-domain from [0,100] toward the real range, so a short
 * wait leaves every value inside one pixel and a moving series falsely reads as
 * flat. Let the animation settle before measuring.
 */
async function settle(ms = 3000) {
  await act(async () => {
    await new Promise((r) => setTimeout(r, ms));
  });
}

describe("LiveLineChart dataKey passthrough", () => {
  it("holds a steady YES price of 0.6 instead of collapsing to zero", async () => {
    // Exactly what market-detail builds: `value` plus capitalised outcome keys.
    const data: LiveLinePoint[] = [
      { time: NOW - 30, value: 0.6, Yes: 0.6, No: 0.4 },
      { time: NOW - 20, value: 0.6, Yes: 0.6, No: 0.4 },
      { time: NOW - 10, value: 0.6, Yes: 0.6, No: 0.4 },
      { time: NOW, value: 0.6, Yes: 0.6, No: 0.4 },
    ];

    const container = renderChart(data, { value: 0.6, valueNo: 0.4 }, "Yes");
    await settle();

    expect(badgeTexts(container)).toContain("0.60");
    expect(badgeTexts(container)).not.toContain("0.00");

    const ys = pathYs(linePath(container));
    expect(ys.length).toBeGreaterThan(0);
    // y=0 is the top edge of the plot: the signature of the missing-key bug.
    expect(ys.every((y) => y !== 0)).toBe(true);
    // Steady price -> a flat line is correct.
    expect(new Set(ys.map((y) => Math.round(y * 100))).size).toBe(1);
  });

  it("tracks a changing YES price", async () => {
    const values = [0.4, 0.55, 0.7, 0.8];
    const data: LiveLinePoint[] = values.map((v, i) => ({
      time: NOW - 30 + i * 10,
      value: v,
      Yes: v,
      No: 1 - v,
    }));

    const container = renderChart(data, { value: 0.8, valueNo: 0.2 }, "Yes");
    await settle();

    const ys = pathYs(linePath(container));
    expect(new Set(ys.map((y) => Math.round(y * 100))).size).toBeGreaterThan(1);
    expect(ys.every((y) => y !== 0)).toBe(true);
    expect(badgeTexts(container)).toContain("0.80");
  });

  it("renders multi-outcome series keyed by outcome name", async () => {
    // Multi-outcome markets pass valueNo={undefined}, so the virtual tip point
    // has no secondary keys at all - the case that used to dive to zero.
    const data: LiveLinePoint[] = [
      { time: NOW - 20, value: 0.3, "Team A": 0.3, "Team B": 0.6 },
      { time: NOW - 10, value: 0.5, "Team A": 0.5, "Team B": 0.4 },
      { time: NOW, value: 0.7, "Team A": 0.7, "Team B": 0.2 },
    ];

    const container = renderChart(data, { value: 0.7 }, "Team A");
    await settle();

    const ys = pathYs(linePath(container));
    expect(ys.length).toBeGreaterThan(0);
    expect(ys.every((y) => y !== 0)).toBe(true);
    expect(new Set(ys.map((y) => Math.round(y * 100))).size).toBeGreaterThan(1);
  });

  it("still honours the plain `value` key used by the trending carousel", async () => {
    const data: LiveLinePoint[] = [
      { time: NOW - 30, value: 0.3 },
      { time: NOW - 20, value: 0.5 },
      { time: NOW, value: 0.7 },
    ];

    const container = renderChart(data, { value: 0.7 }, "value");
    await settle();

    expect(badgeTexts(container)).toContain("0.70");
    const ys = pathYs(linePath(container));
    expect(new Set(ys.map((y) => Math.round(y * 100))).size).toBeGreaterThan(1);
  });

  it("does not fabricate a zero when a series key is missing entirely", async () => {
    // A point set with no "Yes" key at all. getY used to answer 0 for a missing
    // key, which d3 plots as a real zero, so the line and the badge both claimed
    // 0.00. It must now render as a gap instead.
    const data = [
      { time: NOW - 20, value: 0.6 },
      { time: NOW - 10, value: 0.6 },
      { time: NOW, value: 0.6 },
    ] as LiveLinePoint[];

    const container = renderChart(data, { value: 0.6 }, "Yes");
    await settle();

    // No 0.00 badge anywhere in the chart.
    expect(badgeTexts(container)).not.toContain("0.00");

    const ys = pathYs(linePath(container));
    // No NaN leaked into a plotted coordinate and no fabricated zero.
    expect(ys.every((y) => Number.isFinite(y))).toBe(true);
    expect(ys.some((y) => y === 0)).toBe(false);
  });

  it("keeps the y-domain around the data instead of 0-100", async () => {
    // The domain used to be seeded at [0,100] and eased toward the data, which
    // squashed a 0.3-0.7 market into a couple of pixels for a couple of seconds.
    const data: LiveLinePoint[] = [
      { time: NOW - 20, value: 0.3, Yes: 0.3 },
      { time: NOW, value: 0.7, Yes: 0.7 },
    ];

    const container = renderChart(data, { value: 0.7 }, "Yes");
    // No settle(): read the very first committed frame.
    await settle(300);

    const ys = pathYs(linePath(container)).filter((y) => Number.isFinite(y));
    const spread = Math.max(...ys) - Math.min(...ys);
    // On a 0-100 axis this would be ~2px of a ~164px plot.
    expect(spread).toBeGreaterThan(20);
  });
});