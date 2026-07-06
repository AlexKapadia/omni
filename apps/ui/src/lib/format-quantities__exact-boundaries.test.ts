/**
 * Exactness tests for display formatting — the zero-numerical-error mandate.
 * Every boundary is asserted on / just-over / just-under; money is proven
 * exact through integer-cent arithmetic (no float rounding drift).
 */
import { describe, expect, it } from "vitest";
import {
  formatCentsUsd,
  formatDayLabel,
  formatDurationMin,
  formatStartsIn,
  formatTokensCompact,
} from "./format-quantities";
import { ledgerTotals } from "./settings-store";

describe("formatTokensCompact", () => {
  it.each<[number, string]>([
    [0, "0"],
    [999, "999"],
    [1_000, "1K"],
    [1_999, "1K"], // floors — never inflates usage
    [246_000, "246K"],
    [999_999, "999K"],
    [1_000_000, "1.00M"],
    [1_210_000, "1.21M"],
    [1_219_999, "1.21M"], // floors at the second decimal
    [-5, "0"],
    [Number.NaN, "0"],
  ])("formatTokensCompact(%d) === %s", (input, expected) => {
    expect(formatTokensCompact(input)).toBe(expected);
  });
});

describe("formatCentsUsd is exact to the cent", () => {
  it.each<[number, string]>([
    [0, "$0.00"],
    [1, "$0.01"],
    [99, "$0.99"],
    [100, "$1.00"],
    [412, "$4.12"],
    [599, "$5.99"],
    [123456, "$1234.56"],
  ])("formatCentsUsd(%d) === %s", (cents, expected) => {
    expect(formatCentsUsd(cents)).toBe(expected);
  });

  it("classic float trap: 0.1 + 0.2 dollars as cents is exactly $0.30", () => {
    expect(formatCentsUsd(10 + 20)).toBe("$0.30");
  });
});

describe("ledgerTotals sums exactly", () => {
  it("matches hand-computed integer sums", () => {
    const totals = ledgerTotals([
      { task: "a", calls: 92, tokens: 1_210_000, p50Seconds: 3.8, costCents: 412 },
      { task: "b", calls: 214, tokens: 246_000, p50Seconds: 1.4, costCents: 96 },
      { task: "c", calls: 68, tokens: 114_000, p50Seconds: 2.1, costCents: 91 },
    ]);
    expect(totals).toEqual({ calls: 374, tokens: 1_570_000, costCents: 599 });
    expect(formatCentsUsd(totals.costCents)).toBe("$5.99");
    expect(formatTokensCompact(totals.tokens)).toBe("1.57M");
  });

  it("empty ledger totals to exact zeros", () => {
    expect(ledgerTotals([])).toEqual({ calls: 0, tokens: 0, costCents: 0 });
  });
});

describe("formatDurationMin boundaries", () => {
  it.each<[number, string]>([
    [0, "0 min"],
    [59, "59 min"],
    [60, "1 h"],
    [61, "1 h 1 min"],
    [120, "2 h"],
    [130, "2 h 10 min"],
  ])("formatDurationMin(%d) === %s", (input, expected) => {
    expect(formatDurationMin(input)).toBe(expected);
  });
});

describe("day + relative labels", () => {
  const noon = new Date(2026, 6, 6, 12, 0, 0).getTime(); // local Mon Jul 6 2026

  it("labels today / yesterday / older / future correctly at day boundaries", () => {
    expect(formatDayLabel(new Date(2026, 6, 6, 0, 0, 1).toISOString(), noon)).toBe("Today");
    expect(formatDayLabel(new Date(2026, 6, 5, 23, 59, 59).toISOString(), noon)).toBe("Yesterday");
    expect(formatDayLabel(new Date(2026, 6, 7, 9, 0, 0).toISOString(), noon)).toBe("Today"); // future
    expect(formatDayLabel("not a date", noon)).toBe("Unknown day");
  });

  it("formatStartsIn: null for the past, exact minutes for the future", () => {
    expect(formatStartsIn(new Date(noon - 1).toISOString(), noon)).toBeNull();
    expect(formatStartsIn(new Date(noon + 40 * 60_000).toISOString(), noon)).toBe("in 40 min");
    expect(formatStartsIn(new Date(noon + 125 * 60_000).toISOString(), noon)).toBe("in 2 h 5 min");
    expect(formatStartsIn("garbage", noon)).toBeNull();
  });
});
