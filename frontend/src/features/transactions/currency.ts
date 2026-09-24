import { useEffect, useState } from "react";

export type CurrencyCode = string;

export type Currency = {
  code: CurrencyCode;
  name: string;
  minor_unit: number;
};

const apiBaseUrl = import.meta.env.VITE_API_BASE_URL?.replace(/\/$/, "") ?? "";
let catalogPromise: Promise<Currency[]> | null = null;

export function loadCurrencies(): Promise<Currency[]> {
  if (!catalogPromise) {
    catalogPromise = fetch(`${apiBaseUrl}/api/v1/currencies`, {
      credentials: "include",
    }).then(async (response) => {
      if (!response.ok) throw new Error("Unable to load currency choices.");
      return (await response.json()) as Currency[];
    });
  }
  return catalogPromise;
}

export function useCurrencies() {
  const [currencies, setCurrencies] = useState<Currency[]>([]);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    let active = true;
    void loadCurrencies()
      .then((result) => active && setCurrencies(result))
      .catch((reason: unknown) => {
        if (active) setError(reason instanceof Error ? reason.message : "Unable to load currency choices.");
      });
    return () => {
      active = false;
    };
  }, []);
  return { currencies, error };
}

export function currencyByCode(currencies: Currency[], code: CurrencyCode): Currency {
  return currencies.find((currency) => currency.code === code) ?? {
    code,
    name: code,
    // A catalog outage must not make persisted JPY/KWD amounts display with
    // the wrong precision. Intl is only an offline display fallback; active
    // choices still come exclusively from the API catalog.
    minor_unit: intlMinorUnit(code),
  };
}

function intlMinorUnit(code: CurrencyCode): number {
  try {
    return new Intl.NumberFormat(undefined, {
      style: "currency",
      currency: code,
    }).resolvedOptions().maximumFractionDigits ?? 2;
  } catch {
    return 2;
  }
}

export function minorUnitsToDisplay(amountMinor: number | bigint, minorUnit: number): string {
  const amount = typeof amountMinor === "bigint" ? amountMinor : BigInt(amountMinor);
  const negative = amount < 0n;
  const absolute = negative ? -amount : amount;
  const scale = 10n ** BigInt(minorUnit);
  const whole = absolute / scale;
  const fraction = minorUnit ? (absolute % scale).toString().padStart(minorUnit, "0") : "";
  return `${negative ? "-" : ""}${whole}${minorUnit ? `.${fraction}` : ""}`;
}

export function formatCurrency(amountMinor: number | bigint, currency: CurrencyCode, minorUnit = 2) {
  const amount = typeof amountMinor === "bigint" ? amountMinor : BigInt(amountMinor);
  const negative = amount < 0n;
  const absolute = negative ? -amount : amount;
  const scale = 10n ** BigInt(minorUnit);
  const whole = absolute / scale;
  const fraction = minorUnit ? (absolute % scale).toString().padStart(minorUnit, "0") : "";
  const numberFormat = new Intl.NumberFormat(undefined, { useGrouping: true, maximumFractionDigits: 0 });
  const currencyFormat = new Intl.NumberFormat(undefined, {
    style: "currency",
    currency,
    minimumFractionDigits: minorUnit,
    maximumFractionDigits: minorUnit,
  });
  return currencyFormat.formatToParts(negative ? -0 : 0).map((part) => {
    if (part.type === "integer") return numberFormat.format(whole);
    if (part.type === "fraction") return fraction;
    return part.value;
  }).join("");
}
