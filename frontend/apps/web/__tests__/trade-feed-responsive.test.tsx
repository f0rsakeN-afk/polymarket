/**
 * Trade feed responsiveness.
 *
 * The row is a CSS grid whose tracks are percentage widths. Hiding a cell with
 * `display:none` removes it from the grid, so the surviving tracks keep their
 * widths and stop short of the full row. The old single column set summed to
 * 100% across all seven columns, which meant a phone rendered Trader(20%) +
 * Side(10%) + Total(15%) = 45% of the row, leaving 55% blank and stranding
 * "Total" mid-row instead of flush right.
 *
 * jsdom does not lay out, so these assert the invariant that would have caught
 * it - each breakpoint's column set fills the row on its own.
 */
import { describe, expect, it } from "vitest";
import {
  DESKTOP_COLUMNS,
  MOBILE_COLUMNS,
  columnWidthSum,
} from "@/components/trades/trade-feed";

describe("trade feed column sets", () => {
  it("each set fills 100% of the row independently", () => {
    // The invariant the bug violated. Hidden cells drop out of the grid, so a
    // set that only reaches 100% when combined with another set leaves a gap.
    expect(columnWidthSum(MOBILE_COLUMNS)).toBe(100);
    expect(columnWidthSum(DESKTOP_COLUMNS)).toBe(100);
  });

  it("the phone set is a genuine subset in the same order", () => {
    // Mobile must be an ordered subsequence of desktop: the cells are rendered
    // into one grid and swapped by breakpoint, so a mismatch would label the
    // wrong column.
    const desktopLabels = DESKTOP_COLUMNS.map((c) => c.label);
    MOBILE_COLUMNS.forEach((col) => {
      expect(desktopLabels).toContain(col.label);
    });

    // And in the same relative order.
    const positions = MOBILE_COLUMNS.map((col) => desktopLabels.indexOf(col.label));
    expect(positions).toEqual([...positions].sort((a, b) => a - b));
  });

  it("keeps Total as the last visible column on phones, flush right", () => {
    const last = MOBILE_COLUMNS.at(-1)!;
    expect(last.label).toBe("Total");
    expect(last.align).toBe("right");
  });

  it("drops Price and Shares on phones but keeps them on desktop", () => {
    const mobileLabels = MOBILE_COLUMNS.map((c) => c.label);
    const desktopLabels = DESKTOP_COLUMNS.map((c) => c.label);

    expect(desktopLabels).toContain("Price");
    expect(desktopLabels).toContain("Shares");
    // Dropped rather than squeezed: at 45% of a 360px screen these are
    // unreadable, and Total is their product.
    expect(mobileLabels).not.toContain("Price");
    expect(mobileLabels).not.toContain("Shares");
  });

  it("has no column flagged as an sm-only spacer", () => {
    // `hiddenSm` was the original mechanism. It is gone: the mobile set is now
    // explicit, so no cell needs to be hidden from a shared set.
    expect(MOBILE_COLUMNS.some((c) => c.hiddenSm)).toBe(false);
    expect(DESKTOP_COLUMNS.some((c) => c.hiddenSm)).toBe(false);
  });
});
