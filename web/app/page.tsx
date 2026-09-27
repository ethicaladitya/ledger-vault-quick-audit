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

// Sidebar groups and icons (24px stroke icons, drawn inline so no icon library is needed).
const GROUPS: { title: string; ids: ViewId[] }[] = [
  { title: "Workspace", ids: ["overview", "upload", "coverage"] },
  { title: "Ledger", ids: ["transactions", "books", "reconciliation"] },
  { title: "Output", ids: ["report"] },
];
const ICONS: Record<ViewId, string> = {
  overview: "M3 13h8V3H3zM13 21h8V11h-8zM3 21h8v-6H3zM13 9h8V3h-8z",
  upload: "M12 16V4M7 9l5-5 5 5M4 17v2a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1v-2",
  coverage: "M8 2v4M16 2v4M3 9h18M5 5h14a2 2 0 0 1 2 2v12a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V7a2 2 0 0 1 2-2zM8 14l2 2 4-4",
  transactions: "M8 6h13M8 12h13M8 18h13M3 6h.01M3 12h.01M3 18h.01",
  books: "M4 19.5A2.5 2.5 0 0 1 6.5 17H20V3H6.5A2.5 2.5 0 0 0 4 5.5zM4 19.5A2.5 2.5 0 0 0 6.5 22H20v-5",
  reconciliation: "M7 7h13l-4-4M17 17H4l4 4",
  report: "M14 3H6a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9zM14 3v6h6M8 13h8M8 17h5",
  settings: "M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6zM19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z",
};
const Icon = ({ d, size = 18 }: { d: string; size?: number }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden><path d={d} /></svg>
);

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
  const [me, setMe] = useState<{ full_name: string; email: string } | null>(null);
  useEffect(() => { api.get<{ full_name: string; email: string }>("/auth/me").then(setMe).catch(() => {}); }, [api]);
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
            {years.map(y => <option key={y.financial_year} value={y.financial_year}>FY {y.financial_year} · {y.transactions} txns</option>)}
          </select>
        </label>
        <nav>
          {GROUPS.map(g => (
            <div key={g.title} className="navgroup">
              <span className="navtitle">{g.title}</span>
              {g.ids.map(id => {
                const v = VIEWS.find(x => x.id === id)!;
                return <a key={id} href={`#${id}`} className={view === id ? "active" : ""} onClick={e => { e.preventDefault(); go(id); }}><Icon d={ICONS[id]} />{v.label}</a>;
              })}
            </div>
          ))}
        </nav>
        <div className="sidefoot">
          <a href="#settings" className={view === "settings" ? "active" : ""} onClick={e => { e.preventDefault(); go("settings"); }}><Icon d={ICONS.settings} />Settings</a>
          <div className="user">
            <span className="avatar" aria-hidden>{(me?.full_name || "?").trim().split(/\s+/).map(w => w[0]).slice(0, 2).join("").toUpperCase()}</span>
            <span className="who"><b>{me?.full_name ?? "Your workspace"}</b><small>{me?.email ?? "Private"}</small></span>
            <button className="signout" onClick={onLogout} title="Sign out" aria-label="Sign out"><Icon d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4M16 17l5-5-5-5M21 12H9" size={17} /></button>
          </div>
          <p className="privacy-note">Private workspace · your statements stay on this server</p>
        </div>
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
        <footer>Tax treatment is provisional until reviewed by your Chartered Accountant.</footer>
      </section>
    </main>
  );
}
