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
