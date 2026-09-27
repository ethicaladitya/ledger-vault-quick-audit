"use client";
import { useCallback, useEffect, useMemo, useState } from "react";
import { makeApi, type Year } from "./lib";
import { Overview, Upload, CoverageView, Transactions, BooksView, Reconciliation, Report, Settings } from "./views";
import Landing from "./landing";

const TOKEN_KEY = "ledger_token";
const VIEWS = [
  { id: "overview", label: "Overview" },
  { id: "upload", label: "Upload & statements" },
  { id: "coverage", label: "Statement coverage" },
  { id: "transactions", label: "Transactions" },
  { id: "books", label: "Books" },
  { id: "reconciliation", label: "Reconciliation" },
  { id: "report", label: "Report & export" },
  { id: "settings", label: "Settings" },
] as const;
export type ViewId = (typeof VIEWS)[number]["id"];

export default function Home() {
  // Read the token after mount so server and client render the same markup.
  const [token, setToken] = useState<string | null | undefined>(undefined);
  const [authMode, setAuthMode] = useState<"signin" | "register" | null>(null);
  useEffect(() => { try { setToken(localStorage.getItem(TOKEN_KEY)); } catch { setToken(null); } }, []);
  const logout = useCallback(() => { try { localStorage.removeItem(TOKEN_KEY); } catch {} setToken(null); }, []);
  if (token === undefined) return <main className="auth"><p className="muted">Loading…</p></main>;
  if (!token) {
    if (!authMode) return <Landing onSignIn={() => { setAuthMode("signin"); window.scrollTo(0, 0); }} onGetStarted={() => { setAuthMode("register"); window.scrollTo(0, 0); }} />;
    return <Auth initialMode={authMode} onBack={() => setAuthMode(null)} onAuth={t => { try { localStorage.setItem(TOKEN_KEY, t); } catch {} setToken(t); }} />;
  }
  return <Workspace token={token} onLogout={logout} />;
}


function Auth({ onAuth, onBack, initialMode }: { onAuth: (token: string) => void; onBack: () => void; initialMode: "signin" | "register" }) {
  const [register, setRegister] = useState(initialMode === "register");
  const [open, setOpen] = useState<boolean | null>(null);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [name, setName] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    fetch("/api/auth/config").then(r => r.json()).then(c => {
      setOpen(c.registration_open);
      if (!c.has_users) setRegister(true);
      else if (!c.registration_open) setRegister(false);
    }).catch(() => setOpen(false));
  }, []);
  const submit = async (e: React.FormEvent) => {
    e.preventDefault(); setError(""); setBusy(true);
    try {
      const res = await fetch(`/api/auth/${register ? "register" : "login"}`, {
        method: "POST", headers: { "content-type": "application/json" },
        body: JSON.stringify(register ? { email, password, full_name: name } : { email, password }),
      });
      const body = await res.json().catch(() => ({}));
      if (!res.ok) { setError(typeof body.detail === "string" ? body.detail : Array.isArray(body.detail) ? "Check the form: password needs 10+ characters and a valid email." : "Unable to sign in"); return; }
      onAuth(body.token);
    } catch { setError("Can't reach the server. Please try again in a moment."); } finally { setBusy(false); }
  };
  return (
    <main className="auth2">
      <section className="auth2-brand">
        <button className="auth2-back" onClick={onBack}>← Back to site</button>
        <div className="auth2-logo">Ledger<span>Vault</span></div>
        <h2>Every rupee accounted for, before your CA asks.</h2>
        <ul>
          <li>Reads bank and card statements in PDF, Excel or CSV, including password-protected ones</li>
          <li>Matches card bills and transfers so nothing is counted twice</li>
          <li>Flags what the tax department is likely to ask about</li>
          <li>Hands your CA a working paper with every figure traced to its source</li>
        </ul>
        <p className="auth2-note">Private by design: your statements stay on this server.</p>
      </section>
      <section className="auth2-form">
        <div className="auth2-card">
          <p className="eyebrow">{register ? "Create your workspace" : "Welcome back"}</p>
          <h1>{register ? "Set up LedgerVault" : "Sign in"}</h1>
          <p className="muted">{register ? "Create the owner account for this private workspace." : "Sign in to your private ITR workspace."}</p>
          <form onSubmit={submit}>
            {register && <label>Full name<input value={name} onChange={e => setName(e.target.value)} required minLength={2} autoComplete="name" /></label>}
            <label>Email<input type="email" value={email} onChange={e => setEmail(e.target.value)} required autoComplete="email" /></label>
            <label>Password<input type="password" minLength={10} value={password} onChange={e => setPassword(e.target.value)} required autoComplete={register ? "new-password" : "current-password"} />{register && <small className="muted">At least 10 characters.</small>}</label>
            {error && <p className="error">{error}</p>}
            <button className="auth2-submit" disabled={busy}>{busy ? "Please wait…" : register ? "Create workspace" : "Sign in"}</button>
          </form>
          {open && <button className="link" onClick={() => { setRegister(!register); setError(""); }}>{register ? "Already have an account? Sign in" : "New here? Create an account"}</button>}
          {open === false && !register && <p className="muted small-note">This is a private workspace. Registration is closed; ask the owner for access.</p>}
        </div>
      </section>
    </main>
  );
}

function Workspace({ token, onLogout }: { token: string; onLogout: () => void }) {
  const api = useMemo(() => makeApi(token, onLogout), [token, onLogout]);
  const [view, setView] = useState<ViewId>("overview");
  const [years, setYears] = useState<Year[]>([]);
  const [fy, setFy] = useState<string>("");
  const [version, setVersion] = useState(0);
  const [txFilter, setTxFilter] = useState<string>("");
  const [businessMode, setBusinessMode] = useState(false);
  useEffect(() => { api.get<{ business_mode: boolean }>("/settings").then(s => setBusinessMode(s.business_mode)).catch(() => {}); }, [api]);

  useEffect(() => {
    const fromHash = () => { const h = window.location.hash.slice(1) as ViewId; if (VIEWS.some(v => v.id === h)) setView(h); };
    fromHash(); window.addEventListener("hashchange", fromHash);
    return () => window.removeEventListener("hashchange", fromHash);
  }, []);
  useEffect(() => {
    api.get<Year[]>("/years").then(ys => { setYears(ys); setFy(cur => (cur && ys.some(y => y.financial_year === cur) ? cur : ys[0]?.financial_year ?? "")); }).catch(() => {});
  }, [api, version]);

  const go = (v: ViewId, filter = "") => { setTxFilter(filter); setView(v); window.location.hash = v; window.scrollTo(0, 0); };
  const refresh = () => setVersion(v => v + 1);
  const props = { api, fy, version, refresh, go, businessMode };

  return (
    <main className="shell">
      <aside>
        <div className="brand">Ledger<span>Vault</span></div>
        <label className="fy">
          <span className="eyebrow">Financial year</span>
          <select value={fy} onChange={e => setFy(e.target.value)}>
            {years.length === 0 && <option value="">No data yet</option>}
            {years.map(y => <option key={y.financial_year} value={y.financial_year}>FY {y.financial_year} ({y.transactions})</option>)}
          </select>
        </label>
        <nav>
          {VIEWS.map(v => <a key={v.id} href={`#${v.id}`} className={view === v.id ? "active" : ""} onClick={e => { e.preventDefault(); go(v.id); }}>{v.label}</a>)}
        </nav>
        <div className="privacy">Private workspace<br /><small>Your statements stay on this server. No telemetry.</small><button className="link" onClick={onLogout}>Sign out</button></div>
      </aside>
      <nav className="mobilenav">
        {VIEWS.map(v => <a key={v.id} href={`#${v.id}`} className={view === v.id ? "active" : ""} onClick={e => { e.preventDefault(); go(v.id); }}>{v.label}</a>)}
        <select value={fy} onChange={e => setFy(e.target.value)} aria-label="Financial year">
          {years.map(y => <option key={y.financial_year} value={y.financial_year}>FY {y.financial_year}</option>)}
        </select>
      </nav>
      <section className="content">
        {view === "overview" && <Overview {...props} />}
        {view === "upload" && <Upload {...props} />}
        {view === "coverage" && <CoverageView {...props} />}
        {view === "transactions" && <Transactions {...props} initialStatus={txFilter} />}
        {view === "books" && <BooksView {...props} />}
        {view === "reconciliation" && <Reconciliation {...props} />}
        {view === "report" && <Report {...props} />}
        {view === "settings" && <Settings {...props} onBusinessMode={setBusinessMode} />}
        <footer>Tax treatment is provisional until reviewed by your Chartered Accountant. <button className="link inline" onClick={onLogout}>Sign out</button></footer>
      </section>
    </main>
  );
}
