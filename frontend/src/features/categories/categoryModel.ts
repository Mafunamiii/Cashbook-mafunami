export type CategoryType = "inflow" | "outflow";

export type Category = {
  id: string;
  name: string;
  color: string;
  icon: string | null;
  transaction_type: CategoryType;
  archived_at: string | null;
};

export const CURATED_COLORS = [
  "#22c55e",
  "#14b8a6",
  "#8b5cf6",
  "#38bdf8",
  "#f97316",
  "#ef4444",
  "#eab308",
  "#6366f1",
  "#ec4899",
  "#a855f7",
  "#06b6d4",
  "#94a3b8",
] as const;

export function categoryTypeLabel(type: CategoryType): string {
  return type === "inflow" ? "Inflow" : "Outflow";
}
