/**
 * Money arithmetic on decimal strings.
 *
 * These tests exist because the failure mode is invisible: `0.3 - 0.1` is
 * `0.19999999999999998` in floating point, which renders as a plausible-looking
 * number and disagrees with the ledger by a hundredth of a cent. Nothing throws.
 * Nothing looks wrong. The operator just moves a slightly different amount than
 * the page told them they would.
 */
import { describe, expect, it } from "vitest";

import { add, group, subtract } from "@/lib/decimal";

describe("subtract", () => {
  it("is exact where floating point is not", () => {
    expect(subtract("0.3", "0.1")).toBe("0.2");
    expect(0.3 - 0.1).not.toBe(0.2); // the reason this module exists
  });

  it("keeps full precision rather than rounding away the remainder", () => {
    // The trailing zeros are the point, not sloppiness: the result is exact and
    // carries the inputs' scale, so a USDC figure reads at a consistent precision
    // next to its neighbours instead of varying with whatever was subtracted.
    expect(subtract("1.005", "0.005")).toBe("1.000");
    expect(subtract("2.675", "0.675")).toBe("2.000");
    // ...and the value is exactly 1, not "1.0000000000000002".
    expect(Number(subtract("1.005", "0.005"))).toBe(1);
  });

  it("aligns differing scales without padding errors", () => {
    expect(subtract("100", "0.5")).toBe("99.5");
    expect(subtract("1.25", "1.125")).toBe("0.125");
  });

  it("handles the pending-fees case the page actually asks", () => {
    expect(subtract("1000", "250.75")).toBe("749.25");
  });

  it("reports a negative balance rather than clamping it", () => {
    // Distributed can exceed collected while a distribution is in flight. A
    // clamped zero would tell an operator there is nothing waiting when there is
    // actually a discrepancy worth noticing.
    expect(subtract("250.75", "1000")).toBe("-749.25");
  });

  it("treats missing and malformed values as zero rather than crashing", () => {
    expect(subtract("", "5")).toBe("-5");
    expect(subtract(undefined as unknown as string, "5")).toBe("-5");
    expect(subtract("abc", "5")).toBe("-5");
    expect(subtract(".", "5")).toBe("-5");
  });

  it("handles integers with no decimal point", () => {
    expect(subtract("1000", "1000")).toBe("0");
    expect(subtract("10", "0")).toBe("10");
  });

  it("preserves trailing precision from the inputs", () => {
    expect(subtract("1.500", "0.5")).toBe("1.000");
  });
});

describe("add", () => {
  it("is exact", () => {
    expect(add("0.1", "0.2")).toBe("0.3");
    expect(add("1.005", "0.005")).toBe("1.010");
  });
});

describe("group", () => {
  it("groups thousands on the string, not the number", () => {
    expect(group("1234567.5")).toBe("1,234,567.5");
    expect(group("1000")).toBe("1,000");
    expect(group("-2500000.25")).toBe("-2,500,000.25");
  });

  it("leaves anything it does not recognise untouched", () => {
    expect(group("")).toBe("");
    expect(group("abc")).toBe("abc");
  });
});