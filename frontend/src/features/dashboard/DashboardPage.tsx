import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Cell, Pie, PieChart, ResponsiveContainer, Tooltip } from "recharts";

import { apiRequest } from "../../api";
import { AddTransaction } from "../transactions/AddTransaction";
import {
  currencyByCode,
  formatCurrency,
  minorUnitsToDisplay,
  useCurrencies,
} from "../transactions/currency";
import {
  budgetProgress,
  categoryBudgetRemainingCopy,
  categoryBudgetUsageCopy,
} from "./budgetProgress";
import {
  defaultSummarySelection,
  selectionAfterFailedSave,
  selectionFromApi,
  selectionToApi,
} from "./summaryPreferences";
import type {
  DashboardSummaryPreference,
  SummaryKey,
  SummarySelection,
} from "./summaryPreferences";

type ReportingMode = "calendar_month" | "payday";

type Allocation = {
  amount_minor: number | null;
  used_minor: number;
  remaining_minor: number | null;
  usage_percent: string | null;
  is_overspent: boolean;
};

type Category = Allocation & {
  category_id: string;
  category_name: string;
  category_color: string;
};

type RecentTransaction = {
  id: string;
  name: string;
  transaction_type: "inflow" | "outflow";
  category_name: string;
  category_color: string;
  amount_minor: number;
  currency_code: string;
  base_amount_minor: number;
  base_currency_code: string;
  transaction_date: string;
};

type Dashboard = Allocation & {
  base_currency_code: string;
  period_start: string;
  period_end: string;
  period_mode: ReportingMode;
  period_label: string;
  total_inflow_minor: number;
  total_outflow_minor: number;
  net_profit_loss_minor: number;
  payday_is_configured: boolean;
  payday_is_enabled: boolean;
  category_spending: Category[];
  category_budgets: Category[];
  recent_transactions: RecentTransaction[];
};

type Settings = {
  dashboard_summary: DashboardSummaryPreference;
  payday_setup_notice_dismissed: boolean;
};

const summaryOptions: { key: SummaryKey; label: string }[] = [
  { key: "inflow", label: "Inflow" },
  { key: "outflow", label: "Outflow" },
  { key: "profitLoss", label: "Profit / loss" },
  { key: "budgetUsed", label: "Budget used" },
];

function localToday() {
  const now = new Date();
  const offset = now.getTimezoneOffset() * 60_000;
  return new Date(now.getTime() - offset).toISOString().slice(0, 10);
}

function previousDay(value: string) {
  const date = new Date(`${value}T12:00:00`);
  date.setDate(date.getDate() - 1);
  return date.toISOString().slice(0, 10);
}

function nextDay(value: string) {
  const date = new Date(`${value}T12:00:00`);
  date.setDate(date.getDate() + 1);
  return date.toISOString().slice(0, 10);
}

export function DashboardPage({
  displayName,
  onBudgetSettings,
  onViewRecords,
}: {
  displayName: string;
  onBudgetSettings?: () => void;
  onViewRecords?: () => void;
}) {
  const [anchorDate, setAnchorDate] = useState(localToday);
  const [mode, setMode] = useState<ReportingMode>("calendar_month");
  const [dashboard, setDashboard] = useState<Dashboard | null>(null);
  const [selectedCategory, setSelectedCategory] = useState<string | null>(null);
  const [isCycleOpen, setIsCycleOpen] = useState(false);
  const [visibleSummaries, setVisibleSummaries] = useState<SummarySelection>(
    defaultSummarySelection,
  );
  const [confirmedSummaries, setConfirmedSummaries] =
    useState<SummarySelection>(defaultSummarySelection);
  const [preferenceStatus, setPreferenceStatus] = useState<
    "loading" | "idle" | "saving" | "saved" | "error"
  >("loading");
  const [failedSave, setFailedSave] = useState<{
    selection: SummarySelection;
    attempts: number;
  } | null>(null);
  const [paydayNoticeDismissed, setPaydayNoticeDismissed] = useState(false);
  const [paydayNoticeReady, setPaydayNoticeReady] = useState(false);
  const [paydayNoticeError, setPaydayNoticeError] = useState(false);
  const saveVersion = useRef(0);
  const customizerRef = useRef<HTMLDetailsElement>(null);
  const [error, setError] = useState<string | null>(null);
  const { currencies } = useCurrencies();
  const baseCurrency = currencyByCode(
    currencies,
    dashboard?.base_currency_code ?? "PHP",
  );
  const money = useCallback(
    (value: number | null) =>
      value === null
        ? "Not set"
        : formatCurrency(value, baseCurrency.code, baseCurrency.minor_unit),
    [baseCurrency.code, baseCurrency.minor_unit],
  );
  const signedMoney = (value: number) =>
    `${value > 0 ? "+" : value < 0 ? "−" : ""}${money(Math.abs(value))}`;

  const load = useCallback(async () => {
    const params = new URLSearchParams({
      anchor_date: anchorDate,
      period_mode: mode,
    });
    try {
      const payload = await apiRequest<Dashboard>(`/dashboard?${params}`);
      setDashboard(payload);
      setMode(payload.period_mode);
      setError(null);
    } catch (requestError) {
      setError(
        requestError instanceof Error
          ? requestError.message
          : "Unable to load the dashboard.",
      );
    }
  }, [anchorDate, mode]);

  useEffect(() => {
    const timer = window.setTimeout(() => void load(), 0);
    return () => window.clearTimeout(timer);
  }, [load]);

  useEffect(() => {
    let active = true;
    void apiRequest<Settings>("/settings")
      .then((settings) => {
        if (!active) return;
        const selection = selectionFromApi(settings.dashboard_summary);
        setVisibleSummaries(selection);
        setConfirmedSummaries(selection);
        setPaydayNoticeDismissed(settings.payday_setup_notice_dismissed);
        setPaydayNoticeReady(true);
        setPreferenceStatus("idle");
      })
      .catch(() => {
        if (!active) return;
        setPaydayNoticeReady(true);
        setPreferenceStatus("error");
      });
    return () => {
      active = false;
    };
  }, []);

  useEffect(() => {
    function closeCustomizer(event: MouseEvent | KeyboardEvent) {
      if (
        event instanceof KeyboardEvent
          ? event.key === "Escape"
          : !customizerRef.current?.contains(event.target as Node)
      ) {
        customizerRef.current?.removeAttribute("open");
      }
    }
    document.addEventListener("mousedown", closeCustomizer);
    document.addEventListener("keydown", closeCustomizer);
    return () => {
      document.removeEventListener("mousedown", closeCustomizer);
      document.removeEventListener("keydown", closeCustomizer);
    };
  }, []);

  const saveSummaryPreferences = useCallback(
    async (selection: SummarySelection, attempts: number) => {
      const version = ++saveVersion.current;
      setPreferenceStatus("saving");
      setFailedSave(null);
      try {
        const settings = await apiRequest<Settings>("/settings", {
          method: "PATCH",
          body: JSON.stringify({
            dashboard_summary: selectionToApi(selection),
          }),
        });
        if (version !== saveVersion.current) return;
        const confirmed = selectionFromApi(settings.dashboard_summary);
        setVisibleSummaries(confirmed);
        setConfirmedSummaries(confirmed);
        setPreferenceStatus("saved");
      } catch {
        if (version !== saveVersion.current) return;
        const retainedSelection = selectionAfterFailedSave(
          selection,
          confirmedSummaries,
          attempts,
        );
        setVisibleSummaries(retainedSelection);
        if (attempts >= 3) {
          setFailedSave(null);
        } else {
          setFailedSave({ selection, attempts });
        }
        setPreferenceStatus("error");
      }
    },
    [confirmedSummaries],
  );

  function updateSummary(key: SummaryKey, checked: boolean) {
    const selection = { ...visibleSummaries, [key]: checked };
    setVisibleSummaries(selection);
    void saveSummaryPreferences(selection, 1);
  }

  async function dismissPaydayNotice() {
    setPaydayNoticeDismissed(true);
    setPaydayNoticeError(false);
    try {
      await apiRequest<Settings>("/settings", {
        method: "PATCH",
        body: JSON.stringify({ payday_setup_notice_dismissed: true }),
      });
    } catch {
      setPaydayNoticeDismissed(false);
      setPaydayNoticeError(true);
    }
  }

  const chartData = useMemo(
    () =>
      (dashboard?.category_spending ?? []).map((item) => ({
        ...item,
        // Recharts requires Number display values; accounting totals remain
        // integer base-currency minor units everywhere else.
        value: Number(
          minorUnitsToDisplay(item.used_minor, baseCurrency.minor_unit),
        ),
        percentage:
          dashboard && dashboard.total_outflow_minor > 0
            ? (item.used_minor / dashboard.total_outflow_minor) * 100
            : 0,
      })),
    [baseCurrency.minor_unit, dashboard],
  );
  const activeCategory = chartData.find(
    (item) => item.category_id === selectedCategory,
  );
  const overallBudgetProgress = dashboard
    ? budgetProgress(dashboard)
    : { percentage: 0, tone: "neutral" as const, label: "Loading budget" };

  return (
    <main className="app-shell dashboard-shell">
      <header className="dashboard-heading">
        <div>
          <p className="eyebrow">NamiCash by Mafunami</p>
          <h1>Welcome {displayName}</h1>
        </div>
        <div className="dashboard-actions">
          <button
            aria-controls="dashboard-cycle-control"
            aria-expanded={isCycleOpen}
            className="button secondary cycle-toggle"
            onClick={() => setIsCycleOpen((open) => !open)}
            type="button"
          >
            Cycle
            <span aria-hidden="true">{isCycleOpen ? "−" : "+"}</span>
          </button>
          <AddTransaction onSaved={load} />
        </div>
      </header>

      <section
        className={`period-control card ${isCycleOpen ? "mobile-expanded" : ""}`}
        id="dashboard-cycle-control"
        aria-label="Selected reporting period"
      >
        <div className="period-mode" role="group" aria-label="Period type">
          <button
            className={mode === "calendar_month" ? "active" : ""}
            onClick={() => setMode("calendar_month")}
            type="button"
          >
            Month
          </button>
          {dashboard?.payday_is_enabled && (
            <button
              className={mode === "payday" ? "active" : ""}
              onClick={() => setMode("payday")}
              type="button"
            >
              Payday
            </button>
          )}
        </div>
        <div className="period-picker">
          <button
            aria-label="Previous day"
            onClick={() => setAnchorDate(previousDay(anchorDate))}
            type="button"
          >
            ‹
          </button>
          <label>
            <span className="sr-only">Anchor date</span>
            <input
              type="date"
              value={anchorDate}
              onChange={(event) => setAnchorDate(event.target.value)}
            />
          </label>
          <button
            aria-label="Next day"
            onClick={() => setAnchorDate(nextDay(anchorDate))}
            type="button"
          >
            ›
          </button>
        </div>
        <strong>{dashboard?.period_label ?? "Loading period…"}</strong>
      </section>

      {error && (
        <section className="card dashboard-error" role="alert">
          <h2>Dashboard unavailable</h2>
          <p>{error}</p>
          <button className="button" type="button" onClick={() => void load()}>
            Try again
          </button>
        </section>
      )}
      {!dashboard && !error && (
        <div
          aria-label="Loading dashboard summary"
          aria-live="polite"
          className="skeleton dashboard-skeleton"
          role="status"
        >
          <span className="sr-only">Loading dashboard summary…</span>
        </div>
      )}
      {dashboard &&
        !dashboard.payday_is_configured &&
        mode === "calendar_month" &&
        paydayNoticeReady &&
        !paydayNoticeDismissed && (
          <aside className="payday-setup-notice notice" role="note">
            <span>
              Set payday cutoffs in Budget settings to view payday segments.
            </span>
            <button
              aria-label="Dismiss payday setup reminder"
              className="notice-dismiss"
              onClick={() => void dismissPaydayNotice()}
              type="button"
            >
              ×
            </button>
          </aside>
        )}
      {paydayNoticeError && (
        <p className="notice-save-error" role="alert">
          Could not save the dismissal. Please try again.
        </p>
      )}
      {dashboard && (
        <>
          <section
            className="budget-hero card"
            aria-labelledby="remaining-budget"
          >
            <div className="budget-hero-heading">
              <p className="eyebrow">Remaining budget</p>
              <div className="summary-customizer">
                <details ref={customizerRef}>
                  <summary>
                    <span className="customize-label-full">
                      Customize dashboard
                    </span>
                    <span className="customize-label-compact">Customize</span>
                  </summary>
                  <fieldset>
                    <legend className="sr-only">Visible summary cards</legend>
                    {summaryOptions.map((option) => (
                      <label key={option.key}>
                        <input
                          checked={visibleSummaries[option.key]}
                          disabled={
                            preferenceStatus === "loading" ||
                            preferenceStatus === "saving"
                          }
                          onChange={(event) =>
                            updateSummary(option.key, event.target.checked)
                          }
                          type="checkbox"
                        />
                        {option.label}
                      </label>
                    ))}
                    <p className="preference-status" role="status">
                      {preferenceStatus === "loading" && "Loading preferences…"}
                      {preferenceStatus === "saving" && "Saving…"}
                      {preferenceStatus === "saved" && "Saved"}
                      {preferenceStatus === "error" && failedSave && (
                        <>
                          Could not save. Selection retained.{" "}
                          <button
                            onClick={() =>
                              void saveSummaryPreferences(
                                failedSave.selection,
                                failedSave.attempts + 1,
                              )
                            }
                            type="button"
                          >
                            Retry ({3 - failedSave.attempts} left)
                          </button>
                        </>
                      )}
                      {preferenceStatus === "error" &&
                        !failedSave &&
                        "Preferences unavailable; showing the last confirmed selection."}
                    </p>
                  </fieldset>
                </details>
              </div>
            </div>
            <h2 id="remaining-budget">
              {dashboard ? money(dashboard.remaining_minor) : "—"}
            </h2>
            <p>
              {dashboard.amount_minor === null
                ? "Add your first monthly budget to start tracking progress."
                : `of ${money(dashboard?.amount_minor ?? null)} total budget`}
            </p>
            {dashboard.amount_minor === null && (
              <button
                className="button budget-cta"
                type="button"
                onClick={onBudgetSettings}
              >
                Set monthly budget
              </button>
            )}
            <div
              aria-label={overallBudgetProgress.label}
              aria-valuemax={100}
              aria-valuemin={0}
              aria-valuenow={
                dashboard.amount_minor === null
                  ? undefined
                  : overallBudgetProgress.percentage
              }
              className={`depletion-track ${overallBudgetProgress.tone}`}
              role="progressbar"
            >
              <span
                style={{
                  width: `${overallBudgetProgress.percentage}%`,
                }}
              />
            </div>
            <p className="budget-used-copy">
              {`${money(dashboard.used_minor)} used · ${overallBudgetProgress.label}`}
            </p>
          </section>

          {Object.values(visibleSummaries).some(Boolean) && (
            <section className="summary-grid" aria-label="Financial summary">
              {visibleSummaries.inflow && (
                <SummaryCard
                  label="Inflow"
                  value={money(dashboard.total_inflow_minor)}
                  tone="inflow"
                />
              )}
              {visibleSummaries.outflow && (
                <SummaryCard
                  label="Outflow"
                  value={money(dashboard.total_outflow_minor)}
                  tone="outflow"
                />
              )}
              {visibleSummaries.profitLoss && (
                <SummaryCard
                  label="Profit / loss"
                  value={signedMoney(dashboard.net_profit_loss_minor)}
                  tone={
                    dashboard.net_profit_loss_minor < 0 ? "outflow" : "inflow"
                  }
                />
              )}
              {visibleSummaries.budgetUsed && (
                <SummaryCard
                  label="Budget used"
                  value={
                    dashboard.usage_percent
                      ? `${Number(dashboard.usage_percent).toFixed(0)}%`
                      : "—"
                  }
                  tone="neutral"
                />
              )}
            </section>
          )}

          <section className="dashboard-grid">
            <section
              className="card dashboard-panel spending-panel"
              aria-labelledby="spending-heading"
            >
              <div className="panel-heading">
                <div>
                  <p className="eyebrow">Outflow mix</p>
                  <h2 id="spending-heading">Spending by category</h2>
                </div>
              </div>
              {chartData.length ? (
                <>
                  <div className="chart-wrap" aria-hidden="true">
                    <ResponsiveContainer height="100%" width="100%">
                      <PieChart>
                        <Pie
                          data={chartData}
                          dataKey="value"
                          innerRadius="62%"
                          outerRadius="88%"
                          paddingAngle={3}
                          onClick={(_, index) =>
                            setSelectedCategory(
                              chartData[index]?.category_id ?? null,
                            )
                          }
                        >
                          {chartData.map((entry) => (
                            <Cell
                              fill={entry.category_color}
                              key={entry.category_id}
                            />
                          ))}
                        </Pie>
                        <Tooltip content={<ChartTooltip money={money} />} />
                      </PieChart>
                    </ResponsiveContainer>
                  </div>
                  <p className="chart-selected" aria-live="polite">
                    {activeCategory
                      ? `${activeCategory.category_name}: ${money(activeCategory.used_minor)} (${activeCategory.percentage.toFixed(1)}%)`
                      : "Hover or tap a segment for details."}
                  </p>
                  <ul
                    className="chart-summary"
                    aria-label="Outflow category summary"
                  >
                    {chartData.map((item) => (
                      <li key={item.category_id}>
                        <button
                          aria-pressed={item.category_id === selectedCategory}
                          onClick={() => setSelectedCategory(item.category_id)}
                          type="button"
                        >
                          <span
                            className="category-dot"
                            style={{ background: item.category_color }}
                          />
                          <span>{item.category_name}</span>
                          <strong>{money(item.used_minor)}</strong>
                          <small>{item.percentage.toFixed(1)}%</small>
                        </button>
                      </li>
                    ))}
                  </ul>
                </>
              ) : (
                <p className="empty-state">
                  No outflow transactions in this period yet.
                </p>
              )}
            </section>

            <section
              className="card dashboard-panel recent-panel"
              aria-labelledby="recent-heading"
            >
              <div className="panel-heading">
                <div>
                  <p className="eyebrow">Recent activity</p>
                  <h2 id="recent-heading">Latest transactions</h2>
                </div>
                <button
                  className="records-link"
                  onClick={onViewRecords}
                  type="button"
                >
                  View all records
                </button>
              </div>
              {dashboard?.recent_transactions.length ? (
                <ul className="recent-list">
                  {dashboard.recent_transactions.map((item) => (
                    <li key={item.id}>
                      <span
                        className="category-dot"
                        style={{ background: item.category_color }}
                      />
                      <div>
                        <strong>{item.name}</strong>
                        <small>
                          {item.category_name} · {item.transaction_date}
                        </small>
                      </div>
                      <b className={item.transaction_type}>
                        {item.transaction_type === "inflow" ? "+" : "−"}
                        {formatCurrency(
                          item.amount_minor,
                          item.currency_code,
                          currencyByCode(currencies, item.currency_code)
                            .minor_unit,
                        )}
                        {item.currency_code !== item.base_currency_code ? (
                          <small>
                            ≈ {formatCurrency(
                              item.base_amount_minor,
                              item.base_currency_code,
                              currencyByCode(currencies, item.base_currency_code)
                                .minor_unit,
                            )}
                          </small>
                        ) : null}
                      </b>
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="empty-state">
                  Your latest transactions will appear here.
                </p>
              )}
            </section>
          </section>

          {dashboard && dashboard.category_budgets.length > 0 && (
            <section
              className="card dashboard-panel category-budget-panel"
              aria-labelledby="category-budget-heading"
            >
              <div className="panel-heading">
                <div>
                  <p className="eyebrow">Optional allocations</p>
                  <h2 id="category-budget-heading">Category budgets</h2>
                </div>
              </div>
              <div className="category-progress-list">
                {dashboard.category_budgets.map((item) => (
                  <div key={item.category_id}>
                    <p>
                      <span className="category-budget-label">
                        <i
                          className="category-dot"
                          style={{ background: item.category_color }}
                        />
                        <span className="category-budget-name">
                          {item.category_name}
                        </span>
                        <small
                          className={`category-budget-remaining ${budgetProgress(item).tone}`}
                        >
                          {categoryBudgetRemainingCopy(
                            item.remaining_minor,
                            money,
                          )}
                        </small>
                      </span>
                      <strong className="category-budget-usage">
                        {categoryBudgetUsageCopy(
                          item.used_minor,
                          item.amount_minor,
                          money,
                        )}
                      </strong>
                    </p>
                    <div
                      aria-label={`${item.category_name}: ${budgetProgress(item).label}`}
                      aria-valuemax={100}
                      aria-valuemin={0}
                      aria-valuenow={budgetProgress(item).percentage}
                      className={`depletion-track ${budgetProgress(item).tone}`}
                      role="progressbar"
                    >
                      <span
                        style={{
                          width: `${budgetProgress(item).percentage}%`,
                        }}
                      />
                    </div>
                  </div>
                ))}
              </div>
            </section>
          )}
        </>
      )}
    </main>
  );
}

function SummaryCard({
  label,
  value,
  tone,
}: {
  label: string;
  value: string;
  tone: string;
}) {
  return (
    <article className={`card summary-card ${tone}`}>
      <p>{label}</p>
      <strong>{value}</strong>
    </article>
  );
}

function ChartTooltip({
  active,
  payload,
  money,
}: {
  active?: boolean;
  payload?: {
    payload: { category_name: string; used_minor: number; percentage: number };
  }[];
  money: (value: number | null) => string;
}) {
  if (!active || !payload?.[0]) return null;
  const item = payload[0].payload;
  return (
    <div className="chart-tooltip">
      <strong>{item.category_name}</strong>
      <span>
        {money(item.used_minor)} · {item.percentage.toFixed(1)}%
      </span>
    </div>
  );
}
