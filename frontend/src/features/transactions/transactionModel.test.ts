import { describe, expect, it, vi } from "vitest";

import { localToday } from "./transactionModel";

describe("localToday", () => {
  it("returns an ISO calendar day in the browser's local timezone", () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-08-01T00:30:00+08:00"));
    expect(localToday()).toMatch(/^2026-\d{2}-\d{2}$/);
    vi.useRealTimers();
  });
});
