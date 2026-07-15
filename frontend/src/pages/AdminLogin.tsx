import { useState } from "react";
import { login, ApiError } from "../api";

export default function AdminLogin({ onSuccess }: { onSuccess: () => void }) {
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await login(password);
      onSuccess();
    } catch (err) {
      if (err instanceof ApiError && err.status === 429) {
        setError("Too many attempts — wait a moment and try again.");
      } else {
        setError("Incorrect password.");
      }
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="login-wrap">
      <form className="card login-card" onSubmit={submit}>
        <div className="wordmark" style={{ marginBottom: 4 }}>CINA<b>CUE</b></div>
        <div className="muted" style={{ fontSize: 13, marginBottom: 20 }}>Admin Sign In</div>
        <span className="flabel">Administrator Password</span>
        <input
          type="password"
          autoComplete="current-password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          autoFocus
        />
        {error && <div className="error">{error}</div>}
        <div style={{ marginTop: 18 }}>
          <button className="btn" type="submit" disabled={busy || !password}>
            {busy ? "Signing In…" : "Sign In"}
          </button>
        </div>
      </form>
    </div>
  );
}
