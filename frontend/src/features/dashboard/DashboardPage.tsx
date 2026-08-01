import { useCallback, useEffect, useMemo, useState } from "react";
import { Cell, Pie, PieChart, ResponsiveContainer, Tooltip } from "recharts";

import { apiRequest } from "../../api";
import { AddTransaction } from "../transactions/AddTransaction";

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
  transaction_date: string;
};

type Dashboard = Allocation & {
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

function localToday() {
  const now = new Date();
  const offset = now.getTimezoneOffset() * 60_000;
  return new Date(now.getTime() - offset).toISOString().slice(0, 10);
}

function money(value: number | null) {
  if (value === null) return "Not set";
  return new Intl.NumberFormat(undefined, {
    style: "currency",
    currency: "PHP",
    maximumFractionDigits: 2,
  }).format(value / 100);
}

function signedMoney(value: number) {
  return `${value > 0 ? "+" : value < 0 ? "−" : ""}${money(Math.abs(value))}`;
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

function progressClass(summary: Allocation) {
  if (summary.remaining_minor === null) return "neutral";
  if (summary.remaining_minor < 0) return "danger";
  const percentage = Number(summary.usage_percent ?? 0);
  if (percentage >= 90) return "danger";
  if (percentage >= 75) return "warning";
  if (percentage >= 50) return "caution";
  return "safe";
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
  const [error, setError] = useState<string | null>(null);

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

  const chartData = useMemo(
    () =>
      (dashboard?.category_spending ?? []).map((item) => ({
        ...item,
        value: item.used_minor,
        percentage:
          dashboard && dashboard.total_outflow_minor > 0
            ? (item.used_minor / dashboard.total_outflow_minor) * 100
            : 0,
      })),
    [dashboard],
  );
  const activeCategory = chartData.find(
    (item) => item.category_id === selectedCategory,
  );

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
      {dashboard && (
        <>
          <section
            className="budget-hero card"
            aria-labelledby="remaining-budget"
          >
            <p className="eyebrow">Remaining budget</p>
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
              className={`depletion-track ${dashboard ? progressClass(dashboard) : "neutral"}`}
            >
              <span
                style={{
                  width: `${Math.min(100, Number(dashboard?.usage_percent ?? 0))}%`,
                }}
              />
            </div>
            <p className="budget-used-copy">
              {dashboard
                ? `${money(dashboard.used_minor)} used`
                : "Loading summary…"}
            </p>
          </section>

          <section className="summary-grid" aria-label="Financial summary">
            <SummaryCard
              label="Inflow"
              value={dashboard ? money(dashboard.total_inflow_minor) : "—"}
              tone="inflow"
            />
            <SummaryCard
              label="Outflow"
              value={dashboard ? money(dashboard.total_outflow_minor) : "—"}
              tone="outflow"
            />
            <SummaryCard
              label="Profit / loss"
              value={
                dashboard ? signedMoney(dashboard.net_profit_loss_minor) : "—"
              }
              tone={
                dashboard && dashboard.net_profit_loss_minor < 0
                  ? "outflow"
                  : "inflow"
              }
            />
            <SummaryCard
              label="Budget used"
              value={
                dashboard?.usage_percent
                  ? `${Number(dashboard.usage_percent).toFixed(0)}%`
                  : "—"
              }
              tone="neutral"
            />
          </section>

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
                        <Tooltip content={<ChartTooltip />} />
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
                        {money(item.amount_minor)}
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
                      <span>
                        <i
                          className="category-dot"
                          style={{ background: item.category_color }}
                        />
                        {item.category_name}
                      </span>
                      <strong>
                        {money(item.used_minor)} / {money(item.amount_minor)}
                      </strong>
                    </p>
                    <div className={`depletion-track ${progressClass(item)}`}>
                      <span
                        style={{
                          width: `${Math.min(100, Number(item.usage_percent ?? 0))}%`,
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
}: {
  active?: boolean;
  payload?: {
    payload: { category_name: string; used_minor: number; percentage: number };
  }[];
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
