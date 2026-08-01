import { useEffect, useId, useState } from "react";
import type { FormEvent } from "react";

import type { Category, CategoryType } from "../categories/categoryModel";
import { localToday } from "./transactionModel";

type TransactionForm = {
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

function initialForm(): TransactionForm {
  return {
    name: "",
    transaction_type: "outflow",
    category_id: "",
    amount_minor: "",
    transaction_date: localToday(),
    notes: "",
  };
}

async function transactionRequest<T>(
  path: string,
  init?: RequestInit,
): Promise<T> {
  const csrf = csrfToken();
  const response = await fetch(`${apiBaseUrl}/api/v1/transactions${path}`, {
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
    throw new Error(body?.detail ?? "Unable to save transaction.");
  }
  return response.json() as Promise<T>;
}

export function AddTransaction({ onSaved }: { onSaved?: () => void }) {
  const titleId = useId();
  const [open, setOpen] = useState(false);
  const [categories, setCategories] = useState<Category[]>([]);
  const [form, setForm] = useState<TransactionForm>(initialForm);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [isSaving, setIsSaving] = useState(false);

  const availableCategories = categories.filter(
    (category) =>
      category.transaction_type === form.transaction_type &&
      !category.archived_at,
  );

  useEffect(() => {
    if (!open) return;
    let active = true;
    fetch(`${apiBaseUrl}/api/v1/categories`, { credentials: "include" })
      .then(async (response) => {
        if (!response.ok) throw new Error("Unable to load categories.");
        return (await response.json()) as Category[];
      })
      .then((result) => {
        if (!active) return;
        setCategories(result);
        setError(null);
      })
      .catch((requestError: unknown) => {
        if (active) {
          setError(
            requestError instanceof Error
              ? requestError.message
              : "Unable to load categories.",
          );
        }
      })
      .finally(() => {
        if (active) setIsLoading(false);
      });
    return () => {
      active = false;
    };
  }, [open]);

  function openForm() {
    setForm(initialForm());
    setError(null);
    setNotice(null);
    setIsLoading(true);
    setOpen(true);
  }

  function chooseType(type: CategoryType) {
    setForm((current) => ({
      ...current,
      transaction_type: type,
      category_id: "",
    }));
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!form.category_id) {
      setError("Choose a category.");
      return;
    }
    const amountMinor = Number(form.amount_minor);
    if (!Number.isSafeInteger(amountMinor) || amountMinor <= 0) {
      setError("Amount must be a positive whole number of minor units.");
      return;
    }
    setIsSaving(true);
    setError(null);
    try {
      await transactionRequest("", {
        method: "POST",
        body: JSON.stringify({
          ...form,
          name: form.name.trim(),
          amount_minor: amountMinor,
          notes: form.notes.trim() || null,
        }),
      });
      setNotice("Transaction saved.");
      setOpen(false);
      onSaved?.();
    } catch (requestError) {
      setError(
        requestError instanceof Error
          ? requestError.message
          : "Unable to save transaction.",
      );
    } finally {
      setIsSaving(false);
    }
  }

  return (
    <div className="add-transaction">
      <button
        className="button add-transaction-trigger"
        onClick={openForm}
        type="button"
      >
        Add transaction
      </button>
      {notice && (
        <p className="notice transaction-notice" role="status">
          {notice}
        </p>
      )}
      {open && (
        <div className="transaction-overlay" role="presentation">
          <section
            aria-labelledby={titleId}
            aria-modal="true"
            className="transaction-sheet card"
            role="dialog"
          >
            <header className="sheet-heading">
              <div>
                <p className="eyebrow">New record</p>
                <h2 id={titleId}>Add transaction</h2>
              </div>
              <button
                aria-label="Close add transaction form"
                className="text-button"
                onClick={() => setOpen(false)}
                type="button"
              >
                Close
              </button>
            </header>
            <form className="transaction-form" onSubmit={submit}>
              {error && (
                <p className="form-error" role="alert">
                  {error}
                </p>
              )}
              <label>
                Transaction name
                <input
                  autoComplete="off"
                  maxLength={200}
                  onChange={(event) =>
                    setForm({ ...form, name: event.target.value })
                  }
                  placeholder="e.g. Weekly groceries"
                  required
                  value={form.name}
                />
              </label>
              <fieldset>
                <legend>Type</legend>
                <div className="transaction-type-switch">
                  {(["outflow", "inflow"] as const).map((type) => (
                    <button
                      aria-pressed={form.transaction_type === type}
                      className={`type-option ${type} ${form.transaction_type === type ? "selected" : ""}`}
                      key={type}
                      onClick={() => chooseType(type)}
                      type="button"
                    >
                      {type === "inflow" ? "Inflow" : "Outflow"}
                    </button>
                  ))}
                </div>
              </fieldset>
              <label>
                Category
                <select
                  disabled={isLoading || availableCategories.length === 0}
                  onChange={(event) =>
                    setForm({ ...form, category_id: event.target.value })
                  }
                  required
                  value={form.category_id}
                >
                  <option value="">
                    {isLoading ? "Loading categories…" : "Choose a category"}
                  </option>
                  {availableCategories.map((category) => (
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
                    setForm({ ...form, amount_minor: event.target.value })
                  }
                  pattern="[0-9]+"
                  placeholder="e.g. 12500"
                  required
                  type="text"
                  value={form.amount_minor}
                />
              </label>
              <label>
                Date
                <input
                  onChange={(event) =>
                    setForm({ ...form, transaction_date: event.target.value })
                  }
                  required
                  type="date"
                  value={form.transaction_date}
                />
              </label>
              <label>
                Notes <span className="hint">optional</span>
                <textarea
                  maxLength={10_000}
                  onChange={(event) =>
                    setForm({ ...form, notes: event.target.value })
                  }
                  placeholder="Add a note"
                  value={form.notes}
                />
              </label>
              <div className="form-actions">
                <button
                  className="button button-quiet"
                  onClick={() => setOpen(false)}
                  type="button"
                >
                  Cancel
                </button>
                <button
                  className="button"
                  disabled={isSaving || isLoading}
                  type="submit"
                >
                  {isSaving ? "Saving…" : "Save transaction"}
                </button>
              </div>
            </form>
          </section>
        </div>
      )}
    </div>
  );
}
