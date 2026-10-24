import { describe, expect, it } from "vitest";

import {
  categoryTypeLabel,
  isValidCategoryColor,
  normalizeCategoryColor,
} from "./categoryModel";
import { findCategoryIcon, searchCategoryIcons } from "./iconRegistry";

describe("category model", () => {
  it("labels both supported category types", () => {
    expect(categoryTypeLabel("inflow")).toBe("Inflow");
    expect(categoryTypeLabel("outflow")).toBe("Outflow");
  });

  it("normalizes valid six-digit hex colors", () => {
    expect(normalizeCategoryColor(" #06B6D4 ")).toBe("#06b6d4");
    expect(normalizeCategoryColor("#abcdef")).toBe("#abcdef");
  });

  it("rejects colors that are not six-digit hex values", () => {
    expect(isValidCategoryColor("#12345")).toBe(false);
    expect(isValidCategoryColor("#1234567")).toBe(false);
    expect(isValidCategoryColor("red")).toBe(false);
    expect(normalizeCategoryColor(" #12gg34 ")).toBeNull();
  });

  it("searches the curated icon registry by labels and keywords", () => {
    expect(searchCategoryIcons("restaurant").map((icon) => icon.key)).toContain(
      "utensils",
    );
    expect(
      searchCategoryIcons("money", "Finance").map((icon) => icon.key),
    ).toContain("coins");
    expect(searchCategoryIcons("money", "Health")).toHaveLength(0);
  });

  it("matches search words in any order with extra whitespace", () => {
    expect(
      searchCategoryIcons(" restaurant   food ").map((icon) => icon.key),
    ).toContain("utensils");
    expect(searchCategoryIcons("food restaurant", "Finance")).toHaveLength(0);
  });

  it("resolves Lucide keys while leaving legacy values to the fallback", () => {
    expect(findCategoryIcon("utensils")?.label).toBe("Utensils");
    expect(findCategoryIcon("🐾")).toBeNull();
    expect(findCategoryIcon(null)).toBeNull();
  });
});
