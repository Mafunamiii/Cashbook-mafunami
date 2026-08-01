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
