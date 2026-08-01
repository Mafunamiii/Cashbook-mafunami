export type BudgetProgressInput = {
  remaining_minor: number | null;
  usage_percent: string | null;
  is_overspent: boolean;
};

export type BudgetProgressTone = "neutral" | "safe" | "warning" | "danger";

export function budgetProgress(summary: BudgetProgressInput) {
  if (summary.remaining_minor === null) {
    return {
      percentage: 0,
      tone: "neutral" as const,
      label: "Budget not set",
    };
  }

  const parsedPercentage = Number(summary.usage_percent ?? 0);
  const usagePercentage = Number.isFinite(parsedPercentage)
    ? parsedPercentage
    : 0;
  const percentage = Math.max(0, Math.min(100, usagePercentage));

  if (
    summary.is_overspent ||
    summary.remaining_minor < 0 ||
    usagePercentage >= 90
  ) {
    return { percentage, tone: "danger" as const, label: "Budget critical" };
  }

  if (usagePercentage >= 75) {
    return { percentage, tone: "warning" as const, label: "Budget warning" };
  }

  return { percentage, tone: "safe" as const, label: "Budget on track" };
}
