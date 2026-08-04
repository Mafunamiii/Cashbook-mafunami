import { describe, expect, it } from "vitest";

import {
  defaultSummarySelection,
  selectionAfterFailedSave,
  selectionFromApi,
  selectionToApi,
} from "./summaryPreferences";

describe("dashboard summary preferences", () => {
  it("defaults every summary card to visible", () => {
    expect(Object.values(defaultSummarySelection)).toEqual([
      true,
      true,
      true,
      true,
    ]);
  });

  it("maps persisted API preferences in both directions", () => {
    const apiPreference = {
      inflow: false,
      outflow: true,
      profit_loss: false,
      budget_used: true,
    };
    expect(selectionToApi(selectionFromApi(apiPreference))).toEqual(
      apiPreference,
    );
  });

  it("retains pending changes before restoring confirmed state on attempt three", () => {
    const confirmed = defaultSummarySelection;
    const pending = { ...confirmed, inflow: false };

    expect(selectionAfterFailedSave(pending, confirmed, 1)).toBe(pending);
    expect(selectionAfterFailedSave(pending, confirmed, 2)).toBe(pending);
    expect(selectionAfterFailedSave(pending, confirmed, 3)).toBe(confirmed);
  });
});
