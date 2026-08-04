import { useCallback, useEffect, useRef, useState } from "react";

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

  const links: [string, string][] = [
    ["/dashboard", "Dashboard"],
    ["/records", "Records"],
    ["/categories", "Categories"],
    ["/budgets", "Budget"],
    ["/settings", "Settings"],
  ];
  if (user.role === "admin") links.push(["/admin/users", "Admin"]);
  return (
    <>
      <AppNavigation
        activePath={effectivePath}
        email={user.email}
        links={links}
        onLogout={() => void logout()}
        onNavigate={navigate}
        userName={user.display_name}
      />
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

function AppNavigation({
  activePath,
  email,
  links,
  onLogout,
  onNavigate,
  userName,
}: {
  activePath: string;
  email: string;
  links: [string, string][];
  onLogout: () => void;
  onNavigate: (path: string) => void;
  userName: string;
}) {
  const [isOpen, setIsOpen] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);
  const toggleRef = useRef<HTMLButtonElement>(null);
  const firstLinkRef = useRef<HTMLButtonElement>(null);
  const activeLabel =
    links.find(([path]) => path === activePath)?.[1] ?? "NamiCash";

  useEffect(() => {
    if (!isOpen) return;
    firstLinkRef.current?.focus();
    const closeOnOutsideInteraction = (event: PointerEvent) => {
      if (!containerRef.current?.contains(event.target as Node)) {
        setIsOpen(false);
      }
    };
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setIsOpen(false);
        toggleRef.current?.focus();
      }
    };
    document.addEventListener("pointerdown", closeOnOutsideInteraction);
    document.addEventListener("keydown", closeOnEscape);
    return () => {
      document.removeEventListener("pointerdown", closeOnOutsideInteraction);
      document.removeEventListener("keydown", closeOnEscape);
    };
  }, [isOpen]);

  const navigationButtons = (mobile = false) =>
    links.map(([href, label], index) => (
      <button
        className={activePath === href ? "active" : ""}
        key={href}
        onClick={() => {
          setIsOpen(false);
          onNavigate(href);
        }}
        ref={mobile && index === 0 ? firstLinkRef : undefined}
        type="button"
      >
        {label}
      </button>
    ));

  return (
    <>
      <nav className="app-nav desktop-nav" aria-label="Primary navigation">
        {navigationButtons()}
        <span className="nav-spacer" />
        <span className="nav-user" title={email}>
          {userName}
        </span>
        <button onClick={onLogout} type="button">
          Sign out
        </button>
      </nav>
      <div className="mobile-nav" ref={containerRef}>
        <div className="mobile-nav-bar">
          <div>
            <span>NamiCash</span>
            <strong>{activeLabel}</strong>
          </div>
          <button
            aria-controls="mobile-navigation-menu"
            aria-expanded={isOpen}
            aria-label={
              isOpen ? "Close navigation menu" : "Open navigation menu"
            }
            className="mobile-menu-toggle"
            onClick={() => setIsOpen((open) => !open)}
            ref={toggleRef}
            type="button"
          >
            <span aria-hidden="true">{isOpen ? "×" : "☰"}</span>
          </button>
        </div>
        {isOpen && (
          <nav
            aria-label="Mobile primary navigation"
            className="mobile-nav-menu"
            id="mobile-navigation-menu"
          >
            {navigationButtons(true)}
            <div className="mobile-nav-account">
              <span title={email}>{userName}</span>
              <button
                onClick={() => {
                  setIsOpen(false);
                  onLogout();
                }}
                type="button"
              >
                Sign out
              </button>
            </div>
          </nav>
        )}
      </div>
    </>
  );
}
