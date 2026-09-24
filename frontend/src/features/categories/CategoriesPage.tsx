import { useCallback, useEffect, useState } from "react";
import type { FormEvent } from "react";

import { categoryTypeLabel, normalizeCategoryColor } from "./categoryModel";
import type { Category, CategoryType } from "./categoryModel";
import { CategoryIcon, IconPicker } from "./IconPicker";
import { findCategoryIcon } from "./iconRegistry";
import { AddTransaction } from "../transactions/AddTransaction";

type CategoryForm = {
  name: string;
  color: string;
  icon: string;
  transaction_type: CategoryType;
};

const emptyForm: CategoryForm = {
  name: "",
  color: "#22c55e",
  icon: "",
  transaction_type: "outflow",
};

const apiBaseUrl = import.meta.env.VITE_API_BASE_URL?.replace(/\/$/, "") ?? "";

class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
  }
}

function csrfToken(): string | undefined {
  return document.cookie
    .split("; ")
    .find((value) => value.startsWith("cashbook_csrf="))
    ?.split("=")[1];
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const csrf = csrfToken();
  const response = await fetch(`${apiBaseUrl}/api/v1/categories${path}`, {
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
    throw new ApiError(
      body?.detail ?? "Unable to update categories.",
      response.status,
    );
  }
  return (response.status === 204 ? undefined : response.json()) as T;
}

export function CategoriesPage() {
  const [categories, setCategories] = useState<Category[]>([]);
  const [showArchived, setShowArchived] = useState(false);
  const [isLoading, setIsLoading] = useState(true);
  const [notice, setNotice] = useState<string | null>(null);
  const [form, setForm] = useState<CategoryForm>(emptyForm);
  const [editing, setEditing] = useState<Category | null>(null);

  const loadCategories = useCallback(async () => {
    try {
      const results = await request<Category[]>(
        showArchived ? "?include_archived=true" : "",
      );
      setCategories(results);
      setNotice(null);
    } catch (error) {
      setNotice(
        error instanceof Error ? error.message : "Unable to load categories.",
      );
    } finally {
      setIsLoading(false);
    }
  }, [showArchived]);

  useEffect(() => {
    // The request resolves outside this render; its state updates represent the
    // remote category collection rather than a derived local value.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void loadCategories();
  }, [loadCategories]);

  function updateForm<K extends keyof CategoryForm>(
    field: K,
    value: CategoryForm[K],
  ) {
    setForm((current) => ({ ...current, [field]: value }));
  }

  function beginEdit(category: Category) {
    setEditing(category);
    setForm({
      name: category.name,
      color: category.color,
      icon: category.icon ?? "",
      transaction_type: category.transaction_type,
    });
    setNotice(null);
  }

  async function saveCategory(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const color = normalizeCategoryColor(form.color);
    if (!color) {
      setNotice("Enter a valid six-digit hex color, such as #22c55e.");
      return;
    }
    try {
      const body = { ...form, color, icon: form.icon.trim() || null };
      if (editing) {
        await request<Category>(`/${editing.id}`, {
          method: "PATCH",
          body: JSON.stringify(body),
        });
        setNotice("Category updated.");
      } else {
        await request<Category>("", {
          method: "POST",
          body: JSON.stringify(body),
        });
        setNotice("Category created.");
      }
      setEditing(null);
      setForm(emptyForm);
      await loadCategories();
    } catch (error) {
      setNotice(
        error instanceof Error ? error.message : "Unable to save category.",
      );
    }
  }

  async function changeArchive(category: Category) {
    try {
      const action = category.archived_at ? "restore" : "archive";
      await request<Category | undefined>(`/${category.id}/${action}`, {
        method: "POST",
      });
      setNotice(
        category.archived_at ? "Category restored." : "Category archived.",
      );
      await loadCategories();
    } catch (error) {
      setNotice(
        error instanceof Error ? error.message : "Unable to update category.",
      );
    }
  }

  async function deleteCategory(category: Category) {
    if (
      !window.confirm(
        `Delete “${category.name}” permanently? This cannot be undone.`,
      )
    )
      return;
    try {
      await request<undefined>(`/${category.id}`, { method: "DELETE" });
      if (editing?.id === category.id) {
        setEditing(null);
        setForm(emptyForm);
      }
      setNotice("Category deleted.");
      await loadCategories();
    } catch (error) {
      setNotice(
        error instanceof ApiError && error.status === 409
          ? error.message
          : error instanceof Error
            ? error.message
            : "Unable to delete category.",
      );
    }
  }

  const grouped = (type: CategoryType) =>
    categories.filter((category) => category.transaction_type === type);

  return (
    <main className="app-shell">
      <header className="page-heading">
        <div>
          <p className="eyebrow">NamiCash by Mafunami</p>
          <h1>Categories</h1>
          <p className="page-intro">
            Organize where money comes from and where it goes.
          </p>
        </div>
        <div className="heading-actions">
          <AddTransaction />
          <label className="archive-toggle">
            <input
              checked={showArchived}
              onChange={(event) => {
                setIsLoading(true);
                setShowArchived(event.target.checked);
              }}
              type="checkbox"
            />
            Show archived
          </label>
        </div>
      </header>

      <section className="category-layout" aria-label="Category management">
        <form className="category-form card" onSubmit={saveCategory}>
          <div className="section-heading">
            <p className="eyebrow">{editing ? "Edit" : "New category"}</p>
            <h2>{editing ? editing.name : "Add a category"}</h2>
          </div>
          <label>
            Name
            <input
              autoComplete="off"
              maxLength={100}
              onChange={(event) => updateForm("name", event.target.value)}
              placeholder="e.g. Pet care"
              required
              value={form.name}
            />
          </label>
          <label>
            Type
            <select
              disabled={Boolean(editing)}
              onChange={(event) =>
                updateForm(
                  "transaction_type",
                  event.target.value as CategoryType,
                )
              }
              value={form.transaction_type}
            >
              <option value="outflow">Outflow</option>
              <option value="inflow">Inflow</option>
            </select>
          </label>
          <div className="category-form-field">
            <span>Icon <span className="hint">optional</span></span>
            <IconPicker
              color={form.color}
              onChange={(icon) => updateForm("icon", icon)}
              value={form.icon}
            />
          </div>
          <fieldset>
            <legend>Color</legend>
            <input
              aria-label="Choose category color"
              onChange={(event) => updateForm("color", event.target.value)}
              type="color"
              value={normalizeCategoryColor(form.color) ?? "#000000"}
            />
            <label>
              Hex color
              <input
                aria-invalid={normalizeCategoryColor(form.color) ? undefined : true}
                maxLength={7}
                onBlur={() => {
                  const normalized = normalizeCategoryColor(form.color);
                  if (normalized) updateForm("color", normalized);
                }}
                onChange={(event) => updateForm("color", event.target.value)}
                placeholder="#22c55e"
                spellCheck={false}
                value={form.color}
              />
            </label>
          </fieldset>
          <div className="form-actions">
            {editing && (
              <button
                className="button button-quiet"
                onClick={() => {
                  setEditing(null);
                  setForm(emptyForm);
                }}
                type="button"
              >
                Cancel
              </button>
            )}
            <button className="button" type="submit">
              {editing ? "Save changes" : "Create category"}
            </button>
          </div>
        </form>

        <div className="category-groups">
          {notice && (
            <p className="notice" role="status">
              {notice}
            </p>
          )}
          {isLoading ? (
            <div className="skeleton records-skeleton" role="status">
              <span className="sr-only">Loading categories…</span>
              <span />
              <span />
              <span />
              <span />
            </div>
          ) : (
            (["outflow", "inflow"] as const).map((type) => (
              <section className="category-group" key={type}>
                <div className="section-heading inline-heading">
                  <div>
                    <p className="eyebrow">{categoryTypeLabel(type)}</p>
                    <h2>{type === "outflow" ? "Spending" : "Income"}</h2>
                  </div>
                  <span>{grouped(type).length}</span>
                </div>
                {grouped(type).length === 0 ? (
                  <p className="empty-state">No {type} categories yet.</p>
                ) : (
                  <div className="category-list">
                    {grouped(type).map((category) => (
                      <article className="category-row card" key={category.id}>
                        <span
                          className="category-swatch"
                          style={{ backgroundColor: category.color }}
                        />
                        <div className="category-name">
                          <strong className="category-name-heading">
                            {category.icon && <CategoryIcon color={category.color} size={18} value={category.icon} />}
                            {category.name}
                          </strong>
                          <span>
                            {category.icon
                              ? (findCategoryIcon(category.icon)?.label ?? "Legacy icon")
                              : "No icon"}
                          </span>
                        </div>
                        {category.archived_at && (
                          <span className="archive-badge">Archived</span>
                        )}
                        <div className="category-actions">
                          <button
                            className="text-button"
                            onClick={() => beginEdit(category)}
                            type="button"
                          >
                            Edit
                          </button>
                          <button
                            className="text-button"
                            onClick={() => void changeArchive(category)}
                            type="button"
                          >
                            {category.archived_at ? "Restore" : "Archive"}
                          </button>
                          <button
                            className="text-button danger-text"
                            onClick={() => void deleteCategory(category)}
                            type="button"
                          >
                            Delete
                          </button>
                        </div>
                      </article>
                    ))}
                  </div>
                )}
              </section>
            ))
          )}
        </div>
      </section>
    </main>
  );
}
