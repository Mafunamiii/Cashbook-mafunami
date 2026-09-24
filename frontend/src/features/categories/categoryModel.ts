export type CategoryType = "inflow" | "outflow";

export type Category = {
  id: string;
  name: string;
  color: string;
  icon: string | null;
  transaction_type: CategoryType;
  archived_at: string | null;
};

const HEX_COLOR_PATTERN = /^#[0-9a-f]{6}$/i;

export function normalizeCategoryColor(value: string): string | null {
  const normalized = value.trim().toLowerCase();
  return HEX_COLOR_PATTERN.test(normalized) ? normalized : null;
}

export function isValidCategoryColor(value: string): boolean {
  return normalizeCategoryColor(value) !== null;
}

export function categoryTypeLabel(type: CategoryType): string {
  return type === "inflow" ? "Inflow" : "Outflow";
}
