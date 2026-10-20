import type { CategoryType } from "../categories/categoryModel";
import type { CurrencyCode } from "./currency";

export type Transaction = {
  id: string;
  name: string;
  transaction_type: CategoryType;
  category_id: string;
  category_name: string;
  category_color: string;
  amount_minor: number;
  currency_code: CurrencyCode;
  base_amount_minor: number;
  base_currency_code: CurrencyCode;
  exchange_rate: string;
  exchange_rate_date: string;
  exchange_rate_source: string;
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

export function majorAmount(amountMinor: number, minorUnit = 2): string {
  const negative = amountMinor < 0;
  const absolute = Math.abs(amountMinor);
  const scale = 10 ** minorUnit;
  const whole = Math.floor(absolute / scale);
  const fraction = minorUnit
    ? String(absolute % scale).padStart(minorUnit, "0")
    : "";
  return `${negative ? "-" : ""}${whole}${minorUnit ? `.${fraction}` : ""}`;
}

export function toMinorUnits(value: string, minorUnit = 2): number | null {
  const normalized = value.trim();
  const match = normalized.match(/^(\d+)(?:\.(\d+))?$/);
  if (!match || (match[2]?.length ?? 0) > minorUnit) return null;
  const whole = BigInt(match[1]);
  const fractional = (match[2] ?? "").padEnd(minorUnit, "0");
  const amountMinor =
    whole * 10n ** BigInt(minorUnit) + BigInt(fractional || "0");
  return amountMinor > 0n && amountMinor <= BigInt(Number.MAX_SAFE_INTEGER)
    ? Number(amountMinor)
    : null;
}
