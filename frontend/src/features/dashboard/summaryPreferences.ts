export type SummaryKey = "inflow" | "outflow" | "profitLoss" | "budgetUsed";

export type SummarySelection = Record<SummaryKey, boolean>;

export type DashboardSummaryPreference = {
  inflow: boolean;
  outflow: boolean;
  profit_loss: boolean;
  budget_used: boolean;
};

export const defaultSummarySelection: SummarySelection = {
  inflow: true,
  outflow: true,
  profitLoss: true,
  budgetUsed: true,
};

export function selectionFromApi(
  preference: DashboardSummaryPreference,
): SummarySelection {
  return {
    inflow: preference.inflow,
    outflow: preference.outflow,
    profitLoss: preference.profit_loss,
    budgetUsed: preference.budget_used,
  };
}

export function selectionToApi(
  selection: SummarySelection,
): DashboardSummaryPreference {
  return {
    inflow: selection.inflow,
    outflow: selection.outflow,
    profit_loss: selection.profitLoss,
    budget_used: selection.budgetUsed,
  };
}

export function selectionAfterFailedSave(
  pending: SummarySelection,
  confirmed: SummarySelection,
  attempts: number,
) {
  return attempts >= 3 ? confirmed : pending;
}
