import { describe, expect, it, vi } from "vitest";

import { localToday, majorAmount, toMinorUnits } from "./transactionModel";

describe("localToday", () => {
  it("returns an ISO calendar day in the browser's local timezone", () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-08-01T00:30:00+08:00"));
    expect(localToday()).toMatch(/^2026-\d{2}-\d{2}$/);
    vi.useRealTimers();
  });
});

describe("transaction amounts", () => {
  it("converts user-entered peso values to integer centavos", () => {
    expect(toMinorUnits("200")).toBe(20_000);
    expect(toMinorUnits("200.50")).toBe(20_050);
    expect(toMinorUnits("0.01")).toBe(1);
  });

  it("rejects invalid or over-precise peso values", () => {
    expect(toMinorUnits("0")).toBeNull();
    expect(toMinorUnits("12.345")).toBeNull();
    expect(toMinorUnits("not money")).toBeNull();
  });

  it("converts stored centavos back to an editable peso value", () => {
    expect(majorAmount(20_000)).toBe("200.00");
  });
});
