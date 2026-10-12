import { useState, type FormEvent } from "react";
import { useAuth } from "../lib/context";
import { ErrorView } from "../components/ui";
import OrbitArt from "../components/OrbitArt";

/** Landing hero from the design ("01 Landing hero") with the sign-in form. */
export default function Login() {
  const { login } = useAuth();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [err, setErr] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setErr(null);
    try { await login(email, password); } catch (x) { setErr(x); } finally { setBusy(false); }
  };
  return (
    <div style={{ minHeight: "100vh", display: "flex", flexDirection: "column" }}>
      <div style={{ display: "flex", flexWrap: "wrap", alignItems: "center", justifyContent: "space-between", gap: 16, padding: "16px 28px", borderBottom: "1px solid var(--hair)" }}>
        <span className="brand" style={{ fontSize: 18 }}>ASTRAL</span>
        <div style={{ display: "flex", gap: 28, fontSize: 14 }} className="muted">
          <a href="/docs" target="_blank" rel="noreferrer">API</a>
          <span>Track</span><span>Find</span><span>Act</span>
        </div>
      </div>
      <div className="ramp" aria-hidden />
      <main style={{ flex: 1, display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(min(100%, 380px), 1fr))", gap: 40, padding: "56px 28px", alignItems: "center", maxWidth: 1280, margin: "0 auto", width: "100%" }}>
        <div style={{ display: "flex", flexDirection: "column", gap: 22 }}>
          <span className="eyebrow">Advanced Space Traffic Risk Assessment &amp; Analysis Laboratory</span>
          <h1 style={{ fontSize: 52, lineHeight: 1.02, textWrap: "balance" }}>Spot satellites about to pass too close — and test how to avoid it.</h1>
          <p className="muted" style={{ maxWidth: "46ch", fontSize: 17, margin: 0 }}>
            ASTRAL tracks thousands of satellites and pieces of debris, predicts every close approach, and simulates small manoeuvres that would keep them apart.
          </p>
          <form onSubmit={submit} className="card" style={{ maxWidth: 420 }} aria-label="Sign in">
            <label className="field">Email<input type="email" autoComplete="username" required value={email} onChange={(e) => setEmail(e.target.value)} /></label>
            <label className="field">Password<input type="password" autoComplete="current-password" required value={password} onChange={(e) => setPassword(e.target.value)} /></label>
            {err !== null && <ErrorView error={err} />}
            <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
              <button className="btn primary" disabled={busy} style={{ minWidth: 180 }}>{busy ? "Signing in…" : "Sign in →"}</button>
              <a className="btn" href="/docs" target="_blank" rel="noreferrer">Read the API</a>
            </div>
            <span className="muted" style={{ fontSize: 12 }}>Accounts are created by an administrator (<span className="mono">python -m astral.cli create-admin</span>).</span>
          </form>
        </div>
        <OrbitArt />
      </main>
      <footer className="muted" style={{ fontSize: 12, padding: "0 28px 24px" }}>
        Research and evaluation software. Not qualified for operational conjunction assessment.
      </footer>
    </div>
  );
}
