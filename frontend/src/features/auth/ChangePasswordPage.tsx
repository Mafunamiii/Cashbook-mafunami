import { useState } from "react";
import type { FormEvent } from "react";
import { apiRequest } from "../../api";
import type { User } from "../../api";

export function ChangePasswordPage({
  onChanged,
}: {
  onChanged: (user: User) => void;
}) {
  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmation, setConfirmation] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (newPassword !== confirmation)
      return setError("The password confirmation does not match.");
    setBusy(true);
    try {
      const result = await apiRequest<{ user: User }>("/auth/change-password", {
        method: "POST",
        body: JSON.stringify({
          current_password: currentPassword,
          new_password: newPassword,
        }),
      });
      onChanged(result.user);
    } catch (requestError) {
      setError(
        requestError instanceof Error
          ? requestError.message
          : "Unable to change password.",
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="auth-shell">
      <form className="auth-card card" onSubmit={submit}>
        <div>
          <p className="eyebrow">Security required</p>
          <h1>Choose a new password</h1>
          <p className="page-intro">
            Your temporary password must be replaced before you can use
            NamiCash.
          </p>
        </div>
        {error && (
          <p className="form-error" role="alert">
            {error}
          </p>
        )}
        <label>
          Temporary password
          <input
            autoComplete="current-password"
            required
            type="password"
            value={currentPassword}
            onChange={(event) => setCurrentPassword(event.target.value)}
          />
        </label>
        <label>
          New password <span className="hint">at least 12 characters</span>
          <input
            autoComplete="new-password"
            minLength={12}
            required
            type="password"
            value={newPassword}
            onChange={(event) => setNewPassword(event.target.value)}
          />
        </label>
        <label>
          Confirm new password
          <input
            autoComplete="new-password"
            minLength={12}
            required
            type="password"
            value={confirmation}
            onChange={(event) => setConfirmation(event.target.value)}
          />
        </label>
        <button className="button" disabled={busy} type="submit">
          {busy ? "Changing password…" : "Change password and continue"}
        </button>
      </form>
    </main>
  );
}
