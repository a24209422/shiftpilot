import { useState, type FormEvent } from "react";
import { Navigate, useLocation, useNavigate } from "react-router";
import { ApiError } from "../api/client";
import { useAuth } from "./AuthProvider";

function messageFor(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.code === "INVALID_CREDENTIALS") return "帳號或密碼錯誤";
    return error.message;
  }
  return "登入失敗，請再試一次";
}

export function LoginPage() {
  const { status, notice, login } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);
  const from = (location.state as { from?: string } | null)?.from ?? "/";

  if (status === "signedIn") return <Navigate to={from} replace />;

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (pending) return;
    setPending(true);
    setError(null);
    try {
      await login(email, password);
      navigate(from, { replace: true });
    } catch (caught) {
      setError(messageFor(caught));
    } finally {
      setPending(false);
    }
  }

  return (
    <div className="loginWrap">
      <form className="loginCard form" onSubmit={submit}>
        <div className="brand">Shift<br />Pilot</div>
        {notice && <div className="loginNotice">{notice}</div>}
        <div className="field">
          <label htmlFor="loginEmail">Email</label>
          <input id="loginEmail" type="email" autoComplete="username" required value={email} onChange={(e) => setEmail(e.target.value)} />
        </div>
        <div className="field">
          <label htmlFor="loginPassword">密碼</label>
          <input id="loginPassword" type="password" autoComplete="current-password" required value={password} onChange={(e) => setPassword(e.target.value)} />
        </div>
        {error && <div className="formError" role="alert">{error}</div>}
        <button className="primary" type="submit" disabled={pending}>登入</button>
      </form>
    </div>
  );
}
