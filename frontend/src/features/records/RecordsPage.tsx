import { useCallback, useEffect, useMemo, useState } from "react";
import type { FormEvent } from "react";

import type { Category, CategoryType } from "../categories/categoryModel";
import type { Transaction } from "../transactions/transactionModel";
import { majorAmount, toMinorUnits } from "../transactions/transactionModel";
import { currencyByCode, formatCurrency, useCurrencies } from "../transactions/currency";
import type { Currency } from "../transactions/currency";
import type { CurrencyCode } from "../transactions/currency";

type Grouping = "calendar_month" | "payday";
type Sort = "newest" | "oldest";

type BudgetSettings = {
  reporting_mode: Grouping;
  payday_schedule: { id: string } | null;
};

type StatementTransaction = Transaction & {
  running_balance_minor: number;
  period_start: string;
  period_end: string;
};

type Page = {
  items: StatementTransaction[];
  page: number;
  page_size: number;
  total: number;
  total_pages: number;
  sort: Sort;
};

type Editor = {
  id: string;
  name: string;
  transaction_type: CategoryType;
  category_id: string;
  amount_minor: string;
  currency_code: CurrencyCode;
  base_amount_minor: number;
  base_currency_code: CurrencyCode;
  exchange_rate: string;
  exchange_rate_date: string;
  transaction_date: string;
  notes: string;
};

type PendingBulkDeletion = {
  ids: string[];
  timerId: number;
};

const apiBaseUrl = import.meta.env.VITE_API_BASE_URL?.replace(/\/$/, "") ?? "";

function csrfToken(): string | undefined {
  return document.cookie
    .split("; ")
    .find((value) => value.startsWith("cashbook_csrf="))
    ?.split("=")[1];
}

function signedAmount(item: StatementTransaction, minorUnit = 2) {
  return `${item.transaction_type === "inflow" ? "+" : "−"}${formatCurrency(
    item.amount_minor,
    item.currency_code, minorUnit,
  )}`;
}

function readableDate(value: string) {
  return new Intl.DateTimeFormat(undefined, {
    day: "numeric",
    month: "short",
    year: "numeric",
  }).format(new Date(`${value}T12:00:00`));
}

function periodLabel(item: StatementTransaction, grouping: Grouping) {
  if (grouping === "calendar_month") {
    return new Intl.DateTimeFormat(undefined, {
      month: "long",
      year: "numeric",
    }).format(new Date(`${item.period_start}T12:00:00`));
  }
  return `${readableDate(item.period_start)} – ${readableDate(item.period_end)}`;
}

function toEditor(item: StatementTransaction, minorUnit = 2): Editor {
  return {
    id: item.id,
    name: item.name,
    transaction_type: item.transaction_type,
    category_id: item.category_id,
    amount_minor: majorAmount(item.amount_minor, minorUnit),
    currency_code: item.currency_code,
    base_amount_minor: item.base_amount_minor,
    base_currency_code: item.base_currency_code,
    exchange_rate: item.exchange_rate,
    exchange_rate_date: item.exchange_rate_date,
    transaction_date: item.transaction_date,
    notes: item.notes ?? "",
  };
}

export function RecordsPage() {
  const { currencies, error: currenciesError } = useCurrencies();
  const [pageData, setPageData] = useState<Page | null>(null);
  const [categories, setCategories] = useState<Category[]>([]);
  const [page, setPage] = useState(1);
  const [sort, setSort] = useState<Sort>("newest");
  const [grouping, setGrouping] = useState<Grouping>("calendar_month");
  const [paydayAvailable, setPaydayAvailable] = useState(false);
  const [search, setSearch] = useState("");
  const [type, setType] = useState<"" | CategoryType>("");
  const [categoryId, setCategoryId] = useState("");
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [editor, setEditor] = useState<Editor | null>(null);
  const [isSaving, setIsSaving] = useState(false);
  const [isClearingAll, setIsClearingAll] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [isSelecting, setIsSelecting] = useState(false);
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [pendingBulkDeletion, setPendingBulkDeletion] =
    useState<PendingBulkDeletion | null>(null);
  const editorCurrency = currencyByCode(
    currencies,
    editor?.currency_code ?? "PHP",
  );
  const editorAmountStep = editorCurrency.minor_unit
    ? `0.${"0".repeat(editorCurrency.minor_unit - 1)}1`
    : "1";

  const load = useCallback(async () => {
    const params = new URLSearchParams({
      page: String(page),
      page_size: "50",
      sort,
      grouping,
    });
    if (search.trim()) params.set("search", search.trim());
    if (type) params.set("transaction_type", type);
    if (categoryId) params.set("category_id", categoryId);
    if (dateFrom) params.set("date_from", dateFrom);
    if (dateTo) params.set("date_to", dateTo);
    setIsLoading(true);
    try {
      const response = await fetch(
        `${apiBaseUrl}/api/v1/transactions?${params}`,
        {
          credentials: "include",
        },
      );
      if (!response.ok) {
        const body = (await response.json().catch(() => null)) as {
          detail?: string;
        } | null;
        throw new Error(body?.detail ?? "Unable to load records.");
      }
      setPageData((await response.json()) as Page);
      setError(null);
    } catch (requestError) {
      setError(
        requestError instanceof Error
          ? requestError.message
          : "Unable to load records.",
      );
    } finally {
      setIsLoading(false);
    }
  }, [categoryId, dateFrom, dateTo, grouping, page, search, sort, type]);

  useEffect(() => {
    const timer = window.setTimeout(() => void load(), 0);
    return () => window.clearTimeout(timer);
  }, [load]);

  useEffect(() => {
    let active = true;
    Promise.all([
      fetch(`${apiBaseUrl}/api/v1/categories?include_archived=true`, {
        credentials: "include",
      }),
      fetch(`${apiBaseUrl}/api/v1/budget-settings`, {
        credentials: "include",
      }),
    ])
      .then(async ([categoriesResponse, settingsResponse]) => {
        if (!categoriesResponse.ok)
          throw new Error("Unable to load categories.");
        const items = (await categoriesResponse.json()) as Category[];
        const settings = settingsResponse.ok
          ? ((await settingsResponse.json()) as BudgetSettings)
          : null;
        return { items, settings };
      })
      .then(({ items, settings }) => {
        if (active) {
          setCategories(items);
          setPaydayAvailable(
            settings?.reporting_mode === "payday" && !!settings.payday_schedule,
          );
        }
      })
      .catch(() => {
        // The statement remains usable without filter labels or editing.
      });
    return () => {
      active = false;
    };
  }, []);

  const groups = useMemo(() => {
    const result: { label: string; items: StatementTransaction[] }[] = [];
    const pendingIds = new Set(pendingBulkDeletion?.ids ?? []);
    for (const item of pageData?.items ?? []) {
      if (pendingIds.has(item.id)) continue;
      const label = periodLabel(item, grouping);
      const group = result.find((candidate) => candidate.label === label);
      if (group) group.items.push(item);
      else result.push({ label, items: [item] });
    }
    return result;
  }, [grouping, pageData, pendingBulkDeletion]);

  const visibleIds = useMemo(
    () => groups.flatMap((group) => group.items.map((item) => item.id)),
    [groups],
  );
  const allVisibleSelected =
    visibleIds.length > 0 && visibleIds.every((id) => selectedIds.has(id));

  function updateFilters(callback: () => void) {
    setPage(1);
    callback();
  }

  async function saveEdit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!editor) return;
    const amountMinor = toMinorUnits(
      editor.amount_minor,
      editorCurrency.minor_unit,
    );
    if (amountMinor === null) {
      setError(
        `Enter a valid amount with up to ${editorCurrency.minor_unit} decimal places.`,
      );
      return;
    }
    setIsSaving(true);
    const csrf = csrfToken();
    try {
      const response = await fetch(
        `${apiBaseUrl}/api/v1/transactions/${editor.id}`,
        {
          method: "PATCH",
          credentials: "include",
          headers: {
            "Content-Type": "application/json",
            ...(csrf ? { "X-CSRF-Token": decodeURIComponent(csrf) } : {}),
          },
          body: JSON.stringify({
            name: editor.name.trim(),
            transaction_type: editor.transaction_type,
            category_id: editor.category_id,
            amount_minor: amountMinor,
            currency_code: editor.currency_code,
            transaction_date: editor.transaction_date,
            notes: editor.notes.trim() || null,
          }),
        },
      );
      if (!response.ok) {
        const body = (await response.json().catch(() => null)) as {
          detail?: string;
        } | null;
        throw new Error(body?.detail ?? "Unable to update transaction.");
      }
      setEditor(null);
      await load();
    } catch (requestError) {
      setError(
        requestError instanceof Error
          ? requestError.message
          : "Unable to update transaction.",
      );
    } finally {
      setIsSaving(false);
    }
  }

  async function deleteTransaction(item: StatementTransaction) {
    if (!window.confirm(`Delete “${item.name}”? This cannot be undone.`))
      return;
    const csrf = csrfToken();
    try {
      const response = await fetch(
        `${apiBaseUrl}/api/v1/transactions/${item.id}`,
        {
          method: "DELETE",
          credentials: "include",
          headers: csrf ? { "X-CSRF-Token": decodeURIComponent(csrf) } : {},
        },
      );
      if (!response.ok) throw new Error("Unable to delete transaction.");
      if (pageData?.items.length === 1 && page > 1) setPage(page - 1);
      else await load();
    } catch (requestError) {
      setError(
        requestError instanceof Error
          ? requestError.message
          : "Unable to delete transaction.",
      );
    }
  }

  function toggleSelected(id: string) {
    setSelectedIds((current) => {
      const next = new Set(current);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  function toggleAllVisible() {
    setSelectedIds((current) => {
      const next = new Set(current);
      if (allVisibleSelected) visibleIds.forEach((id) => next.delete(id));
      else visibleIds.forEach((id) => next.add(id));
      return next;
    });
  }

  async function commitBulkDelete(ids: string[]) {
    try {
      const csrf = csrfToken();
      const response = await fetch(`${apiBaseUrl}/api/v1/transactions/bulk`, {
        method: "DELETE",
        credentials: "include",
        headers: {
          "Content-Type": "application/json",
          ...(csrf ? { "X-CSRF-Token": decodeURIComponent(csrf) } : {}),
        },
        body: JSON.stringify({ transaction_ids: ids }),
      });
      if (!response.ok) throw new Error("Unable to delete selected records.");
      setPendingBulkDeletion(null);
      setNotice(`${ids.length} record${ids.length === 1 ? "" : "s"} deleted.`);
      await load();
    } catch (requestError) {
      setPendingBulkDeletion(null);
      setError(
        requestError instanceof Error
          ? requestError.message
          : "Unable to delete selected records.",
      );
    }
  }

  function beginBulkDelete() {
    const ids = [...selectedIds];
    if (!ids.length || pendingBulkDeletion) return;
    if (
      !window.confirm(
        `Delete ${ids.length} selected record${ids.length === 1 ? "" : "s"}? You will have 10 seconds to undo.`,
      )
    )
      return;
    const timerId = window.setTimeout(() => void commitBulkDelete(ids), 10_000);
    setPendingBulkDeletion({ ids, timerId });
    setSelectedIds(new Set());
    setIsSelecting(false);
    setNotice(null);
  }

  function undoBulkDelete() {
    if (!pendingBulkDeletion) return;
    window.clearTimeout(pendingBulkDeletion.timerId);
    setPendingBulkDeletion(null);
    setNotice("Deletion undone.");
  }

  async function clearAllTransactions() {
    const confirmation = window.prompt(
      "This permanently deletes every transaction in your account, including records hidden by filters. Type CLEAR ALL to continue.",
    );
    if (confirmation !== "CLEAR ALL") return;
    setIsClearingAll(true);
    setError(null);
    try {
      const csrf = csrfToken();
      const response = await fetch(`${apiBaseUrl}/api/v1/transactions`, {
        method: "DELETE",
        credentials: "include",
        headers: csrf ? { "X-CSRF-Token": decodeURIComponent(csrf) } : {},
      });
      if (!response.ok) throw new Error("Unable to clear transactions.");
      const result = (await response.json()) as {
        transactions_deleted: number;
      };
      setEditor(null);
      setPage(1);
      setNotice(
        result.transactions_deleted
          ? `${result.transactions_deleted} transaction${result.transactions_deleted === 1 ? "" : "s"} deleted.`
          : "There were no transactions to delete.",
      );
      await load();
    } catch (requestError) {
      setError(
        requestError instanceof Error
          ? requestError.message
          : "Unable to clear transactions.",
      );
    } finally {
      setIsClearingAll(false);
    }
  }

  const editableCategories = categories.filter(
    (category) =>
      category.transaction_type === editor?.transaction_type &&
      !category.archived_at,
  );

  return (
    <main className="app-shell records-shell" id="records">
      <header className="page-heading">
        <div>
          <p className="eyebrow">Statement of account</p>
          <h1>Records</h1>
          <p className="page-intro">
            Every transaction, with a running net cash-flow balance.
          </p>
        </div>
        <div className="records-heading-actions">
          <button
            className="button button-quiet records-select-trigger"
            disabled={!!pendingBulkDeletion}
            onClick={() => {
              setIsSelecting((current) => !current);
              setSelectedIds(new Set());
            }}
            type="button"
          >
            {isSelecting ? "Cancel selection" : "Select records"}
          </button>
          <button
            className="text-button danger-button"
            disabled={isClearingAll || !!pendingBulkDeletion}
            onClick={() => void clearAllTransactions()}
            type="button"
          >
            {isClearingAll ? "Clearing…" : "Clear all transactions"}
          </button>
        </div>
      </header>

      <section className="card records-filters" aria-label="Filter records">
        <label className="records-search">
          <span>Search</span>
          <input
            onChange={(event) =>
              updateFilters(() => setSearch(event.target.value))
            }
            placeholder="Name or notes"
            type="search"
            value={search}
          />
        </label>
        <label>
          <span>Type</span>
          <select
            onChange={(event) =>
              updateFilters(() =>
                setType(event.target.value as "" | CategoryType),
              )
            }
            value={type}
          >
            <option value="">All types</option>
            <option value="inflow">Inflow</option>
            <option value="outflow">Outflow</option>
          </select>
        </label>
        <label>
          <span>Category</span>
          <select
            onChange={(event) =>
              updateFilters(() => setCategoryId(event.target.value))
            }
            value={categoryId}
          >
            <option value="">All categories</option>
            {categories.map((category) => (
              <option key={category.id} value={category.id}>
                {category.name}
              </option>
            ))}
          </select>
        </label>
        <label>
          <span>From</span>
          <input
            onChange={(event) =>
              updateFilters(() => setDateFrom(event.target.value))
            }
            type="date"
            value={dateFrom}
          />
        </label>
        <label>
          <span>To</span>
          <input
            onChange={(event) =>
              updateFilters(() => setDateTo(event.target.value))
            }
            type="date"
            value={dateTo}
          />
        </label>
        <label>
          <span>Sort</span>
          <select
            onChange={(event) =>
              updateFilters(() => setSort(event.target.value as Sort))
            }
            value={sort}
          >
            <option value="newest">Newest first</option>
            <option value="oldest">Oldest first</option>
          </select>
        </label>
        {paydayAvailable && (
          <fieldset className="grouping-toggle">
            <legend>Group by</legend>
            {(["calendar_month", "payday"] as const).map((item) => (
              <button
                aria-pressed={grouping === item}
                className={grouping === item ? "active" : ""}
                key={item}
                onClick={() => updateFilters(() => setGrouping(item))}
                type="button"
              >
                {item === "calendar_month" ? "Month" : "Payday"}
              </button>
            ))}
          </fieldset>
        )}
      </section>

      <p className="statement-note">
        Running balance includes all of your transactions through each row’s
        date, including records outside the current filters.
      </p>
      {error && (
        <p className="form-error" role="alert">
          {error}
        </p>
      )}
      {currenciesError && (
        <p className="form-error" role="alert">
          {currenciesError}
        </p>
      )}
      {notice && (
        <p className="notice" role="status">
          {notice}
        </p>
      )}
      {pendingBulkDeletion && (
        <div className="bulk-delete-undo" role="status">
          <span>
            Deleting {pendingBulkDeletion.ids.length} record
            {pendingBulkDeletion.ids.length === 1 ? "" : "s"} in 10 seconds.
          </span>
          <button
            className="text-button"
            onClick={undoBulkDelete}
            type="button"
          >
            Undo
          </button>
        </div>
      )}
      {isSelecting && visibleIds.length > 0 && (
        <div
          className="bulk-selection-bar"
          role="toolbar"
          aria-label="Record selection"
        >
          <label>
            <input
              checked={allVisibleSelected}
              onChange={toggleAllVisible}
              type="checkbox"
            />
            Select this page
          </label>
          <span>{selectedIds.size} selected across pages</span>
          <button
            className="button danger-button"
            disabled={!selectedIds.size}
            onClick={beginBulkDelete}
            type="button"
          >
            Delete selected
          </button>
        </div>
      )}
      {isLoading ? (
        <div className="skeleton records-skeleton" role="status">
          <span className="sr-only">Loading records…</span>
          <span />
          <span />
          <span />
          <span />
        </div>
      ) : null}
      {!isLoading && pageData?.total === 0 ? (
        <p className="empty-state">
          No records match these filters. Add a transaction or broaden your
          search.
        </p>
      ) : null}
      {!isLoading && groups.length > 0 ? (
        <section className="records-groups" aria-label="Transaction statement">
          {groups.map((group) => (
            <section className="record-group" key={group.label}>
              <h2>{group.label}</h2>
              <div className="records-table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th>Date</th>
                      {isSelecting && (
                        <th>
                          <span className="sr-only">Select</span>
                        </th>
                      )}
                      <th>Name</th>
                      <th>Category</th>
                      <th>Type</th>
                      <th className="amount-column">Amount</th>
                      <th className="amount-column">Running balance</th>
                      <th>
                        <span className="sr-only">Actions</span>
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {group.items.map((item) => (
                      <RecordRow
                        currencies={currencies}
                        item={item}
                        key={item.id}
                        isSelected={selectedIds.has(item.id)}
                        isSelecting={isSelecting}
                        onDelete={deleteTransaction}
                        onEdit={() =>
                          setEditor(
                            toEditor(
                              item,
                              currencyByCode(currencies, item.currency_code)
                                .minor_unit,
                            ),
                          )
                        }
                        onSelect={() => toggleSelected(item.id)}
                      />
                    ))}
                  </tbody>
                </table>
              </div>
              <div className="records-mobile-list">
                {group.items.map((item) => (
                  <RecordCard
                    currencies={currencies}
                    item={item}
                    key={item.id}
                    isSelected={selectedIds.has(item.id)}
                    isSelecting={isSelecting}
                    onDelete={deleteTransaction}
                    onEdit={() =>
                      setEditor(
                        toEditor(
                          item,
                          currencyByCode(currencies, item.currency_code)
                            .minor_unit,
                        ),
                      )
                    }
                    onSelect={() => toggleSelected(item.id)}
                  />
                ))}
              </div>
            </section>
          ))}
        </section>
      ) : null}
      {pageData && pageData.total_pages > 1 ? (
        <nav className="records-pagination" aria-label="Statement pages">
          <button
            className="button button-quiet"
            disabled={page <= 1}
            onClick={() => setPage(page - 1)}
            type="button"
          >
            Previous
          </button>
          <span>
            Page {pageData.page} of {pageData.total_pages} · {pageData.total}{" "}
            records
          </span>
          <button
            className="button button-quiet"
            disabled={page >= pageData.total_pages}
            onClick={() => setPage(page + 1)}
            type="button"
          >
            Next
          </button>
        </nav>
      ) : pageData && pageData.total > 0 ? (
        <p className="records-count">
          {pageData.total} record{pageData.total === 1 ? "" : "s"}
        </p>
      ) : null}

      {editor ? (
        <div className="transaction-overlay" role="presentation">
          <section
            aria-label="Edit transaction"
            aria-modal="true"
            className="transaction-sheet card"
            role="dialog"
          >
            <header className="sheet-heading">
              <div>
                <p className="eyebrow">Statement record</p>
                <h2>Edit transaction</h2>
              </div>
              <button
                className="text-button"
                onClick={() => setEditor(null)}
                type="button"
              >
                Close
              </button>
            </header>
            <form className="transaction-form" onSubmit={saveEdit}>
              <label>
                Transaction name
                <input
                  maxLength={200}
                  onChange={(event) =>
                    setEditor({ ...editor, name: event.target.value })
                  }
                  required
                  value={editor.name}
                />
              </label>
              <fieldset>
                <legend>Type</legend>
                <div className="transaction-type-switch">
                  {(["outflow", "inflow"] as const).map((item) => (
                    <button
                      aria-pressed={editor.transaction_type === item}
                      className={`type-option ${item} ${editor.transaction_type === item ? "selected" : ""}`}
                      key={item}
                      onClick={() =>
                        setEditor({
                          ...editor,
                          transaction_type: item,
                          category_id: "",
                        })
                      }
                      type="button"
                    >
                      {item === "inflow" ? "Inflow" : "Outflow"}
                    </button>
                  ))}
                </div>
              </fieldset>
              <label>
                Category
                <select
                  onChange={(event) =>
                    setEditor({ ...editor, category_id: event.target.value })
                  }
                  required
                  value={editor.category_id}
                >
                  <option value="">Choose a category</option>
                  {editableCategories.map((category) => (
                    <option key={category.id} value={category.id}>
                      {category.name}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                Currency
                <select
                  onChange={(event) =>
                    setEditor({
                      ...editor,
                      currency_code: event.target.value as CurrencyCode,
                    })
                  }
                  value={editor.currency_code}
                >
                  {!currencies.some((currency) => currency.code === editor.currency_code) && (
                    <option value={editor.currency_code}>{editor.currency_code}</option>
                  )}
                  {currencies.map((currency) => (
                    <option key={currency.code} value={currency.code}>
                      {currency.code} — {currency.name}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                Amount <span className="hint">{editor.currency_code}</span>
                <input
                  inputMode="decimal"
                  min={editorAmountStep}
                  onChange={(event) =>
                    setEditor({ ...editor, amount_minor: event.target.value })
                  }
                  required
                  step={editorAmountStep}
                  type="number"
                  value={editor.amount_minor}
                />
              </label>
              {editor.currency_code !== editor.base_currency_code ? (
                <p className="hint">
                  Captured conversion: ≈{" "}
                  {formatCurrency(
                    editor.base_amount_minor,
                    editor.base_currency_code,
                    currencyByCode(currencies, editor.base_currency_code)
                      .minor_unit,
                  )}
                  <br />
                  Rate: 1 {editor.currency_code} = {editor.exchange_rate}{" "}
                  {editor.base_currency_code}
                  <br />
                  Rate date: {readableDate(editor.exchange_rate_date)}
                </p>
              ) : null}
              <label>
                Date
                <input
                  onChange={(event) =>
                    setEditor({
                      ...editor,
                      transaction_date: event.target.value,
                    })
                  }
                  required
                  type="date"
                  value={editor.transaction_date}
                />
              </label>
              <label>
                Notes <span className="hint">optional</span>
                <textarea
                  maxLength={10000}
                  onChange={(event) =>
                    setEditor({ ...editor, notes: event.target.value })
                  }
                  value={editor.notes}
                />
              </label>
              <div className="form-actions">
                <button
                  className="button button-quiet"
                  onClick={() => setEditor(null)}
                  type="button"
                >
                  Cancel
                </button>
                <button
                  className="button"
                  disabled={isSaving || !editor.category_id}
                  type="submit"
                >
                  {isSaving ? "Saving…" : "Save changes"}
                </button>
              </div>
            </form>
          </section>
        </div>
      ) : null}
    </main>
  );
}

function RecordRow({
  item,
  currencies,
  isSelecting,
  isSelected,
  onEdit,
  onDelete,
  onSelect,
}: {
  item: StatementTransaction;
  currencies: Currency[];
  isSelecting: boolean;
  isSelected: boolean;
  onEdit: () => void;
  onDelete: (item: StatementTransaction) => void;
  onSelect: () => void;
}) {
  return (
    <tr className={isSelected ? "record-selected" : undefined}>
      <td>{readableDate(item.transaction_date)}</td>
      {isSelecting && (
        <td className="record-select-cell">
          <input
            aria-label={`Select ${item.name}`}
            checked={isSelected}
            onChange={onSelect}
            type="checkbox"
          />
        </td>
      )}
      <td>
        <span className="record-name">
          <i
            className="category-dot"
            style={{ background: item.category_color }}
          />
          {item.name}
        </span>
        {item.notes ? <small>{item.notes}</small> : null}
      </td>
      <td>{item.category_name}</td>
      <td>
        <span className={`record-type ${item.transaction_type}`}>
          {item.transaction_type}
        </span>
      </td>
      <td className={`amount-column ${item.transaction_type}`}>
        {signedAmount(item, currencyByCode(currencies, item.currency_code).minor_unit)}
        {item.currency_code !== item.base_currency_code ? (
          <small>≈ {formatCurrency(item.base_amount_minor, item.base_currency_code, currencyByCode(currencies, item.base_currency_code).minor_unit)}</small>
        ) : null}
      </td>
      <td className="amount-column">
        {item.running_balance_minor < 0 ? "−" : ""}
        {formatCurrency(Math.abs(item.running_balance_minor), item.base_currency_code, currencyByCode(currencies, item.base_currency_code).minor_unit)}
      </td>
      <td className="record-actions">
        <button className="text-button" onClick={onEdit} type="button">
          Edit
        </button>
        <button
          className="text-button danger-button"
          onClick={() => onDelete(item)}
          type="button"
        >
          Delete
        </button>
      </td>
    </tr>
  );
}

function RecordCard({
  item,
  currencies,
  isSelecting,
  isSelected,
  onEdit,
  onDelete,
  onSelect,
}: {
  item: StatementTransaction;
  currencies: Currency[];
  isSelecting: boolean;
  isSelected: boolean;
  onEdit: () => void;
  onDelete: (item: StatementTransaction) => void;
  onSelect: () => void;
}) {
  return (
    <article className={`record-card${isSelected ? " record-selected" : ""}`}>
      <div className="record-card-top">
        {isSelecting && (
          <input
            aria-label={`Select ${item.name}`}
            checked={isSelected}
            className="record-card-select"
            onChange={onSelect}
            type="checkbox"
          />
        )}
        <span
          className="category-dot"
          style={{ background: item.category_color }}
        />
        <div>
          <strong>{item.name}</strong>
          <small>
            {readableDate(item.transaction_date)} · {item.category_name}
          </small>
        </div>
        <b className={item.transaction_type}>
          {signedAmount(item, currencyByCode(currencies, item.currency_code).minor_unit)}
          {item.currency_code !== item.base_currency_code ? (
            <small>≈ {formatCurrency(item.base_amount_minor, item.base_currency_code, currencyByCode(currencies, item.base_currency_code).minor_unit)}</small>
          ) : null}
        </b>
      </div>
      <div className="record-card-bottom">
        <span>
          Balance{" "}
          <strong>
            {item.running_balance_minor < 0 ? "−" : ""}
            {formatCurrency(Math.abs(item.running_balance_minor), item.base_currency_code, currencyByCode(currencies, item.base_currency_code).minor_unit)}
          </strong>
        </span>
        {!isSelecting && (
          <span>
            <button className="text-button" onClick={onEdit} type="button">
              Edit
            </button>
            <button
              className="text-button danger-button"
              onClick={() => onDelete(item)}
              type="button"
            >
              Delete
            </button>
          </span>
        )}
      </div>
    </article>
  );
}
