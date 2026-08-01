import { useCallback, useEffect, useState } from "react";

import { AdminUsersPage } from "./features/admin/AdminUsersPage";
import { BudgetSettingsPage } from "./features/budgets/BudgetSettingsPage";
import { CategoriesPage } from "./features/categories/CategoriesPage";
import { DashboardPage } from "./features/dashboard/DashboardPage";
import { RecordsPage } from "./features/records/RecordsPage";
import { SettingsPage } from "./features/settings/SettingsPage";

type Page =
  "dashboard" | "records" | "categories" | "budgets" | "settings" | "admin";
type AppearancePreference = "system" | "dark" | "light";
const apiBaseUrl = import.meta.env.VITE_API_BASE_URL?.replace(/\/$/, "") ?? "";

export function App() {
  const [page, setPage] = useState<Page>("dashboard");
  const [isAdministrator, setIsAdministrator] = useState(false);
  const [appearance, setAppearance] = useState<AppearancePreference>("system");

  useEffect(() => {
    void fetch(`${apiBaseUrl}/api/v1/auth/session`, { credentials: "include" })
      .then(async (response) => (response.ok ? response.json() : null))
      .then((user: { role?: string } | null) =>
        setIsAdministrator(user?.role === "admin"),
      )
      .catch(() => setIsAdministrator(false));
  }, []);

  useEffect(() => {
    const useLight =
      appearance === "light" ||
      (appearance === "system" &&
        window.matchMedia("(prefers-color-scheme: light)").matches);
    document.documentElement.dataset.theme = useLight ? "light" : "dark";
  }, [appearance]);

  const handleAppearanceChange = useCallback(
    (preference: AppearancePreference) => setAppearance(preference),
    [],
  );
  return (
    <>
      <nav className="app-nav" aria-label="Primary navigation">
        <button
          className={page === "dashboard" ? "active" : ""}
          onClick={() => setPage("dashboard")}
          type="button"
        >
          Dashboard
        </button>
        <button
          className={page === "records" ? "active" : ""}
          onClick={() => setPage("records")}
          type="button"
        >
          Records
        </button>
        <button
          className={page === "categories" ? "active" : ""}
          onClick={() => setPage("categories")}
          type="button"
        >
          Categories
        </button>
        <button
          className={page === "budgets" ? "active" : ""}
          onClick={() => setPage("budgets")}
          type="button"
        >
          Budget
        </button>
        <button
          className={page === "settings" ? "active" : ""}
          onClick={() => setPage("settings")}
          type="button"
        >
          Settings
        </button>
        {isAdministrator && (
          <button
            className={page === "admin" ? "active" : ""}
            onClick={() => setPage("admin")}
            type="button"
          >
            Admin
          </button>
        )}
      </nav>
      {page === "dashboard" ? (
        <DashboardPage onViewRecords={() => setPage("records")} />
      ) : page === "records" ? (
        <RecordsPage />
      ) : page === "categories" ? (
        <CategoriesPage />
      ) : page === "settings" ? (
        <SettingsPage
          onBudgetSettings={() => setPage("budgets")}
          onAppearanceChange={handleAppearanceChange}
        />
      ) : page === "admin" && isAdministrator ? (
        <AdminUsersPage />
      ) : (
        <BudgetSettingsPage />
      )}
    </>
  );
}
