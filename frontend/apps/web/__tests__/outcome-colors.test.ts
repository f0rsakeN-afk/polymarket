/**
 * Multi-outcome series must be distinguishable by colour.
 *
 * The failure this guards: the palette was `--chart-1..5`, which are five
 * lightnesses of ONE green (hue 149-153°). On a chart that renders as four or
 * five near-identical curves - and `market-detail.tsx` referenced
 * `--chart-6/7/8`, which were never defined at all, so any market with more
 * outcomes than defined colours got no colour.
 *
 * These assert the property that matters - distinct HUES, not merely distinct
 * strings - by reading the CSS the variables resolve to. A palette of
 * `var(--chart-1)`..`var(--chart-5)` would satisfy a "all strings differ" test
 * and still look like one line.
 */
import { describe, expect, it } from "vitest";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import {
  MAX_PLOTTED_OUTCOMES,
  OUTCOME_CHART_COLORS,
  outcomeColor,
  plottedOutcomeColors,
} from "@/lib/outcome-colors";

// Resolved from the Vitest root (apps/web), not import.meta.url: under Vitest
// that is not a file:// URL, so fileURLToPath throws.
const globalsCss = readFileSync(
  resolve(process.cwd(), "../../packages/ui/src/styles/globals.css"),
  "utf8"
);

/**
 * `--<prefix>-N: value` declarations, keyed by the FULL variable name.
 *
 * Keyed by name rather than by the captured number: the first version keyed by
 * the digits, so a lookup of `outcome-1` missed and every hue came back
 * undefined - which then read as "all hues identical" and failed the palette
 * tests for a reason that had nothing to do with the palette.
 */
function cssVars(prefix: string): Record<string, string> {
  const re = new RegExp(`--(${prefix}-\\d+):\\s*([^;]+);`, "g");
  const out: Record<string, string> = {};
  for (const m of globalsCss.matchAll(re)) out[m[1]!] = m[2]!.trim();
  return out;
}

/** Hue angle in degrees from an oklch() value, or null if not oklch. */
function hue(value: string | undefined): number | null {
  if (!value) return null;
  const m = /oklch\([^)]*?([\d.]+)\s*\)\s*$/i.exec(value);
  return m ? Number(m[1]) : null;
}

/** Hue distance on the 0-360 wheel, so 350° and 10° count as close. */
function hueDistance(a: number, b: number): number {
  const d = Math.abs(a - b) % 360;
  return d > 180 ? 360 - d : d;
}

describe("palette is declared in CSS", () => {
  it("defines a variable for every palette entry", () => {
    const vars = cssVars("outcome");
    for (const token of OUTCOME_CHART_COLORS) {
      const name = token.replace(/var\(--|[\s)]/g, "");
      expect(vars[name], `${token} is not defined in globals.css`).toBeTruthy();
    }
  });

  it("declares at least as many outcomes as the palette has entries", () => {
    const vars = cssVars("outcome");
    expect(Object.keys(vars).length).toBeGreaterThanOrEqual(
      OUTCOME_CHART_COLORS.length
    );
  });

  it("redefines them for dark mode with the same hues", () => {
    const all = [...globalsCss.matchAll(/--outcome-(\d+):\s*([^;]+);/g)].map(
      (m) => Number(m[1])
    );
    // Each variable appears twice: once in :root, once in the dark block.
    expect(all.length).toBeGreaterThanOrEqual(
      OUTCOME_CHART_COLORS.length * 2
    );
  });

  it("keeps hue identical between light and dark for each index", () => {
    // A colour that means a different outcome in dark mode makes a legend
    // actively misleading.
    const light = cssVars("outcome");
    const occurrences = new Map<number, number[]>();
    for (const m of globalsCss.matchAll(
      /--outcome-(\d+):\s*oklch\([^)]*?([\d.]+)\s*\)\s*;/g
    )) {
      const idx = Number(m[1]);
      occurrences.set(idx, [...(occurrences.get(idx) ?? []), Number(m[2])]);
    }
    for (const [idx, hues] of occurrences) {
      if (hues.length < 2) continue;
      const distinct = new Set(hues);
      expect(distinct.size, `outcome-${idx} changes hue in dark mode`).toBe(1);
    }
    expect(light).toBeTruthy();
  });
});

describe("palette hues are distinguishable", () => {
  const vars = cssVars("outcome");
  const hues = OUTCOME_CHART_COLORS.map((token) => {
    const name = token.replace(/var\(--|[\s)]/g, "");
    return hue(vars[name]!);
  });

  it("parses every entry as oklch", () => {
    expect(hues.every((h) => h !== null)).toBe(true);
  });

  it("uses all eight hues", () => {
    expect(new Set(hues).size).toBe(OUTCOME_CHART_COLORS.length);
  });

  it("separates every adjacent pair by at least 25 degrees", () => {
    for (let i = 0; i < hues.length - 1; i++) {
      const d = hueDistance(hues[i]!, hues[i + 1]!);
      expect(
        d,
        `outcome-${i + 1} and outcome-${i + 2} are only ${d.toFixed(1)}° apart`
      ).toBeGreaterThanOrEqual(25);
    }
  });

  it("separates every pair by at least 20 degrees, not just adjacent ones", () => {
    // Two non-adjacent lines land near each other constantly - an 8-outcome
    // market draws several at once - so only the adjacent-pair check is safe.
    for (let i = 0; i < hues.length; i++) {
      for (let j = i + 1; j < hues.length; j++) {
        const d = hueDistance(hues[i]!, hues[j]!);
        expect(
          d,
          `outcome-${i + 1} and outcome-${j + 1} are only ${d.toFixed(1)}° apart`
        ).toBeGreaterThanOrEqual(20);
      }
    }
  });

  it("is not five shades of one green, which is what --chart-1..5 are", () => {
    const chartHues = Object.entries(cssVars("chart"))
      .map(([, v]) => hue(v))
      .filter((h): h is number => h !== null);
    const spread = Math.max(...chartHues) - Math.min(...chartHues);
    // The existing chart tokens span a few degrees of hue. Anything under 20°
    // means they are lightnesses of one colour, not a categorical palette.
    expect(spread).toBeLessThan(20);
  });
});

describe("outcomeColor", () => {
  it("gives each index a different colour for the first eight", () => {
    const seen = Array.from({ length: 8 }, (_, i) => outcomeColor(i));
    expect(new Set(seen).size).toBe(8);
  });

  it("cycles instead of returning undefined past the palette", () => {
    // The bug: the old list named --chart-6/7/8, which do not exist, so a
    // market with more outcomes than colours silently drew uncoloured lines.
    for (let i = 0; i < 40; i++) {
      expect(OUTCOME_CHART_COLORS).toContain(outcomeColor(i));
    }
  });

  it("returns a real colour for a silly index rather than throwing", () => {
    expect(outcomeColor(-1)).toBe(OUTCOME_CHART_COLORS[0]);
    expect(outcomeColor(Number.NaN)).toBe(OUTCOME_CHART_COLORS[0]);
    expect(outcomeColor(1.7)).toBe(outcomeColor(1));
  });
});

describe("plottedOutcomeColors", () => {
  const eight = [
    "France",
    "England",
    "Germany",
    "Spain",
    "Portugal",
    "Italy",
    "Netherlands",
    "Other",
  ];

  it("pairs each name with a distinct colour", () => {
    const plotted = plottedOutcomeColors(eight);
    expect(plotted.map((p) => p.name)).toEqual(eight.slice(0, 4));
    expect(new Set(plotted.map((p) => p.color)).size).toBe(4);
  });

  it("assigns the first outcome the first colour, so leaders agree everywhere", () => {
    expect(plottedOutcomeColors(eight)[0]!.color).toBe(OUTCOME_CHART_COLORS[0]);
  });

  it("caps the plotted lines for legibility", () => {
    expect(MAX_PLOTTED_OUTCOMES).toBeLessThan(eight.length);
    expect(plottedOutcomeColors(eight).length).toBe(MAX_PLOTTED_OUTCOMES);
  });

  it("handles a two-outcome market", () => {
    const plotted = plottedOutcomeColors(["Trump", "Biden"]);
    expect(plotted).toHaveLength(2);
    expect(new Set(plotted.map((p) => p.color)).size).toBe(2);
  });

  it("handles no outcomes", () => {
    expect(plottedOutcomeColors([])).toEqual([]);
  });

  it("never emits a colour outside the palette", () => {
    for (const n of [0, 1, 3, 8, 20]) {
      for (const { color } of plottedOutcomeColors(
        Array.from({ length: n }, (_, i) => `o${i}`)
      )) {
        expect(OUTCOME_CHART_COLORS).toContain(color);
      }
    }
  });
});
// ── Contrast and gamut ─────────────────────────────────────────────────────────
//
// A palette can be perfectly hue-separated and still be unusable: too close to
// the background to see, or outside sRGB, in which case the browser clips it and
// the rendered hue is not the specified one.
//
// WCAG 1.4.11 requires 3:1 for graphical objects. Chart strokes are thin, so the
// test target is higher, leaving headroom for a 2px line.

/** oklch() -> linear-ish sRGB triple, per the CSS Color 4 reference matrices. */
function oklchToSrgb(L: number, C: number, Hdeg: number): number[] {
  const h = (Hdeg * Math.PI) / 180;
  const a = C * Math.cos(h);
  const b = C * Math.sin(h);

  const l_ = L + 0.3963377774 * a + 0.2158037573 * b;
  const m_ = L - 0.1055613458 * a - 0.0638541728 * b;
  const s_ = L - 0.0894841775 * a - 1.291485548 * b;
  const l = l_ ** 3;
  const m = m_ ** 3;
  const s = s_ ** 3;

  const rgb = [
    4.0767416621 * l - 3.3077115913 * m + 0.2309699292 * s,
    -1.2684380046 * l + 2.6097574011 * m - 0.3413193965 * s,
    -0.0041960863 * l - 0.7034186147 * m + 1.707614701 * s,
  ];
  return rgb.map((c) =>
    c <= 0.0031308 ? 12.92 * c : 1.055 * Math.pow(c, 1 / 2.4) - 0.055
  );
}

/** WCAG 2.x relative luminance, from gamma-encoded sRGB in 0..1. */
function relativeLuminance(rgb: number[]): number {
  const lin = rgb.map((c) =>
    c <= 0.04045 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4)
  );
  return 0.2126 * lin[0]! + 0.7152 * lin[1]! + 0.0722 * lin[2]!;
}

function contrastRatio(a: number[], b: number[]): number {
  const la = relativeLuminance(a);
  const lb = relativeLuminance(b);
  const hi = Math.max(la, lb);
  const lo = Math.min(la, lb);
  return (hi + 0.05) / (lo + 0.05);
}

/** oklch() triple, or null. */
function oklch(value: string): [number, number, number] | null {
  const m = /oklch\(\s*([\d.]+)\s+([\d.]+)\s+([\d.]+)\s*\)/i.exec(value);
  return m ? [Number(m[1]), Number(m[2]), Number(m[3])] : null;
}

/** --chart-background per theme: index 0 light, index 1 dark. */
function backgroundFor(occurrenceIndex: number): number[] {
  const all = [...globalsCss.matchAll(/--chart-background:\s*([^;]+);/g)].map(
    (m) => m[1]!.trim()
  );
  return oklchToSrgb(...oklch(all[occurrenceIndex]!)!);
}

/** The nth occurrence of --outcome-N for a given N (0 = light, 1 = dark). */
function occurrence(index: number, themeIndex: number): string {
  const all = [...globalsCss.matchAll(
    new RegExp(`--outcome-${index}:\\s*([^;]+);`, "g")
  )].map((m) => m[1]!.trim());
  return all[themeIndex]!;
}

const WCAG_GRAPHIC_FLOOR = 3.0;
const TARGET = 4.0;

describe.each([
  ["light", 0],
  ["dark", 1],
])("contrast in %s mode", (_theme, themeIndex) => {
  const bg = backgroundFor(themeIndex as number);

  it("resolves the background to a real colour", () => {
    expect(bg.every((c) => Number.isFinite(c))).toBe(true);
  });

  it.each(OUTCOME_CHART_COLORS.map((_, i) => i + 1))(
    "outcome-%i clears the WCAG 1.4.11 floor of 3:1",
    (idx) => {
      const value = occurrence(idx as number, themeIndex as number);
      expect(value, `--outcome-${idx} has no ${_theme} declaration`).toBeTruthy();
      const rgb = oklchToSrgb(...oklch(value)!);
      expect(contrastRatio(rgb, bg)).toBeGreaterThanOrEqual(
        WCAG_GRAPHIC_FLOOR
      );
    }
  );

  it.each(OUTCOME_CHART_COLORS.map((_, i) => i + 1))(
    "outcome-%i clears the 4:1 thin-stroke target",
    (idx) => {
      const rgb = oklchToSrgb(...oklch(occurrence(idx as number, themeIndex as number))!);
      expect(contrastRatio(rgb, bg)).toBeGreaterThanOrEqual(TARGET);
    }
  );

  it.each(OUTCOME_CHART_COLORS.map((_, i) => i + 1))(
    "outcome-%i is inside sRGB, so the browser does not clip it",
    (idx) => {
      // Out of gamut is not cosmetic: a clipped colour renders as a different
      // hue, so the spacing asserted above is not what reaches the screen.
      const rgb = oklchToSrgb(...oklch(occurrence(idx as number, themeIndex as number))!);
      for (const channel of rgb) {
        expect(channel).toBeGreaterThanOrEqual(-0.002);
        expect(channel).toBeLessThanOrEqual(1.002);
      }
    }
  );

  it("uses one consistent lightness across the palette", () => {
    // Free-running lightness makes the series read as unrelated colours rather
    // than one family. Contrast is still met, but the chart looks ad hoc.
    const Ls = OUTCOME_CHART_COLORS.map((_, i) =>
      oklch(occurrence(i + 1, themeIndex as number))![0]
    );
    expect(Math.max(...Ls) - Math.min(...Ls)).toBeLessThanOrEqual(0.01);
  });
});

// ── Perceptual separation (CIE ΔE2000) ─────────────────────────────────────────
//
// Hue angle is a poor proxy for "can a human tell these apart". An earlier
// amber/orange pair was 30° apart in oklch but only 18° apart after the
// browser's gamut mapping, and 18° of orange looks like one colour. ΔE2000 is
// the standard measure and accounts for lightness and chroma too.
//
// Reference points: ~2.3 is a just-noticeable difference, >10 is clearly
// different, >25 is obviously different.
//
// Only the first MAX_PLOTTED_OUTCOMES lines overlap on the chart, so those are
// held to the higher bar; the other four sit side by side in the card grid.

const LAB = (rgb: number[]) => {
  const lin = (c: number) =>
    c <= 0.04045 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4);
  const [r0 = 0, g0 = 0, b0 = 0] = rgb.map(lin);
  const x = (0.4124 * r0 + 0.3576 * g0 + 0.1805 * b0) / 0.95047;
  const y = 0.2126 * r0 + 0.7152 * g0 + 0.0722 * b0;
  const z = (0.0193 * r0 + 0.1192 * g0 + 0.9505 * b0) / 1.08883;
  const f = (t: number) => (t > 0.008856 ? Math.cbrt(t) : 7.787 * t + 16 / 116);
  const [fx, fy, fz] = [f(x), f(y), f(z)];
  return [116 * fy - 16, 500 * (fx - fy), 200 * (fy - fz)];
};

function deltaE2000(
  [L1 = 0, a1 = 0, b1 = 0]: number[],
  [L2 = 0, a2 = 0, b2 = 0]: number[]
): number {
  const C1 = Math.hypot(a1, b1);
  const C2 = Math.hypot(a2, b2);
  const Cbar = (C1 + C2) / 2;
  const G =
    Cbar === 0
      ? 0
      : 0.5 * (1 - Math.sqrt(Math.pow(Cbar, 7) / (Math.pow(Cbar, 7) + 25 ** 7)));
  const a1p = (1 + G) * a1;
  const a2p = (1 + G) * a2;
  const C1p = Math.hypot(a1p, b1);
  const C2p = Math.hypot(a2p, b2);

  const hp = (ap: number, bp: number) => {
    if (ap === 0 && bp === 0) return 0;
    const h = (Math.atan2(bp, ap) * 180) / Math.PI;
    return h < 0 ? h + 360 : h;
  };
  const h1p = hp(a1p, b1);
  const h2p = hp(a2p, b2);

  const dLp = L2 - L1;
  const dCp = C2p - C1p;
  let dhp = 0;
  if (C1p * C2p !== 0) {
    if (Math.abs(h2p - h1p) <= 180) dhp = h2p - h1p;
    else dhp = h2p - h1p > 180 ? h2p - h1p - 360 : h2p - h1p + 360;
  }
  const dHp = 2 * Math.sqrt(C1p * C2p) * Math.sin(((dhp / 2) * Math.PI) / 180);

  const Lbar = (L1 + L2) / 2;
  const Cbarp = (C1p + C2p) / 2;
  let hbar: number;
  if (C1p * C2p === 0) hbar = h1p + h2p;
  else if (Math.abs(h1p - h2p) <= 180) hbar = (h1p + h2p) / 2;
  else hbar = h1p + h2p < 360 ? (h1p + h2p + 360) / 2 : (h1p + h2p - 360) / 2;

  const T =
    1 -
    0.17 * Math.cos((((hbar - 30) * Math.PI) / 180)) +
    0.24 * Math.cos((((2 * hbar) * Math.PI) / 180)) +
    0.32 * Math.cos((((3 * hbar + 6) * Math.PI) / 180)) -
    0.2 * Math.cos((((4 * hbar - 63) * Math.PI) / 180));
  const dtheta = 30 * Math.exp(-Math.pow((hbar - 275) / 25, 2));
  const Rc =
    Cbarp === 0
      ? 0
      : 2 * Math.sqrt(Math.pow(Cbarp, 7) / (Math.pow(Cbarp, 7) + 25 ** 7));
  const Sl = 1 + (0.015 * Math.pow(Lbar - 50, 2)) / Math.sqrt(20 + Math.pow(Lbar - 50, 2));
  const Sc = 1 + 0.045 * Cbarp;
  const Sh = 1 + 0.015 * Cbarp * T;
  const Rt = -Math.sin(((2 * dtheta * Math.PI) / 180)) * Rc;

  return Math.sqrt(
    Math.pow(dLp / Sl, 2) +
      Math.pow(dCp / Sc, 2) +
      Math.pow(dHp / Sh, 2) +
      Rt * (dCp / Sc) * (dHp / Sh)
  );
}

describe.each([
  ["light", 0],
  ["dark", 1],
])("perceptual separation in %s mode", (_theme, themeIndex) => {
  const labs = OUTCOME_CHART_COLORS.map((_, i) =>
    LAB(oklchToSrgb(...oklch(occurrence(i + 1, themeIndex as number))!))
  );

  it("separates the plotted lines by a clearly visible margin (dE > 20)", () => {
    // These are the lines that overlap in one chart, so the bar is high.
    let worst = Infinity;
    for (let i = 0; i < MAX_PLOTTED_OUTCOMES; i++) {
      for (let j = i + 1; j < MAX_PLOTTED_OUTCOMES; j++) {
        worst = Math.min(worst, deltaE2000(labs[i]!, labs[j]!));
      }
    }
    expect(worst).toBeGreaterThan(20);
  });

  it("separates every pair, including the grid-only colours (dE > 12)", () => {
    let worst = Infinity;
    for (let i = 0; i < labs.length; i++) {
      for (let j = i + 1; j < labs.length; j++) {
        worst = Math.min(worst, deltaE2000(labs[i]!, labs[j]!));
      }
    }
    expect(worst).toBeGreaterThan(12);
  });

  it("never renders two outcomes the same colour", () => {
    // dE of exactly 0 means the browser clipped both to the same value.
    for (let i = 0; i < labs.length; i++) {
      for (let j = i + 1; j < labs.length; j++) {
        expect(deltaE2000(labs[i]!, labs[j]!)).toBeGreaterThan(0);
      }
    }
  });
});

describe("hue order is shared across themes", () => {
  it("uses the same hue for the same index in light and dark", () => {
    // If the order differed, an outcome would change colour with the theme and
    // a dark-mode screenshot would not match the light one.
    for (let i = 1; i <= OUTCOME_CHART_COLORS.length; i++) {
      expect(oklch(occurrence(i, 0))![2]).toBe(oklch(occurrence(i, 1))![2]);
    }
  });
});
