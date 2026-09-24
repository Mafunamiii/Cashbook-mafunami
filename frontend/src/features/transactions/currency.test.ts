import { describe, expect, it } from "vitest";

import { initialForm } from "./AddTransaction";
import { currencyByCode, formatCurrency, minorUnitsToDisplay } from "./currency";

describe("transaction currencies", () => {
  it("defaults a new transaction to the supplied account currency", () => {
    expect(initialForm("AED").currency_code).toBe("AED");
  });

  it("provides labels and formatting for the supported choices", () => {
    expect(minorUnitsToDisplay(1_234, 2)).toBe("12.34");
    expect(minorUnitsToDisplay(1_234, 0)).toBe("1234");
    expect(minorUnitsToDisplay(12_345, 3)).toBe("12.345");
    expect(formatCurrency(10_000, "AED", 2)).toContain("100.00");
    expect(formatCurrency(1_234, "JPY", 0)).toContain("1,234");
    expect(formatCurrency(1_234, "USD", 2)).toContain("12.34");
    expect(formatCurrency(1_234, "KWD", 3)).toContain("1.234");
  });

  it("keeps persisted values exponent-aware when the catalog is unavailable", () => {
    expect(currencyByCode([], "JPY").minor_unit).toBe(0);
    expect(currencyByCode([], "KWD").minor_unit).toBe(3);
  });
});
