import type { CategoryType } from "../categories/categoryModel";

export type Transaction = {
  id: string;
  name: string;
  transaction_type: CategoryType;
  category_id: string;
  category_name: string;
  category_color: string;
  amount_minor: number;
  transaction_date: string;
  notes: string | null;
  created_at: string;
  updated_at: string;
};

export function localToday(): string {
  const today = new Date();
  const offset = today.getTimezoneOffset() * 60_000;
  return new Date(today.getTime() - offset).toISOString().slice(0, 10);
}

export function majorAmount(amountMinor: number): string {
  return (amountMinor / 100).toFixed(2);
}

export function toMinorUnits(value: string): number | null {
  const normalized = value.trim();
  if (!/^\d+(\.\d{1,2})?$/.test(normalized)) return null;
  const amountMinor = Math.round(Number(normalized) * 100);
  return Number.isSafeInteger(amountMinor) && amountMinor > 0
    ? amountMinor
    : null;
}
