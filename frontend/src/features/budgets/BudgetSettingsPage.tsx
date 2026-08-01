import { useCallback, useEffect, useState } from "react";
import type { FormEvent } from "react";

type ReportingMode = "calendar_month" | "payday";

type Schedule = {
  id: string;
  first_day: number;
  second_day: number;
  effective_from: string;
  is_active: boolean;
};

type Allocation = {
  amount_minor: number | null;
  used_minor: number;
  remaining_minor: number | null;
  usage_percent: string | null;
  is_overspent: boolean;
};

type Cycle = Allocation & {
  month_start: string;
  month_end: string;
  total_inflow_minor: number;
  total_outflow_minor: number;
  net_profit_loss_minor: number;
  reporting_mode: ReportingMode;
  payday_schedule: Schedule | null;
  allowances_total_minor: number;
  allowances_match_budget: boolean | null;
  payday_allowances: (Allocation & {
    period_start: string;
    period_end: string;
  })[];
  category_budgets: (Allocation & {
    category_id: string;
    category_name: string;
    category_color: string;
  })[];
};

const apiBaseUrl = import.meta.env.VITE_API_BASE_URL?.replace(/\/$/, "") ?? "";

function csrfToken(): string | undefined {
  return document.cookie
    .split("; ")
    .find((value) => value.startsWith("cashbook_csrf="))
    ?.split("=")[1];
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const csrf = csrfToken();
  const response = await fetch(`${apiBaseUrl}/api/v1${path}`, {
    ...init,
    credentials: "include",
    headers: {
      "Content-Type": "application/json",
      ...(csrf ? { "X-CSRF-Token": decodeURIComponent(csrf) } : {}),
      ...init?.headers,
    },
  });
  if (!response.ok) {
    const body = (await response.json().catch(() => null)) as {
      detail?: string;
    } | null;
    throw new Error(body?.detail ?? "Unable to save budget settings.");
  }
  return response.json() as Promise<T>;
}

function thisMonth(): string {
  const now = new Date();
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}-01`;
}

function money(value: number | null): string {
  return value === null
    ? "Not set"
    : new Intl.NumberFormat(undefined, {
        style: "currency",
        currency: "PHP",
      }).format(value / 100);
}

export function BudgetSettingsPage() {
  const [monthStart, setMonthStart] = useState(thisMonth);
  const [cycle, setCycle] = useState<Cycle | null>(null);
  const [mode, setMode] = useState<ReportingMode>("calendar_month");
  const [amount, setAmount] = useState("");
  const [firstDay, setFirstDay] = useState("12");
  const [secondDay, setSecondDay] = useState("27");
  const [effectiveFrom, setEffectiveFrom] = useState("");
  const [notice, setNotice] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const [settings, currentCycle] = await Promise.all([
        request<{ reporting_mode: ReportingMode }>("/budget-settings"),
        request<Cycle>(`/budgets/${monthStart}`),
      ]);
      setMode(settings.reporting_mode);
      setCycle(currentCycle);
      setAmount(currentCycle.amount_minor?.toString() ?? "");
      setNotice(null);
    } catch (error) {
      setNotice(
        error instanceof Error
          ? error.message
          : "Unable to load budget settings.",
      );
    }
  }, [monthStart]);

  useEffect(() => {
    const timer = window.setTimeout(() => void load(), 0);
    return () => window.clearTimeout(timer);
  }, [load]);

  async function saveBudget(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const amountMinor = Number(amount);
    if (!Number.isSafeInteger(amountMinor) || amountMinor < 0) {
      setNotice("Enter a whole, non-negative amount in minor units.");
      return;
    }
    try {
      await request<Cycle>(`/budgets/${monthStart}`, {
        method: "PUT",
        body: JSON.stringify({ amount_minor: amountMinor }),
      });
      setNotice("Monthly budget saved.");
      await load();
    } catch (error) {
      setNotice(
        error instanceof Error
          ? error.message
          : "Unable to save the monthly budget.",
      );
    }
  }

  async function saveMode(nextMode: ReportingMode) {
    setMode(nextMode);
    try {
      await request("/budget-settings", {
        method: "PUT",
        body: JSON.stringify({ reporting_mode: nextMode }),
      });
      setNotice("Budget view preference saved.");
      await load();
    } catch (error) {
      setNotice(
        error instanceof Error ? error.message : "Unable to save preference.",
      );
    }
  }

  async function saveSchedule(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    try {
      await request<Schedule>("/budget-settings/payday-schedules", {
        method: "POST",
        body: JSON.stringify({
          first_day: Number(firstDay),
          second_day: Number(secondDay),
          effective_from: effectiveFrom,
        }),
      });
      setNotice(
        "A new payday schedule version was saved. Earlier cycles are unchanged.",
      );
      await load();
    } catch (error) {
      setNotice(
        error instanceof Error
          ? error.message
          : "Unable to save payday schedule.",
      );
    }
  }

  async function saveAllowance(periodStart: string, amountMinor: string) {
    try {
      await request(`/budgets/${monthStart}/allowances/${periodStart}`, {
        method: "PUT",
        body: JSON.stringify({ amount_minor: Number(amountMinor) }),
      });
      setNotice("Payday allowance saved.");
      await load();
    } catch (error) {
      setNotice(
        error instanceof Error ? error.message : "Unable to save allowance.",
      );
    }
  }

  async function saveCategoryBudget(categoryId: string, amountMinor: string) {
    try {
      await request(`/budgets/${monthStart}/categories/${categoryId}`, {
        method: "PUT",
        body: JSON.stringify({ amount_minor: Number(amountMinor) }),
      });
      setNotice("Category allocation saved.");
      await load();
    } catch (error) {
      setNotice(
        error instanceof Error
          ? error.message
          : "Unable to save category allocation.",
      );
    }
  }

  return (
    <main className="app-shell">
      <header className="page-heading">
        <div>
          <p className="eyebrow">Cashbook</p>
          <h1>Budget settings</h1>
          <p className="page-intro">
            Set the monthly spending envelope and its non-additive subdivisions.
          </p>
        </div>
      </header>
      {notice && (
        <p className="notice" role="status">
          {notice}
        </p>
      )}
      <section className="budget-layout" aria-label="Budget configuration">
        <form className="card category-form" onSubmit={saveBudget}>
          <div className="section-heading">
            <p className="eyebrow">Cycle</p>
            <h2>Monthly budget</h2>
          </div>
          <label>
            Month
            <input
              type="month"
              value={monthStart.slice(0, 7)}
              onChange={(event) => setMonthStart(`${event.target.value}-01`)}
            />
          </label>
          <label>
            Overall budget <span className="hint">minor units</span>
            <input
              inputMode="numeric"
              pattern="[0-9]*"
              value={amount}
              onChange={(event) => setAmount(event.target.value)}
              placeholder="e.g. 300000"
              required
            />
          </label>
          <button className="button" type="submit">
            Save monthly budget
          </button>
          {cycle && (
            <p className={cycle.is_overspent ? "budget-danger" : "hint"}>
              Remaining: {money(cycle.remaining_minor)} · Outflows:{" "}
              {money(cycle.total_outflow_minor)} · Inflows do not increase this
              budget.
            </p>
          )}
        </form>

        <section className="card budget-panel">
          <div className="section-heading">
            <p className="eyebrow">Reporting</p>
            <h2>Budget mode</h2>
          </div>
          <div className="transaction-type-switch">
            <button
              className={`type-option ${mode === "calendar_month" ? "selected" : ""}`}
              onClick={() => void saveMode("calendar_month")}
              type="button"
            >
              Calendar month
            </button>
            <button
              className={`type-option ${mode === "payday" ? "selected" : ""}`}
              onClick={() => void saveMode("payday")}
              type="button"
            >
              Payday segments
            </button>
          </div>
          <p className="hint">
            The overall budget remains a monthly envelope; payday allowances
            divide it without adding money.
          </p>
        </section>

        <form className="card category-form" onSubmit={saveSchedule}>
          <div className="section-heading">
            <p className="eyebrow">Payday</p>
            <h2>Cutoff schedule</h2>
          </div>
          <label>
            First cutoff
            <input
              min="1"
              max="31"
              type="number"
              value={firstDay}
              onChange={(event) => setFirstDay(event.target.value)}
              required
            />
          </label>
          <label>
            Second cutoff
            <input
              min="1"
              max="31"
              type="number"
              value={secondDay}
              onChange={(event) => setSecondDay(event.target.value)}
              required
            />
          </label>
          <label>
            Effective from <span className="hint">must be a period start</span>
            <input
              type="date"
              value={effectiveFrom}
              onChange={(event) => setEffectiveFrom(event.target.value)}
              required
            />
          </label>
          <button className="button" type="submit">
            Add schedule version
          </button>
          {cycle?.payday_schedule && (
            <p className="hint">
              Viewing {cycle.payday_schedule.first_day}th /{" "}
              {cycle.payday_schedule.second_day}th cutoffs, effective{" "}
              {cycle.payday_schedule.effective_from}.
            </p>
          )}
        </form>

        <section className="card budget-panel">
          <div className="section-heading">
            <p className="eyebrow">Allocations</p>
            <h2>Payday allowances</h2>
          </div>
          {cycle?.allowances_match_budget === false && (
            <p className="budget-warning" role="alert">
              Configured segment allowances (
              {money(cycle.allowances_total_minor)}) do not equal the overall
              budget.
            </p>
          )}
          {cycle?.payday_allowances.map((allowance) => (
            <form
              className="allocation-row"
              key={allowance.period_start}
              onSubmit={(event) => {
                event.preventDefault();
                void saveAllowance(
                  allowance.period_start,
                  new FormData(event.currentTarget).get("amount") as string,
                );
              }}
            >
              <span>
                {allowance.period_start} – {allowance.period_end}
                <small>Used {money(allowance.used_minor)}</small>
              </span>
              <input
                aria-label={`Allowance for ${allowance.period_start}`}
                defaultValue={allowance.amount_minor ?? ""}
                inputMode="numeric"
                name="amount"
                pattern="[0-9]*"
                required
              />
              <button className="text-button" type="submit">
                Save
              </button>
            </form>
          ))}
        </section>

        <section className="card budget-panel budget-panel-wide">
          <div className="section-heading">
            <p className="eyebrow">Sub-budgets</p>
            <h2>Category allocations</h2>
          </div>
          <p className="hint">
            These are outflow-only subdivisions of the monthly envelope.
            Overspending is shown but never blocked.
          </p>
          {cycle?.category_budgets.map((category) => (
            <form
              className="allocation-row"
              key={category.category_id}
              onSubmit={(event) => {
                event.preventDefault();
                void saveCategoryBudget(
                  category.category_id,
                  new FormData(event.currentTarget).get("amount") as string,
                );
              }}
            >
              <span>
                <i
                  className="budget-swatch"
                  style={{ backgroundColor: category.category_color }}
                />
                {category.category_name}
                <small className={category.is_overspent ? "budget-danger" : ""}>
                  Used {money(category.used_minor)} · Remaining{" "}
                  {money(category.remaining_minor)}
                </small>
              </span>
              <input
                aria-label={`${category.category_name} budget`}
                defaultValue={category.amount_minor ?? ""}
                inputMode="numeric"
                name="amount"
                pattern="[0-9]*"
                required
              />
              <button className="text-button" type="submit">
                Save
              </button>
            </form>
          ))}
        </section>
      </section>
    </main>
  );
}
