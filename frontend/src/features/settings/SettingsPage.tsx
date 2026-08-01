import { useCallback, useEffect, useState } from "react";
import type { FormEvent } from "react";

type AppearancePreference = "system" | "dark" | "light";

type Settings = {
  display_name: string;
  email: string;
  reporting_mode: "calendar_month" | "payday";
  appearance_preference: AppearancePreference;
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
    throw new Error(body?.detail ?? "Unable to update settings.");
  }
  return response.json() as Promise<T>;
}

export function SettingsPage({
  onBudgetSettings,
  onAppearanceChange,
}: {
  onBudgetSettings: () => void;
  onAppearanceChange: (preference: AppearancePreference) => void;
}) {
  const [settings, setSettings] = useState<Settings | null>(null);
  const [displayName, setDisplayName] = useState("");
  const [appearance, setAppearance] = useState<AppearancePreference>("system");
  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [notice, setNotice] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const result = await request<Settings>("/settings");
      setSettings(result);
      setDisplayName(result.display_name);
      setAppearance(result.appearance_preference);
      onAppearanceChange(result.appearance_preference);
      setError(null);
    } catch (loadError) {
      setError(
        loadError instanceof Error
          ? loadError.message
          : "Unable to load settings.",
      );
    }
  }, [onAppearanceChange]);

  useEffect(() => {
    const timer = window.setTimeout(() => void load(), 0);
    return () => window.clearTimeout(timer);
  }, [load]);

  async function saveProfile(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    try {
      const result = await request<Settings>("/settings", {
        method: "PATCH",
        body: JSON.stringify({
          display_name: displayName,
          appearance_preference: appearance,
        }),
      });
      setSettings(result);
      onAppearanceChange(result.appearance_preference);
      setNotice("Account preferences saved.");
      setError(null);
    } catch (saveError) {
      setError(
        saveError instanceof Error
          ? saveError.message
          : "Unable to save settings.",
      );
    }
  }

  async function changePassword(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (newPassword !== confirmPassword) {
      setError("The new password confirmation does not match.");
      return;
    }
    try {
      await request("/auth/change-password", {
        method: "POST",
        body: JSON.stringify({
          current_password: currentPassword,
          new_password: newPassword,
        }),
      });
      setCurrentPassword("");
      setNewPassword("");
      setConfirmPassword("");
      setNotice("Password changed. Other sessions were signed out.");
      setError(null);
    } catch (passwordError) {
      setError(
        passwordError instanceof Error
          ? passwordError.message
          : "Unable to change password.",
      );
    }
  }

  return (
    <main className="app-shell">
      <header className="page-heading">
        <div>
          <p className="eyebrow">Account</p>
          <h1>Settings</h1>
          <p className="page-intro">
            Manage your profile, appearance, password, and budget setup.
          </p>
        </div>
      </header>
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
      {!settings && !error ? (
        <p className="card settings-status" role="status">
          Loading settings…
        </p>
      ) : null}
      {settings && (
        <section className="settings-layout" aria-label="Account settings">
          <form className="card category-form" onSubmit={saveProfile}>
            <div className="section-heading">
              <p className="eyebrow">Profile</p>
              <h2>Personal details</h2>
            </div>
            <label>
              Email
              <input
                value={settings.email}
                disabled
                aria-describedby="email-note"
              />
            </label>
            <p className="hint" id="email-note">
              Email changes are not available from this screen.
            </p>
            <label>
              Display name
              <input
                value={displayName}
                maxLength={120}
                onChange={(event) => setDisplayName(event.target.value)}
                required
              />
            </label>
            <label>
              Appearance
              <select
                value={appearance}
                onChange={(event) =>
                  setAppearance(event.target.value as AppearancePreference)
                }
              >
                <option value="system">System preference</option>
                <option value="dark">Dark</option>
                <option value="light">Light</option>
              </select>
            </label>
            <button className="button" type="submit">
              Save account settings
            </button>
          </form>
          <form className="card category-form" onSubmit={changePassword}>
            <div className="section-heading">
              <p className="eyebrow">Security</p>
              <h2>Change password</h2>
            </div>
            <label>
              Current password
              <input
                type="password"
                autoComplete="current-password"
                value={currentPassword}
                onChange={(event) => setCurrentPassword(event.target.value)}
                required
              />
            </label>
            <label>
              New password <span className="hint">at least 12 characters</span>
              <input
                type="password"
                autoComplete="new-password"
                minLength={12}
                value={newPassword}
                onChange={(event) => setNewPassword(event.target.value)}
                required
              />
            </label>
            <label>
              Confirm new password
              <input
                type="password"
                autoComplete="new-password"
                minLength={12}
                value={confirmPassword}
                onChange={(event) => setConfirmPassword(event.target.value)}
                required
              />
            </label>
            <button className="button" type="submit">
              Change password
            </button>
          </form>
          <section className="card budget-panel">
            <div className="section-heading">
              <p className="eyebrow">Budgeting</p>
              <h2>Budget configuration</h2>
            </div>
            <p className="hint">
              Current reporting mode:{" "}
              {settings.reporting_mode === "payday"
                ? "Payday segments"
                : "Calendar month"}
              . Configure mode, historical payday cutoffs, allowances, and
              category sub-budgets in the budget settings area.
            </p>
            <button
              className="button secondary-button"
              type="button"
              onClick={onBudgetSettings}
            >
              Open budget settings
            </button>
          </section>
        </section>
      )}
    </main>
  );
}
