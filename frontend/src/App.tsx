import { useCallback, useEffect, useState } from "react";

import { apiRequest } from "./api";
import type { User } from "./api";
import { AdminUsersPage } from "./features/admin/AdminUsersPage";
import { AuthPage } from "./features/auth/AuthPage";
import { ChangePasswordPage } from "./features/auth/ChangePasswordPage";
import { BudgetSettingsPage } from "./features/budgets/BudgetSettingsPage";
import { CategoriesPage } from "./features/categories/CategoriesPage";
import { DashboardPage } from "./features/dashboard/DashboardPage";
import { RecordsPage } from "./features/records/RecordsPage";
import { SettingsPage } from "./features/settings/SettingsPage";

type AppearancePreference = "system" | "dark" | "light";
const publicPaths = new Set(["/sign-in", "/sign-up", "/password-recovery"]);
const appPaths = new Set([
  "/dashboard",
  "/records",
  "/categories",
  "/budgets",
  "/settings",
  "/admin/users",
]);

export function App() {
  const [path, setPath] = useState(window.location.pathname);
  const [session, setSession] = useState<
    "checking" | "anonymous" | "authenticated"
  >("checking");
  const [user, setUser] = useState<User | null>(null);
  const [appearance, setAppearance] = useState<AppearancePreference>("system");

  const navigate = useCallback((nextPath: string, replace = false) => {
    window.history[replace ? "replaceState" : "pushState"]({}, "", nextPath);
    setPath(nextPath);
  }, []);

  useEffect(() => {
    const popstate = () => setPath(window.location.pathname);
    const unauthorized = () => {
      setUser(null);
      setSession("anonymous");
      navigate("/sign-in", true);
    };
    window.addEventListener("popstate", popstate);
    window.addEventListener("cashbook:unauthorized", unauthorized);
    return () => {
      window.removeEventListener("popstate", popstate);
      window.removeEventListener("cashbook:unauthorized", unauthorized);
    };
  }, [navigate]);

  useEffect(() => {
    void apiRequest<User>("/auth/session")
      .then((result) => {
        setUser(result);
        setSession("authenticated");
      })
      .catch(() => {
        setUser(null);
        setSession("anonymous");
      });
  }, []);

  useEffect(() => {
    const useLight =
      appearance === "light" ||
      (appearance === "system" &&
        window.matchMedia("(prefers-color-scheme: light)").matches);
    document.documentElement.dataset.theme = useLight ? "light" : "dark";
  }, [appearance]);

  const effectivePath =
    session === "anonymous" && !publicPaths.has(path)
      ? "/sign-in"
      : session === "authenticated" && user?.must_change_password
        ? "/change-password"
        : session === "authenticated" &&
            !user?.must_change_password &&
            (path === "/" ||
              publicPaths.has(path) ||
              path === "/change-password" ||
              !appPaths.has(path) ||
              (path === "/admin/users" && user?.role !== "admin"))
          ? "/dashboard"
          : path;

  useEffect(() => {
    if (session !== "checking" && effectivePath !== path) {
      window.history.replaceState({}, "", effectivePath);
    }
  }, [effectivePath, path, session]);

  if (session === "checking")
    return (
      <main className="auth-shell">
        <p className="card session-status" role="status">
          Checking your session…
        </p>
      </main>
    );
  if (session === "anonymous") {
    const mode =
      effectivePath === "/sign-up"
        ? "sign-up"
        : effectivePath === "/password-recovery"
          ? "password-recovery"
          : "sign-in";
    return (
      <AuthPage
        mode={mode}
        onNavigate={navigate}
        onAuthenticated={(nextUser) => {
          setUser(nextUser);
          setSession("authenticated");
          navigate(
            nextUser.must_change_password ? "/change-password" : "/dashboard",
            true,
          );
        }}
      />
    );
  }
  if (!user) return null;
  if (user.must_change_password)
    return (
      <ChangePasswordPage
        onChanged={(nextUser) => {
          setUser(nextUser);
          navigate("/dashboard", true);
        }}
      />
    );

  async function logout() {
    try {
      await apiRequest<void>("/auth/logout", { method: "POST" });
    } finally {
      setUser(null);
      setSession("anonymous");
      navigate("/sign-in", true);
    }
  }

  const links = [
    ["/dashboard", "Dashboard"],
    ["/records", "Records"],
    ["/categories", "Categories"],
    ["/budgets", "Budget"],
    ["/settings", "Settings"],
    ...(user.role === "admin" ? [["/admin/users", "Admin"]] : []),
  ];
  return (
    <>
      <nav className="app-nav" aria-label="Primary navigation">
        {links.map(([href, label]) => (
          <button
            className={effectivePath === href ? "active" : ""}
            key={href}
            onClick={() => navigate(href)}
            type="button"
          >
            {label}
          </button>
        ))}
        <span className="nav-spacer" />
        <span className="nav-user" title={user.email}>
          {user.display_name}
        </span>
        <button onClick={() => void logout()} type="button">
          Sign out
        </button>
      </nav>
      {effectivePath === "/records" ? (
        <RecordsPage />
      ) : effectivePath === "/categories" ? (
        <CategoriesPage />
      ) : effectivePath === "/budgets" ? (
        <BudgetSettingsPage />
      ) : effectivePath === "/settings" ? (
        <SettingsPage
          onBudgetSettings={() => navigate("/budgets")}
          onAppearanceChange={setAppearance}
        />
      ) : effectivePath === "/admin/users" && user.role === "admin" ? (
        <AdminUsersPage />
      ) : (
        <DashboardPage
          displayName={user.display_name}
          onBudgetSettings={() => navigate("/budgets")}
          onViewRecords={() => navigate("/records")}
        />
      )}
    </>
  );
}
