"use client";
import { useCallback, useEffect, useMemo, useState } from "react";
import { makeApi, type Year } from "./lib";
import { Overview, Upload, CoverageView, Transactions, BooksView, Reconciliation, Report, Settings } from "./views";
import { motion } from "motion/react";

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
  const [showAuth, setShowAuth] = useState(false);
  useEffect(() => { try { setToken(localStorage.getItem(TOKEN_KEY)); } catch { setToken(null); } }, []);
  const logout = useCallback(() => { try { localStorage.removeItem(TOKEN_KEY); } catch {} setToken(null); }, []);
  if (token === undefined) return <main className="auth"><p className="muted">Loading…</p></main>;
  if (!token) return showAuth ? <Auth onAuth={t => { try { localStorage.setItem(TOKEN_KEY, t); } catch {} setToken(t); }} /> : <Landing onLogin={() => setShowAuth(true)} />;
  return <Workspace token={token} onLogout={logout} />;
}

function Landing({ onLogin }: { onLogin: () => void }) {
  const reveal = { hidden: { opacity: 0, y: 22 }, show: { opacity: 1, y: 0 } };
  return <main className="landing">
    <nav className="landing-nav"><a className="landing-brand" href="#top">Ledger<span>Vault</span></a><div className="landing-links"><a href="#workflow">How it works</a><a href="#ca">For CAs</a><a href="#trust">Trust & privacy</a></div><button className="nav-login" onClick={onLogin}>Sign in</button></nav>
    <section className="hero" id="top"><motion.div className="hero-copy" initial="hidden" animate="show" variants={reveal} transition={{ duration: .65 }}><p className="hero-kicker"><span className="pulse-dot" /> Private financial evidence workspace</p><h1>Your statements.<br /><em>Finally reconciled.</em></h1><p className="hero-sub">Turn bank and card exports into clean, source-linked working papers your CA can actually review.</p><div className="hero-actions"><motion.button whileHover={{ y: -2 }} whileTap={{ scale: .97 }} onClick={onLogin}>Create your workspace <span>→</span></motion.button><a href="#workflow">See how it works <span>↓</span></a></div><p className="hero-note">Built for Indian financial years · No external AI · Your evidence stays private</p></motion.div><motion.div className="hero-visual" initial={{ opacity: 0, scale: .95, rotate: 1 }} animate={{ opacity: 1, scale: 1, rotate: 0 }} transition={{ duration: .8, delay: .15 }}><div className="doodle doodle-top">less admin<br />more clarity <svg viewBox="0 0 100 35"><path d="M3 25 C27 7 60 8 92 14" /><path d="M84 8 L94 14 L84 21" /></svg></div><div className="ledger-card"><div className="card-top"><span>FY 2026–27</span><span className="card-live"><i /> LIVE</span></div><div className="card-number">₹ 12,84,650</div><div className="card-label">Working-paper coverage</div><div className="coverage"><span style={{ width: "82%" }} /></div><div className="card-foot"><span>48 statements found</span><b>82%</b></div><div className="mini-lines"><span /><span /><span /></div></div><div className="float-chip chip-match"><b>✓</b><span>Card settlement<br /><strong>matched</strong></span></div><div className="float-chip chip-source"><span className="chip-icon">⌁</span><span>Every row has<br /><strong>a source</strong></span></div><svg className="hero-scribble" viewBox="0 0 520 520" aria-hidden="true"><path d="M100 448 C48 325 82 128 252 75 C376 36 473 115 467 254 C461 391 361 471 238 467 C188 465 136 457 100 448Z" /><path d="M93 429 C57 326 77 160 216 91" /></svg></motion.div></section>
    <section className="proof-strip" id="trust"><span>Designed around the work that matters</span><div><b>IMMUTABLE EVIDENCE</b><b>EXPLAINABLE RULES</b><b>CA-READY OUTPUT</b></div></section>
    <section className="workflow" id="workflow"><div className="section-intro"><p className="section-kicker">The calm way through tax season</p><h2>From messy exports<br /><em>to a clean handover.</em></h2><p>LedgerVault does the tedious joining and sorting first. You and your CA spend time on decisions—not data entry.</p></div><div className="steps"><motion.article whileHover={{ y: -5 }}><span className="step-num">01</span><h3>Bring your evidence</h3><p>Drop in bank and credit-card CSV/XLS exports. Originals stay untouched, hashed and traceable.</p><div className="step-art"><span>HDFC_Apr.csv</span><span>AMEX_FY.xlsx</span><span>ICICI_Mar.csv</span></div></motion.article><motion.article whileHover={{ y: -5 }}><span className="step-num">02</span><h3>Let flows settle</h3><p>Card bill payments and own-account transfers are linked globally—not counted twice.</p><div className="step-art match-art"><span>₹35,000 debit</span><i>↕</i><span>₹35,000 credit</span></div></motion.article><motion.article whileHover={{ y: -5 }}><span className="step-num">03</span><h3>Hand over with context</h3><p>Export bifurcations with source rows, exceptions and a clear review trail for your CA.</p><div className="step-art report-art"><span>Receipts</span><b>₹ 8.2L</b><span>Expenses</span><b>₹ 3.1L</b></div></motion.article></div></section>
    <section className="ca-section" id="ca"><div><p className="section-kicker">For the taxpayer + CA pair</p><h2>A shared paper trail,<br /><em>without the spreadsheet archaeology.</em></h2><p>Owners keep the context. Accountants get the evidence. Every correction and review decision stays attributed.</p><button className="outline-btn" onClick={onLogin}>Open LedgerVault <span>↗</span></button></div><div className="review-note"><div className="note-head"><span>CA REVIEW · FY 2026–27</span><b>PROVISIONAL</b></div><p>“Please confirm whether the ₹18,400 payment is business software or personal.”</p><div className="note-line" /><small>Question linked to 4 source rows · Owner response pending</small><div className="hand-note">ask once.<br />keep the answer.</div></div></section>
    <footer className="landing-footer"><div className="landing-brand">Ledger<span>Vault</span></div><span>Evidence first. Tax decisions stay human.</span><button className="link" onClick={onLogin}>Sign in →</button></footer>
  </main>;
}

function Auth({ onAuth }: { onAuth: (token: string) => void }) {
  const [register, setRegister] = useState(false);
  const [open, setOpen] = useState<boolean | null>(null);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [name, setName] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    fetch("/api/auth/config").then(r => r.json()).then(c => { setOpen(c.registration_open); if (!c.has_users) setRegister(true); }).catch(() => setOpen(false));
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
    } catch { setError("Can't reach the server. Is the API running?"); } finally { setBusy(false); }
  };
  return (
    <main className="auth">
      <div className="authbox">
        <div className="brand">Ledger<span>Vault</span></div>
        <p className="eyebrow">Private ITR workspace</p>
        <h1>{register ? "Create your ledger" : "Welcome back"}</h1>
        <p className="muted">Upload your bank and credit-card statements, clean up categories, and hand your CA an evidence-backed working paper.</p>
        <form onSubmit={submit}>
          {register && <label>Full name<input value={name} onChange={e => setName(e.target.value)} required minLength={2} autoComplete="name" /></label>}
          <label>Email<input type="email" value={email} onChange={e => setEmail(e.target.value)} required autoComplete="email" /></label>
          <label>Password<input type="password" minLength={10} value={password} onChange={e => setPassword(e.target.value)} required autoComplete={register ? "new-password" : "current-password"} />{register && <small className="muted">At least 10 characters.</small>}</label>
          {error && <p className="error">{error}</p>}
          <button disabled={busy}>{busy ? "Please wait…" : register ? "Create workspace" : "Sign in"}</button>
        </form>
        {(open || register) && <button className="link" onClick={() => { setRegister(!register); setError(""); }}>{register ? "Already have an account? Sign in" : "New here? Create an account"}</button>}
      </div>
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
