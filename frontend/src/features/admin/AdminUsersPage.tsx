import * as Sentry from "@sentry/react";
import { useCallback, useEffect, useState } from "react";

type AdminUser = {
  id: string;
  email: string;
  display_name: string;
  role: "user" | "admin";
  is_active: boolean;
  must_change_password: boolean;
  created_at: string;
};

const apiBaseUrl = import.meta.env.VITE_API_BASE_URL?.replace(/\/$/, "") ?? "";

function FrontendErrorButton({
  onError,
  onSent,
}: {
  onError: (message: string) => void;
  onSent: (message: string) => void;
}) {
  const [isSending, setIsSending] = useState(false);

  async function sendError() {
    setIsSending(true);
    onError("");
    const eventId = Sentry.captureException(
      new Error("This is your first frontend error!"),
    );
    const sent = await Sentry.flush(5_000);
    if (sent) {
      onSent(`Frontend test error sent to Sentry. Event ID: ${eventId}`);
    } else {
      onError(
        "The frontend Sentry request timed out. Check browser tracking protection, ad blockers, and the Network tab.",
      );
    }
    setIsSending(false);
  }

  return (
    <button
      className="text-button danger-button"
      disabled={isSending}
      onClick={() => void sendError()}
      type="button"
    >
      {isSending ? "Sending frontend error…" : "Send frontend test error"}
    </button>
  );
}

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
    throw new Error(
      body?.detail ?? "Unable to complete the administration action.",
    );
  }
  return response.status === 204
    ? (undefined as T)
    : (response.json() as Promise<T>);
}

export function AdminUsersPage() {
  const [users, setUsers] = useState<AdminUser[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [temporaryPassword, setTemporaryPassword] = useState<{
    email: string;
    value: string;
  } | null>(null);
  const [isSeeding, setIsSeeding] = useState(false);
  const [isSeedingCycles, setIsSeedingCycles] = useState(false);
  const [isClearingDemo, setIsClearingDemo] = useState(false);
  const [isSendingBackendError, setIsSendingBackendError] = useState(false);

  async function sendBackendError() {
    setIsSendingBackendError(true);
    setError(null);
    try {
      await request<void>("/admin/debug/sentry-error", { method: "POST" });
      setNotice("Backend test error sent to Sentry.");
    } catch (sendError) {
      setError(
        sendError instanceof Error
          ? sendError.message
          : "Unable to send the backend test error.",
      );
    } finally {
      setIsSendingBackendError(false);
    }
  }

  const load = useCallback(async () => {
    try {
      setUsers(await request<AdminUser[]>("/admin/users"));
      setError(null);
    } catch (loadError) {
      setError(
        loadError instanceof Error
          ? loadError.message
          : "Unable to load users.",
      );
    }
  }, []);

  useEffect(() => {
    const timer = window.setTimeout(() => void load(), 0);
    return () => window.clearTimeout(timer);
  }, [load]);

  async function action(user: AdminUser, endpoint: string, init?: RequestInit) {
    try {
      await request(endpoint, init);
      setTemporaryPassword(null);
      setNotice(`Updated ${user.display_name}.`);
      await load();
    } catch (actionError) {
      setError(
        actionError instanceof Error
          ? actionError.message
          : "Unable to update user.",
      );
    }
  }

  async function generatePassword(user: AdminUser) {
    try {
      const result = await request<{ temporary_password: string }>(
        `/admin/users/${user.id}/temporary-password`,
        { method: "POST" },
      );
      setTemporaryPassword({
        email: user.email,
        value: result.temporary_password,
      });
      setNotice(`A temporary password was generated for ${user.display_name}.`);
      await load();
    } catch (actionError) {
      setError(
        actionError instanceof Error
          ? actionError.message
          : "Unable to generate password.",
      );
    }
  }

  async function seedMyAccount() {
    if (
      !window.confirm(
        "Add realistic demo transactions and budgets to your administrator account? Existing data will not be replaced.",
      )
    ) {
      return;
    }
    setIsSeeding(true);
    setError(null);
    try {
      const result = await request<{
        transactions_created: number;
        budgets_created: number;
        category_budgets_created: number;
      }>("/admin/debug/seed-my-account", { method: "POST" });
      const created =
        result.transactions_created +
        result.budgets_created +
        result.category_budgets_created;
      setNotice(
        created
          ? `Demo data added to your account: ${result.transactions_created} transactions, ${result.budgets_created} monthly budget, and ${result.category_budgets_created} category budgets.`
          : "Your account already has this month's demo data.",
      );
    } catch (actionError) {
      setError(
        actionError instanceof Error
          ? actionError.message
          : "Unable to add demo data.",
      );
    } finally {
      setIsSeeding(false);
    }
  }

  async function clearMyDemoData() {
    if (
      !window.confirm(
        "Remove all regular and cutoff-cycle data created by the debugger from your administrator account? Your other records will be preserved.",
      )
    ) {
      return;
    }
    setIsClearingDemo(true);
    setError(null);
    try {
      const result = await request<{
        transactions_deleted: number;
        budgets_deleted: number;
        category_budgets_deleted: number;
        allowances_deleted: number;
        schedules_deleted: number;
      }>("/admin/debug/demo-data", { method: "DELETE" });
      const deleted =
        result.transactions_deleted +
        result.budgets_deleted +
        result.category_budgets_deleted +
        result.allowances_deleted +
        result.schedules_deleted;
      setNotice(
        deleted
          ? `Demo data cleared: ${result.transactions_deleted} transactions, ${result.budgets_deleted} monthly budgets, ${result.category_budgets_deleted} category budgets, ${result.allowances_deleted} cutoff allowances, and ${result.schedules_deleted} cutoff schedules removed.`
          : "There is no debugger-created data to clear.",
      );
    } catch (actionError) {
      setError(
        actionError instanceof Error
          ? actionError.message
          : "Unable to clear demo data.",
      );
    } finally {
      setIsClearingDemo(false);
    }
  }

  async function seedCompletedCycles() {
    if (
      !window.confirm(
        "Add the four most recent completed 15th/30th cutoff cycles (about two months) to your administrator account? Existing data will not be replaced.",
      )
    ) {
      return;
    }
    setIsSeedingCycles(true);
    setError(null);
    try {
      const result = await request<{
        transactions_created: number;
        budgets_created: number;
        category_budgets_created: number;
        schedules_created: number;
        allowances_created: number;
      }>("/admin/debug/seed-completed-cycles", { method: "POST" });
      const created = Object.values(result).reduce(
        (total, count) => total + count,
        0,
      );
      setNotice(
        created
          ? `Cutoff-cycle demo added: ${result.transactions_created} transactions across four completed cycles and ${result.allowances_created} allowances.`
          : "Your account already has the completed cutoff-cycle demo data.",
      );
    } catch (actionError) {
      setError(
        actionError instanceof Error
          ? actionError.message
          : "Unable to add cutoff-cycle demo data.",
      );
    } finally {
      setIsSeedingCycles(false);
    }
  }

  return (
    <main className="app-shell">
      <header className="page-heading">
        <div>
          <p className="eyebrow">Administration</p>
          <h1>Users</h1>
          <p className="page-intro">
            Account and session controls only. Financial records are never shown
            here.
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
      {temporaryPassword && (
        <section className="temporary-password card" role="alert">
          <strong>
            Copy this temporary password now for {temporaryPassword.email}.
          </strong>
          <code>{temporaryPassword.value}</code>
          <p>
            It will not be shown again. Give it to the user through a trusted
            channel.
          </p>
          <button
            className="text-button"
            type="button"
            onClick={() => setTemporaryPassword(null)}
          >
            Dismiss
          </button>
        </section>
      )}
      <section
        className="card admin-debug"
        aria-labelledby="debug-tools-heading"
      >
        <div>
          <p className="eyebrow">Debugger</p>
          <h2 id="debug-tools-heading">Preview a filled cashbook</h2>
          <p>
            Add realistic transactions and budgets for the current month to your
            administrator account. Existing records are preserved, and running
            it again will not duplicate the demo data.
          </p>
        </div>
        <div className="admin-debug-actions">
          <button
            className="secondary-button"
            disabled={isSeeding || isSeedingCycles || isClearingDemo}
            onClick={() => void seedMyAccount()}
            type="button"
          >
            {isSeeding ? "Adding demo data…" : "Fill my account with demo data"}
          </button>
          <button
            className="secondary-button"
            disabled={isSeeding || isSeedingCycles || isClearingDemo}
            onClick={() => void seedCompletedCycles()}
            type="button"
          >
            {isSeedingCycles
              ? "Adding completed cycles…"
              : "Add completed cutoff-cycle demo"}
          </button>
          <button
            className="text-button danger-button"
            disabled={isSeeding || isSeedingCycles || isClearingDemo}
            onClick={() => void clearMyDemoData()}
            type="button"
          >
            {isClearingDemo ? "Clearing demo data…" : "Clear demo data"}
          </button>
          <FrontendErrorButton
            onError={(message) => setError(message || null)}
            onSent={setNotice}
          />
          <button
            className="text-button danger-button"
            disabled={isSendingBackendError}
            onClick={() => void sendBackendError()}
            type="button"
          >
            {isSendingBackendError
              ? "Sending backend error…"
              : "Send backend test error"}
          </button>
        </div>
      </section>
      <section className="card admin-users" aria-label="User accounts">
        {!users.length && !error ? (
          <p className="empty-state">Loading users…</p>
        ) : (
          users.map((user) => (
            <article className="admin-user-row" key={user.id}>
              <div>
                <strong>{user.display_name}</strong>
                <span>
                  {user.email} · {user.role}
                </span>
                <small>
                  {user.is_active ? "Active" : "Disabled"}
                  {user.must_change_password
                    ? " · Password change required"
                    : ""}
                </small>
              </div>
              <div className="admin-actions">
                <button
                  className="text-button"
                  type="button"
                  onClick={() =>
                    void action(user, `/admin/users/${user.id}/account`, {
                      method: "PATCH",
                      body: JSON.stringify({ is_active: !user.is_active }),
                    })
                  }
                >
                  {user.is_active ? "Disable" : "Enable"}
                </button>
                <button
                  className="text-button"
                  type="button"
                  onClick={() => void generatePassword(user)}
                >
                  Temporary password
                </button>
                <button
                  className="text-button"
                  type="button"
                  onClick={() =>
                    void action(
                      user,
                      `/admin/users/${user.id}/force-password-change`,
                      { method: "POST" },
                    )
                  }
                >
                  Force password change
                </button>
                <button
                  className="text-button"
                  type="button"
                  onClick={() =>
                    void action(
                      user,
                      `/admin/users/${user.id}/sessions/revoke`,
                      { method: "POST" },
                    )
                  }
                >
                  Revoke sessions
                </button>
              </div>
            </article>
          ))
        )}
      </section>
    </main>
  );
}
