import { useCallback, useEffect, useMemo, useState } from "react";
import type { FormEvent } from "react";

import type { Category, CategoryType } from "../categories/categoryModel";
import type { Transaction } from "../transactions/transactionModel";

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
  transaction_date: string;
  notes: string;
};

const apiBaseUrl = import.meta.env.VITE_API_BASE_URL?.replace(/\/$/, "") ?? "";

function csrfToken(): string | undefined {
  return document.cookie
    .split("; ")
    .find((value) => value.startsWith("cashbook_csrf="))
    ?.split("=")[1];
}

function money(value: number) {
  return new Intl.NumberFormat(undefined, {
    style: "currency",
    currency: "PHP",
    maximumFractionDigits: 2,
  }).format(Math.abs(value) / 100);
}

function signedAmount(item: StatementTransaction) {
  return `${item.transaction_type === "inflow" ? "+" : "−"}${money(item.amount_minor)}`;
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

function toEditor(item: StatementTransaction): Editor {
  return {
    id: item.id,
    name: item.name,
    transaction_type: item.transaction_type,
    category_id: item.category_id,
    amount_minor: String(item.amount_minor),
    transaction_date: item.transaction_date,
    notes: item.notes ?? "",
  };
}

export function RecordsPage() {
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
    for (const item of pageData?.items ?? []) {
      const label = periodLabel(item, grouping);
      const group = result.find((candidate) => candidate.label === label);
      if (group) group.items.push(item);
      else result.push({ label, items: [item] });
    }
    return result;
  }, [grouping, pageData]);

  function updateFilters(callback: () => void) {
    setPage(1);
    callback();
  }

  async function saveEdit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!editor) return;
    const amountMinor = Number(editor.amount_minor);
    if (!Number.isSafeInteger(amountMinor) || amountMinor <= 0) {
      setError("Amount must be a positive whole number of minor units.");
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
            ...editor,
            name: editor.name.trim(),
            amount_minor: amountMinor,
            notes: editor.notes.trim() || null,
          }),
        },
      );
      if (!response.ok) throw new Error("Unable to update transaction.");
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
        <button
          className="text-button danger-button"
          disabled={isClearingAll}
          onClick={() => void clearAllTransactions()}
          type="button"
        >
          {isClearingAll ? "Clearing…" : "Clear all transactions"}
        </button>
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
      {notice && (
        <p className="notice" role="status">
          {notice}
        </p>
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
                        item={item}
                        key={item.id}
                        onDelete={deleteTransaction}
                        onEdit={() => setEditor(toEditor(item))}
                      />
                    ))}
                  </tbody>
                </table>
              </div>
              <div className="records-mobile-list">
                {group.items.map((item) => (
                  <RecordCard
                    item={item}
                    key={item.id}
                    onDelete={deleteTransaction}
                    onEdit={() => setEditor(toEditor(item))}
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
                Amount <span className="hint">minor units</span>
                <input
                  inputMode="numeric"
                  min="1"
                  onChange={(event) =>
                    setEditor({ ...editor, amount_minor: event.target.value })
                  }
                  required
                  type="text"
                  value={editor.amount_minor}
                />
              </label>
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
  onEdit,
  onDelete,
}: {
  item: StatementTransaction;
  onEdit: () => void;
  onDelete: (item: StatementTransaction) => void;
}) {
  return (
    <tr>
      <td>{readableDate(item.transaction_date)}</td>
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
        {signedAmount(item)}
      </td>
      <td className="amount-column">
        {item.running_balance_minor < 0 ? "−" : ""}
        {money(item.running_balance_minor)}
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
  onEdit,
  onDelete,
}: {
  item: StatementTransaction;
  onEdit: () => void;
  onDelete: (item: StatementTransaction) => void;
}) {
  return (
    <article className="record-card">
      <div className="record-card-top">
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
        <b className={item.transaction_type}>{signedAmount(item)}</b>
      </div>
      <div className="record-card-bottom">
        <span>
          Balance{" "}
          <strong>
            {item.running_balance_minor < 0 ? "−" : ""}
            {money(item.running_balance_minor)}
          </strong>
        </span>
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
      </div>
    </article>
  );
}
