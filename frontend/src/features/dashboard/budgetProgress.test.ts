import { describe, expect, it } from "vitest";

import { budgetProgress } from "./budgetProgress";

function progressAt(usagePercent: string, remainingMinor = 1) {
  return budgetProgress({
    is_overspent: false,
    remaining_minor: remainingMinor,
    usage_percent: usagePercent,
  });
}

describe("budgetProgress", () => {
  it("uses green below 75 percent", () => {
    expect(progressAt("74.99").tone).toBe("safe");
  });

  it("uses yellow from 75 through 89 percent", () => {
    expect(progressAt("75").tone).toBe("warning");
    expect(progressAt("89.99").tone).toBe("warning");
  });

  it("uses red at 90 percent and when overspent", () => {
    expect(progressAt("90").tone).toBe("danger");
    expect(progressAt("105", -500).tone).toBe("danger");
  });

  it("clamps the rendered fill between zero and 100 percent", () => {
    expect(progressAt("-10").percentage).toBe(0);
    expect(progressAt("125", -1).percentage).toBe(100);
  });

  it("stays neutral until a budget is set", () => {
    expect(
      budgetProgress({
        is_overspent: false,
        remaining_minor: null,
        usage_percent: null,
      }),
    ).toEqual({ percentage: 0, tone: "neutral", label: "Budget not set" });
  });
});
