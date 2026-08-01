import { describe, expect, it } from "vitest";

import { CURATED_COLORS, categoryTypeLabel } from "./categoryModel";

describe("category model", () => {
  it("labels both supported category types", () => {
    expect(categoryTypeLabel("inflow")).toBe("Inflow");
    expect(categoryTypeLabel("outflow")).toBe("Outflow");
  });

  it("uses a finite, hash-prefixed color palette", () => {
    expect(CURATED_COLORS).toHaveLength(12);
    expect(CURATED_COLORS.every((color) => color.startsWith("#"))).toBe(true);
  });
});
