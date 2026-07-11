import { describe, expect, it } from "vitest";
import { formatHoldLabel } from "./format-hold-label";

describe("formatHoldLabel", () => {
  it("defaults to Hold F9 when keys are missing or empty", () => {
    expect(formatHoldLabel(undefined)).toBe("Hold F9");
    expect(formatHoldLabel(null)).toBe("Hold F9");
    expect(formatHoldLabel([])).toBe("Hold F9");
  });

  it("joins tokens with +", () => {
    expect(formatHoldLabel(["Ctrl", "Shift", "F8"])).toBe("Hold Ctrl+Shift+F8");
    expect(formatHoldLabel(["F9"])).toBe("Hold F9");
  });
});
