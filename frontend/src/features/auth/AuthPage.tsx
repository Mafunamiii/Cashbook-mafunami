import { useEffect, useState } from "react";
import type { FormEvent } from "react";

import { apiRequest } from "../../api";
import type { User } from "../../api";

type AuthResult = { user: User; csrf_token: string };

export function AuthPage({
  mode,
  onAuthenticated,
  onNavigate,
}: {
  mode: "sign-in" | "sign-up" | "password-recovery";
  onAuthenticated: (user: User) => void;
  onNavigate: (path: string) => void;
}) {
  const [email, setEmail] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [showConfirmPassword, setShowConfirmPassword] = useState(false);
  const [inviteCode, setInviteCode] = useState("");
  const [message, setMessage] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (mode === "password-recovery") {
      void apiRequest<{ message: string }>("/auth/recovery-info")
        .then((result) => setMessage(result.message))
        .catch((error: unknown) =>
          setMessage(
            error instanceof Error
              ? error.message
              : "Recovery information is unavailable.",
          ),
        );
    }
  }, [mode]);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (mode === "password-recovery") return;
    if (mode === "sign-up" && password !== confirmPassword) {
      setMessage("The password confirmation does not match.");
      return;
    }
    setBusy(true);
    setMessage(null);
    try {
      const result = await apiRequest<AuthResult>(
        mode === "sign-in" ? "/auth/login" : "/auth/register",
        {
          method: "POST",
          body: JSON.stringify(
            mode === "sign-in"
              ? { email, password }
              : {
                  email,
                  display_name: displayName,
                  password,
                  ...(inviteCode ? { invite_code: inviteCode } : {}),
                },
          ),
        },
      );
      onAuthenticated(result.user);
    } catch (error) {
      setMessage(
        error instanceof Error ? error.message : "Unable to continue.",
      );
    } finally {
      setBusy(false);
    }
  }

  if (mode === "password-recovery") {
    return (
      <main className="auth-shell">
        <section className="auth-card card">
          <p className="eyebrow">Account recovery</p>
          <h1>Recover access</h1>
          <p className="page-intro">
            {message ?? "Loading recovery instructions…"}
          </p>
          <button
            className="button"
            type="button"
            onClick={() => onNavigate("/sign-in")}
          >
            Back to sign in
          </button>
        </section>
      </main>
    );
  }

  const signingUp = mode === "sign-up";
  return (
    <main className="auth-shell">
      <form className="auth-card card" onSubmit={submit}>
        <div>
          <p className="eyebrow">NamiCash by Mafunami</p>
          <h1>{signingUp ? "Create your account" : "Welcome back"}</h1>
          <p className="page-intro">
            {signingUp
              ? "Start with a private cashbook of your own."
              : "Sign in to view your cashbook."}
          </p>
        </div>
        {message && (
          <p className="form-error" role="alert">
            {message}
          </p>
        )}
        {signingUp && (
          <label>
            Display name
            <input
              autoComplete="name"
              maxLength={120}
              required
              value={displayName}
              onChange={(event) => setDisplayName(event.target.value)}
            />
          </label>
        )}
        <label>
          Email
          <input
            autoComplete="email"
            inputMode="email"
            required
            type="email"
            value={email}
            onChange={(event) => setEmail(event.target.value)}
          />
        </label>
        <label>
          Password{" "}
          {signingUp && <span className="hint">at least 8 characters</span>}
          <span className="password-input">
            <input
              autoComplete={signingUp ? "new-password" : "current-password"}
              minLength={signingUp ? 8 : 1}
              required
              type={showPassword ? "text" : "password"}
              value={password}
              onChange={(event) => setPassword(event.target.value)}
            />
            <button
              aria-label={`${showPassword ? "Hide" : "Show"} password`}
              aria-pressed={showPassword}
              className="password-toggle"
              type="button"
              onClick={() => setShowPassword((visible) => !visible)}
            >
              {showPassword ? "Hide" : "Show"}
            </button>
          </span>
        </label>
        {signingUp && (
          <>
            <label>
              Confirm password
              <span className="password-input">
                <input
                  autoComplete="new-password"
                  minLength={8}
                  required
                  type={showConfirmPassword ? "text" : "password"}
                  value={confirmPassword}
                  onChange={(event) => setConfirmPassword(event.target.value)}
                />
                <button
                  aria-label={`${showConfirmPassword ? "Hide" : "Show"} password confirmation`}
                  aria-pressed={showConfirmPassword}
                  className="password-toggle"
                  type="button"
                  onClick={() => setShowConfirmPassword((visible) => !visible)}
                >
                  {showConfirmPassword ? "Hide" : "Show"}
                </button>
              </span>
            </label>
            <label>
              Invite code <span className="hint">if required</span>
              <input
                autoComplete="off"
                value={inviteCode}
                onChange={(event) => setInviteCode(event.target.value)}
              />
            </label>
          </>
        )}
        <button className="button" disabled={busy} type="submit">
          {busy ? "Please wait…" : signingUp ? "Create account" : "Sign in"}
        </button>
        <div className="auth-links">
          <button
            className="text-button"
            type="button"
            onClick={() => onNavigate(signingUp ? "/sign-in" : "/sign-up")}
          >
            {signingUp
              ? "Already have an account? Sign in"
              : "Create an account"}
          </button>
          {!signingUp && (
            <button
              className="text-button"
              type="button"
              onClick={() => onNavigate("/password-recovery")}
            >
              Forgot password?
            </button>
          )}
        </div>
      </form>
    </main>
  );
}
