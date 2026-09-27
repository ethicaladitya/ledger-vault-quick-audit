"use client";
import { useEffect, useRef, useState } from "react";
import { money, amountOf, STATUS_LABEL, type Api, type Dash, type Tx, type Category, type Account, type Doc, type FileResult, type Flag } from "./lib";
import type { ViewId } from "./page";

type ViewProps = { api: Api; fy: string; version: number; refresh: () => void; go: (v: ViewId, filter?: string) => void };
const q = (fy: string) => (fy ? `fy=${encodeURIComponent(fy)}` : "");

function Flags({ flags }: { flags: Flag[] }) {
  if (!flags.length) return <div className="empty">No findings. Everything uploaded for this year is categorised and matched.</div>;
  return <ul className="flags">{flags.map((f, i) => <li key={i} className={f.level}><b>{f.title}</b><p>{f.detail}</p></li>)}</ul>;
}

function StatusTag({ status }: { status: string }) {
  const good = status === "ok" || status.startsWith("confirmed");
  return <span className={`tag ${good ? "good" : ""}`}>{STATUS_LABEL[status] ?? status}</span>;
}

// ---------------- Overview ----------------

export function Overview({ api, fy, version, refresh, go }: ViewProps) {
  const [dash, setDash] = useState<Dash>();
  const [recent, setRecent] = useState<Tx[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  useEffect(() => {
    api.get<Dash>(`/dashboard?${q(fy)}`).then(setDash).catch(e => setError(e.message));
    api.get<{ items: Tx[] }>(`/transactions?limit=8&${q(fy)}`).then(r => setRecent(r.items)).catch(() => {});
  }, [api, fy, version]);
  const demo = async () => {
    setBusy(true); setError("");
    try { await api.post("/imports/demo"); refresh(); } catch (e) { setError((e as Error).message); } finally { setBusy(false); }
  };
  const empty = dash && dash.transactions === 0;

  return (
    <>
      <header>
        <div><p className="eyebrow">ITR working papers {fy && `· FY ${fy}`}</p><h1>Financial clarity, with evidence.</h1></div>
        <button onClick={() => go("upload")}>Upload statements</button>
      </header>
      {error && <p className="error">{error}</p>}
      {empty ? (
        <section className="panel onboarding">
          <h2>Start by uploading your statements</h2>
          <ol>
            <li><b>Download statements from net banking</b> for the financial year (April–March) as <b>Excel (XLS/XLSX) or CSV</b>. PDF isn't supported yet.</li>
            <li><b>Upload each account separately</b>: give it a name like “HDFC Savings” and choose bank account or credit card.</li>
            <li><b>Upload your credit-card statements too.</b> Card bill payments from your bank then cancel out, and the actual purchases are counted.</li>
            <li><b>Review</b> anything flagged, then download the Excel working paper for your CA.</li>
          </ol>
          <div className="actions">
            <button onClick={() => go("upload")}>Upload statements</button>
            <button className="secondary" onClick={demo} disabled={busy}>{busy ? "Loading…" : "Try with sample data"}</button>
          </div>
        </section>
      ) : (
        <>
          <div className="metrics">
            <article><p>Money in</p><strong>{money(dash?.income)}</strong><small>Excludes self-transfers & refunds</small></article>
            <article><p>Money out</p><strong>{money(dash?.expenses)}</strong><small>Net of refunds; card bill payments excluded</small></article>
            <article><p>Neutral flows</p><strong>{money(dash?.neutral)}</strong><small>Card bill payments & self-transfers</small></article>
            <article className="clickable" onClick={() => go("transactions", "exceptions")}><p>Needs attention</p><strong>{dash?.exceptions ?? "—"}</strong><small>Click to review →</small></article>
          </div>
          <div className="split">
            <section className="panel">
              <div className="panelhead"><h2>Audit findings</h2><span>{dash?.flags.length ?? 0} items</span></div>
              {dash && <Flags flags={dash.flags} />}
            </section>
            <section className="panel">
              <div className="panelhead"><h2>Recent transactions</h2><a className="more" href="#transactions" onClick={e => { e.preventDefault(); go("transactions"); }}>View all →</a></div>
              {recent.map(t => (
                <div className="row" key={t.id}>
                  <div><b>{t.narration}</b><small>{t.date} · {t.account} · {t.category_label}</small></div>
                  <span className={amountOf(t) < 0 ? "neg" : "pos"}>{money(amountOf(t))}</span>
                </div>
              ))}
            </section>
          </div>
        </>
      )}
    </>
  );
}

// ---------------- Upload & statements ----------------

type Hints = { name: string; dob: string; pan: string; extras: string };
const HINTS_KEY = "ledger_pdf_hints";
const emptyHints: Hints = { name: "", dob: "", pan: "", extras: "" };

export function Upload({ api, version, refresh, go }: ViewProps) {
  const [accounts, setAccounts] = useState<Account[]>([]);
  const [docs, setDocs] = useState<Doc[] | null>(null);
  const [account, setAccount] = useState("");
  const [kind, setKind] = useState<"auto" | "bank" | "card">("auto");
  const [files, setFiles] = useState<File[]>([]);
  const [results, setResults] = useState<FileResult[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [drag, setDrag] = useState(false);
  const [hints, setHints] = useState<Hints>(emptyHints);
  const [remember, setRemember] = useState(false);
  const [passwords, setPasswords] = useState<Record<string, string>>({});
  const sent = useRef<Record<string, File>>({});
  const [reviewDocs, setReviewDocs] = useState<number[]>([]);
  const addReview = (rs: FileResult[]) => setReviewDocs(prev => [...prev, ...rs.filter(r => r.document_id).map(r => r.document_id as number)]);
  const input = useRef<HTMLInputElement>(null);

  useEffect(() => {
    api.get<Account[]>("/accounts").then(setAccounts).catch(() => {});
    api.get<Doc[]>("/documents").then(setDocs).catch(() => {});
  }, [api, version]);
  useEffect(() => {
    try { const saved = localStorage.getItem(HINTS_KEY); if (saved) { setHints({ ...emptyHints, ...JSON.parse(saved) }); setRemember(true); } } catch {}
  }, []);

  const pickAccount = (name: string) => {
    setAccount(name);
    const existing = accounts.find(a => a.name === name);
    if (existing) setKind(existing.kind as "bank" | "card");
  };
  const addFiles = (list: FileList | null) => { if (list) setFiles(prev => [...prev, ...Array.from(list)]); };
  const send = async (batch: File[], password = "") => {
    const form = new FormData();
    form.append("account_name", account.trim()); form.append("kind", kind);
    form.append("name", hints.name); form.append("dob", hints.dob); form.append("pan", hints.pan); form.append("extras", hints.extras);
    if (password) form.append("password", password);
    batch.forEach(f => { form.append("files", f); sent.current[f.name] = f; });
    return (await api.post<{ files: FileResult[] }>("/imports/upload", form)).files;
  };
  const submit = async (e: React.FormEvent) => {
    e.preventDefault(); setError("");
    if (!files.length) { setError("Choose at least one statement file."); return; }
    try { if (remember) localStorage.setItem(HINTS_KEY, JSON.stringify(hints)); else localStorage.removeItem(HINTS_KEY); } catch {}
    setBusy(true);
    try {
      const rs = await send(files);
      setResults(rs); addReview(rs); setFiles([]); if (input.current) input.current.value = ""; refresh();
    } catch (err) { setError((err as Error).message); } finally { setBusy(false); }
  };
  const unlock = async (r: FileResult) => {
    const file = sent.current[r.filename];
    if (!file) return;
    setBusy(true); setError("");
    try {
      const [res] = await send([file], passwords[r.filename] ?? "");
      setResults(list => list.map(x => (x.filename === r.filename ? res : x)));
      addReview([res]);
      refresh();
    } catch (err) { setError((err as Error).message); } finally { setBusy(false); }
  };
  const remove = async (d: Doc) => {
    if (!confirm(`Delete ${d.filename} and its ${d.transactions} transactions? Your category edits on those rows will be lost.`)) return;
    try { await api.del(`/documents/${d.id}`); refresh(); } catch (err) { setError((err as Error).message); }
  };
  const locked = results.filter(r => r.needs_password);
  const setHint = (k: keyof Hints) => (e: React.ChangeEvent<HTMLInputElement>) => setHints(h => ({ ...h, [k]: e.target.value }));

  return (
    <>
      <header><div><p className="eyebrow">Evidence</p><h1>Upload statements</h1></div></header>
      <section className="panel">
        <form className="upload" onSubmit={submit}>
          <div className={`drop ${drag ? "drag" : ""}`} onClick={() => input.current?.click()}
            onDragOver={e => { e.preventDefault(); setDrag(true); }} onDragLeave={() => setDrag(false)}
            onDrop={e => { e.preventDefault(); setDrag(false); addFiles(e.dataTransfer.files); }}>
            <input ref={input} type="file" multiple accept=".pdf,.csv,.xls,.xlsx,.zip,.txt" hidden onChange={e => addFiles(e.target.files)} />
            <b>Drop all your statements here, or click to choose</b>
            <span className="muted">PDF, Excel or CSV from any bank or credit card, or a ZIP of them · mix accounts freely · up to 50 MB each</span>
            {files.length > 0 && <ul className="chosen">{files.map((f, i) => <li key={i}>{f.name} <small>({Math.ceil(f.size / 1024)} KB)</small></li>)}</ul>}
          </div>
          <details className="subpanel" open={locked.length > 0 || undefined}>
            <summary>Password-protected PDFs? Let LedgerVault try the usual bank passwords</summary>
            <p className="muted">Banks lock statements with formulas like the first 4 letters of your name + date of birth (<code>PRIY0512</code>), or your PAN + date of birth. Enter your details to try them automatically. They're used only during this upload and never saved on the server.</p>
            <div className="hintgrid">
              <label>Name as on statements<input value={hints.name} onChange={setHint("name")} placeholder="Priya Sharma" autoComplete="off" /></label>
              <label>Date of birth<input type="date" value={hints.dob} onChange={setHint("dob")} /></label>
              <label>PAN<input value={hints.pan} onChange={setHint("pan")} placeholder="ABCDE1234F" maxLength={10} autoComplete="off" /></label>
              <label>Card last 4 digits / customer IDs<input value={hints.extras} onChange={setHint("extras")} placeholder="9876, 4521, 50012345" autoComplete="off" /></label>
            </div>
            <label className="check"><input type="checkbox" checked={remember} onChange={e => setRemember(e.target.checked)} /> Remember these on this device only</label>
          </details>
          <details className="subpanel">
            <summary>Account: {account.trim() ? account : "detected automatically"}{kind !== "auto" ? ` · ${kind === "card" ? "credit card" : "bank"}` : ""}</summary>
            <div className="fields">
              <label>Account name (optional)
                <input list="accounts" value={account} onChange={e => pickAccount(e.target.value)} placeholder="Leave blank to detect from each statement" maxLength={120} />
                <datalist id="accounts">{accounts.map(a => <option key={a.id} value={a.name} />)}</datalist>
                <small className="muted">Blank: each file is filed under an account like “HDFC Bank Credit Card ••9876”. Set a name to put all these files in one account.</small>
              </label>
              <fieldset>
                <legend>Account type</legend>
                <div className="toggle">
                  <button type="button" className={kind === "auto" ? "on" : ""} onClick={() => setKind("auto")}>Detect</button>
                  <button type="button" className={kind === "bank" ? "on" : ""} onClick={() => setKind("bank")}>Bank</button>
                  <button type="button" className={kind === "card" ? "on" : ""} onClick={() => setKind("card")}>Credit card</button>
                </div>
              </fieldset>
            </div>
          </details>
          {error && <p className="error">{error}</p>}
          <div className="actions">
            <button disabled={busy || !files.length}>{busy ? "Importing…" : `Import ${files.length || ""} file${files.length === 1 ? "" : "s"}`}</button>
            {files.length > 0 && <button type="button" className="secondary" onClick={() => { setFiles([]); if (input.current) input.current.value = ""; }}>Clear</button>}
          </div>
        </form>
        {results.length > 0 && (
          <ul className="results">
            {results.map((r, i) => (
              <li key={i} className={r.needs_password ? "locked" : r.error ? "bad" : r.duplicate ? "dup" : "ok"}>
                <b>{r.filename}</b>
                <span>{r.error ?? (r.duplicate ? `Skipped: ${r.message ?? "already imported"}` : `${r.transactions} transactions imported into ${r.account}${r.kind ? ` (${r.kind === "card" ? "credit card" : "bank"})` : ""} · ${r.period}`)}</span>
                {r.needs_password && (sent.current[r.filename] ? (
                  <form className="unlock" onSubmit={e => { e.preventDefault(); unlock(r); }}>
                    <input type="password" placeholder="PDF password" value={passwords[r.filename] ?? ""} onChange={e => setPasswords(p => ({ ...p, [r.filename]: e.target.value }))} autoComplete="off" />
                    <button disabled={busy}>Unlock</button>
                    <small>Or fill in your details above and click Unlock to try the usual patterns again.</small>
                  </form>
                ) : <small>This file came from a ZIP. Upload the PDF on its own to enter its password.</small>)}
                {r.warnings?.map((w, j) => <small key={j}>{w}</small>)}
              </li>
            ))}
          </ul>
        )}
      </section>
      {reviewDocs.length > 0 && <ImportReview api={api} docIds={reviewDocs} onDone={() => { setReviewDocs([]); setResults([]); refresh(); go("overview"); }} onChange={refresh} />}
      <details className="panel help">
        <summary>Where do I get these files?</summary>
        <ul>
          <li><b>Credit cards:</b> the monthly e-statement PDF from your email or the card app works as-is, including password-protected ones.</li>
          <li><b>HDFC Bank:</b> NetBanking → Accounts → Account Statement → choose the period → Download as <i>XLS</i>, <i>Delimited</i> or <i>PDF</i>.</li>
          <li><b>ICICI Bank:</b> Bank Accounts → Account Statement → choose dates → Download → <i>XLS</i> or <i>PDF</i>.</li>
          <li><b>SBI:</b> YONO / OnlineSBI → Account Statement → choose the period → <i>Excel</i> or <i>PDF</i>.</li>
          <li>Excel/CSV is the most reliable where your bank offers it. Scanned (photographed) statements aren't supported.</li>
        </ul>
      </details>
      <section className="panel">
        <div className="panelhead"><h2>Uploaded statements</h2><span>{docs?.length ?? 0} files</span></div>
        {!docs ? <div className="empty">Loading…</div> : docs.length === 0 ? <div className="empty">Nothing uploaded yet.</div> : (
          <div className="scroll"><table>
            <thead><tr><th>File</th><th>Account</th><th>Period</th><th className="num">Rows</th><th>Notes</th><th /></tr></thead>
            <tbody>{docs.map(d => (
              <tr key={d.id}>
                <td>{d.filename}<small className="muted block">{new Date(d.imported_at + "Z").toLocaleString("en-IN")}</small></td>
                <td>{d.account}<small className="muted block">{d.kind === "card" ? "Credit card" : "Bank"}</small></td>
                <td>{d.from ? `${d.from} → ${d.to}` : "—"}</td>
                <td className="num">{d.transactions}</td>
                <td>{d.warnings.map((w, i) => <small key={i} className="block muted">{w}</small>)}</td>
                <td><button className="link danger" onClick={() => remove(d)}>Delete</button></td>
              </tr>
            ))}</tbody>
          </table></div>
        )}
      </section>
    </>
  );
}

// ---------------- Post-upload review ----------------

type ReviewGroup = { key: string; example: string; category: string; direction: "in" | "out"; count: number; total: string; tx_ids: number[]; needs_review: boolean; confirmed: boolean };
type ReviewStatement = { document_id: number; filename: string; account_id: number; account: string; kind: string; transactions: number; period: string | null };

function ImportReview({ api, docIds, onDone, onChange }: { api: Api; docIds: number[]; onDone: () => void; onChange: () => void }) {
  const [data, setData] = useState<{ statements: ReviewStatement[]; groups: ReviewGroup[] }>();
  const [cats, setCats] = useState<Category[]>([]);
  const [choice, setChoice] = useState<Record<number, string>>({});
  const [remember, setRemember] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [names, setNames] = useState<Record<number, string>>({});
  const load = () => api.get<{ statements: ReviewStatement[]; groups: ReviewGroup[] }>(`/imports/review?docs=${docIds.join(",")}`).then(d => { setData(d); setChoice({}); }).catch(e => setError(e.message));
  useEffect(() => { api.get<Category[]>("/categories").then(setCats).catch(() => {}); }, [api]);
  useEffect(() => { load(); }, [docIds.join(",")]); // eslint-disable-line react-hooks/exhaustive-deps

  const saveAccount = async (s: ReviewStatement, body: { name?: string; kind?: string }) => {
    setError("");
    try { await api.patch(`/accounts/${s.account_id}`, body); await load(); onChange(); } catch (e) { setError((e as Error).message); }
  };
  const confirmAll = async () => {
    if (!data) return;
    setBusy(true); setError("");
    const groups = data.groups.map((g, i) => {
      const category = choice[i] ?? g.category;
      return { tx_ids: g.tx_ids, category, remember_key: remember && g.key && category !== g.category ? g.key : null };
    });
    try { await api.post("/imports/confirm", { groups }); onDone(); } catch (e) { setError((e as Error).message); } finally { setBusy(false); }
  };
  if (!data) return <section className="panel"><div className="empty">Preparing review…</div></section>;
  const undecided = data.groups.filter((g, i) => g.needs_review && !choice[i]).length;

  return (
    <section className="panel review">
      <div className="panelhead"><h2>Review this import</h2><span>{data.groups.reduce((n, g) => n + g.count, 0)} transactions in {data.groups.length} groups</span></div>
      <p className="muted">Check what was detected, fix anything that's wrong, then confirm. Groups that need a decision are listed first.</p>
      <h3>Statements</h3>
      <div className="scroll"><table>
        <thead><tr><th>File</th><th>Filed under account</th><th>Type</th><th>Period</th><th className="num">Rows</th></tr></thead>
        <tbody>{data.statements.map(s => (
          <tr key={s.document_id}>
            <td>{s.filename}</td>
            <td><input className="acct" value={names[s.account_id] ?? s.account} onChange={e => setNames(n => ({ ...n, [s.account_id]: e.target.value }))}
              onBlur={e => e.target.value.trim() && e.target.value !== s.account && saveAccount(s, { name: e.target.value })} /></td>
            <td><select value={s.kind} onChange={e => saveAccount(s, { kind: e.target.value })}><option value="bank">Bank</option><option value="card">Credit card</option></select></td>
            <td className="nowrap">{s.period?.replace(" to ", " → ")}</td>
            <td className="num">{s.transactions}</td>
          </tr>
        ))}</tbody>
      </table></div>
      <h3>Categories</h3>
      <div className="scroll"><table className="groups">
        <thead><tr><th>Payee / description</th><th className="num">Count</th><th className="num">Amount</th><th>Category</th></tr></thead>
        <tbody>{data.groups.map((g, i) => {
          const current = choice[i] ?? g.category;
          return (
            <tr key={i} className={g.needs_review && !choice[i] ? "undecided" : ""}>
              <td><b className="narr block">{g.example}</b>{g.count > 1 && <small className="muted">and {g.count - 1} similar</small>}</td>
              <td className="num">{g.count}</td>
              <td className={`num nowrap ${g.direction === "out" ? "neg" : "pos"}`}>{g.direction === "out" ? "-" : ""}{money(g.total)}</td>
              <td><select value={current} onChange={e => setChoice(c => ({ ...c, [i]: e.target.value }))} className={choice[i] ? "userset" : ""}>
                {cats.map(c => <option key={c.key} value={c.key}>{c.label}</option>)}
              </select></td>
            </tr>
          );
        })}</tbody>
      </table></div>
      {error && <p className="error">{error}</p>}
      <label className="check"><input type="checkbox" checked={remember} onChange={e => setRemember(e.target.checked)} /> Remember my changes for future uploads from the same payees</label>
      <div className="actions">
        <button onClick={confirmAll} disabled={busy}>{busy ? "Saving…" : "Confirm all"}</button>
        <button className="secondary" onClick={onDone}>Skip for now</button>
        {undecided > 0 && <span className="muted">{undecided} group{undecided === 1 ? " is" : "s are"} still “unidentified”. Confirming keeps them as they are.</span>}
      </div>
    </section>
  );
}

// ---------------- Transactions ----------------

export function Transactions({ api, fy, version, initialStatus }: ViewProps & { initialStatus: string }) {
  const [items, setItems] = useState<Tx[] | null>(null);
  const [total, setTotal] = useState(0);
  const [cats, setCats] = useState<Category[]>([]);
  const [accounts, setAccounts] = useState<Account[]>([]);
  const [status, setStatus] = useState(initialStatus.startsWith("category:") ? "" : initialStatus);
  const [category, setCategory] = useState(initialStatus.startsWith("category:") ? initialStatus.slice(9) : "");
  const [account, setAccount] = useState("");
  const [search, setSearch] = useState("");
  const [page, setPage] = useState(0);
  const [error, setError] = useState("");
  const [tick, setTick] = useState(0);
  const PAGE = 100;

  useEffect(() => { api.get<Category[]>("/categories").then(setCats).catch(() => {}); api.get<Account[]>("/accounts").then(setAccounts).catch(() => {}); }, [api]);
  useEffect(() => { setPage(0); }, [status, category, account, search, fy]);
  useEffect(() => {
    const params = new URLSearchParams({ limit: String(PAGE), offset: String(page * PAGE) });
    if (fy) params.set("fy", fy);
    if (status) params.set("status", status);
    if (category) params.set("category", category);
    if (account) params.set("account_id", account);
    if (search.trim()) params.set("q", search.trim());
    const t = setTimeout(() => api.get<{ items: Tx[]; total: number }>(`/transactions?${params}`).then(r => { setItems(r.items); setTotal(r.total); }).catch(e => setError(e.message)), 200);
    return () => clearTimeout(t);
  }, [api, fy, version, status, category, account, search, page, tick]);

  const [similar, setSimilar] = useState<{ tx: Tx; category: string; key: string; count: number } | null>(null);
  const [flash, setFlash] = useState("");
  const update = async (t: Tx, body: { category?: string; note?: string; apply_similar?: boolean }) => {
    setError(""); setFlash("");
    try {
      const updated = await api.patch<Tx & { similar: { key: string; count: number } | null; applied: number }>(`/transactions/${t.id}`, body);
      setItems(list => list && list.map(x => (x.id === t.id ? updated : x)));
      if (body.apply_similar) { setSimilar(null); setFlash(`Updated ${updated.applied} similar transaction${updated.applied === 1 ? "" : "s"}. Future uploads from this payee will use this category too.`); setTick(v => v + 1); return; }
      if (body.category) setSimilar(updated.similar ? { tx: updated, category: body.category, ...updated.similar } : null);
      if (body.category && status && !updated.similar) setTimeout(() => setTick(v => v + 1), 600);
    } catch (e) { setError((e as Error).message); }
  };

  return (
    <>
      <header><div><p className="eyebrow">Ledger {fy && `· FY ${fy}`}</p><h1>Transactions</h1></div></header>
      <div className="filters">
        <input type="search" placeholder="Search narration or note…" value={search} onChange={e => setSearch(e.target.value)} />
        <select value={status} onChange={e => setStatus(e.target.value)}>
          <option value="">All statuses</option>
          <option value="exceptions">Needs attention</option>
          <option value="needs_review">Needs a category</option>
          <option value="unmatched">Unmatched transfers</option>
          <option value="ambiguous">Ambiguous matches</option>
        </select>
        <select value={category} onChange={e => setCategory(e.target.value)}>
          <option value="">All categories</option>
          {cats.map(c => <option key={c.key} value={c.key}>{c.label}</option>)}
        </select>
        <select value={account} onChange={e => setAccount(e.target.value)}>
          <option value="">All accounts</option>
          {accounts.map(a => <option key={a.id} value={a.id}>{a.name}</option>)}
        </select>
      </div>
      {error && <p className="error">{error}</p>}
      {similar && (
        <div className="similar">
          <span><b>{similar.count}</b> more transaction{similar.count === 1 ? "" : "s"} look like “{similar.key}”. Set them all to <b>{cats.find(c => c.key === similar.category)?.label ?? similar.category}</b> and remember it for future uploads?</span>
          <span className="actions tight"><button onClick={() => update(similar.tx, { category: similar.category, apply_similar: true })}>Apply to all</button><button className="secondary" onClick={() => { setSimilar(null); if (status) setTick(v => v + 1); }}>Just this one</button></span>
        </div>
      )}
      {flash && <p className="notice">{flash}</p>}
      {status === "exceptions" || status === "needs_review" ? <p className="notice">To clear a row from this list, pick the right category, or click <b>Confirm</b> to keep the suggested one. Notes (e.g. “loan from father”) are for your CA and appear in the Excel export; they don't clear the row on their own.</p> : null}
      <section className="panel">
        <div className="panelhead"><h2>{total} transactions</h2><span>Showing {items?.length ? page * PAGE + 1 : 0}–{page * PAGE + (items?.length ?? 0)}</span></div>
        {!items ? <div className="empty">Loading…</div> : items.length === 0 ? <div className="empty">No transactions match these filters.</div> : (
          <div className="scroll"><table className="txtable">
            <thead><tr><th>Date</th><th>Description</th><th className="num">Amount</th><th>Category</th><th>Status</th><th>Note</th></tr></thead>
            <tbody>{items.map(t => (
              <tr key={t.id}>
                <td className="nowrap">{t.date}</td>
                <td><span className="narr" title={t.narration}>{t.narration}</span><small className="muted block">{t.account} · row {t.source_row}</small></td>
                <td className={`num nowrap ${amountOf(t) < 0 ? "neg" : "pos"}`}>{money(amountOf(t))}</td>
                <td>
                  <select className={t.category_source === "user" ? "userset" : ""} value={t.category} onChange={e => update(t, { category: e.target.value })} title={t.itr_hint}>
                    {cats.map(c => <option key={c.key} value={c.key}>{c.label}</option>)}
                  </select>
                  {t.status === "needs_review" && <button className="link small" onClick={() => update(t, { category: t.category })}>Confirm</button>}
                </td>
                <td><StatusTag status={t.status} /></td>
                <td><NoteInput value={t.note ?? ""} onSave={note => update(t, { note })} /></td>
              </tr>
            ))}</tbody>
          </table></div>
        )}
        {total > PAGE && (
          <div className="pager">
            <button className="secondary" disabled={page === 0} onClick={() => setPage(p => p - 1)}>← Previous</button>
            <span>Page {page + 1} of {Math.ceil(total / PAGE)}</span>
            <button className="secondary" disabled={(page + 1) * PAGE >= total} onClick={() => setPage(p => p + 1)}>Next →</button>
          </div>
        )}
      </section>
    </>
  );
}

function NoteInput({ value, onSave }: { value: string; onSave: (v: string) => Promise<void> | void }) {
  const [v, setV] = useState(value);
  const [state, setState] = useState<"idle" | "saving" | "saved">("idle");
  useEffect(() => setV(value), [value]);
  const dirty = v !== value;
  const save = async () => {
    if (!dirty) return;
    setState("saving");
    await onSave(v);
    setState("saved");
    setTimeout(() => setState("idle"), 2000);
  };
  return (
    <div className="noteedit">
      <input className="note" value={v} placeholder="Add a note for your CA" maxLength={1000} onChange={e => { setV(e.target.value); setState("idle"); }}
        onBlur={save} onKeyDown={e => e.key === "Enter" && (e.target as HTMLInputElement).blur()} title="Saved when you press Enter or click away" />
      {dirty && state !== "saving" && <button className="link small" onMouseDown={e => e.preventDefault()} onClick={save}>Save</button>}
      {state === "saving" && <small className="muted">Saving…</small>}
      {state === "saved" && !dirty && <small className="pos">Saved ✓</small>}
    </div>
  );
}

// ---------------- Reconciliation ----------------

export function Reconciliation({ api, fy, version, go }: ViewProps) {
  const [data, setData] = useState<{ matched: Tx[][]; open: Tx[] }>();
  useEffect(() => { api.get<{ matched: Tx[][]; open: Tx[] }>(`/reconciliation?${q(fy)}`).then(setData).catch(() => {}); }, [api, fy, version]);
  return (
    <>
      <header><div><p className="eyebrow">Neutral flows {fy && `· FY ${fy}`}</p><h1>Reconciliation</h1></div></header>
      <p className="explain">Paying a credit-card bill from your bank isn't an expense, because the purchases on the card are. LedgerVault links each bank payment to the matching credit on the card statement (same amount, within a week), and self-transfers to the other account's credit. It links only when there is exactly one candidate.</p>
      <section className="panel">
        <div className="panelhead"><h2>Open items</h2><span>{data?.open.length ?? 0}</span></div>
        {!data ? <div className="empty">Loading…</div> : !data.open.length ? <div className="empty">Nothing open.</div> : (
          <div className="scroll"><table>
            <thead><tr><th>Date</th><th>Description</th><th>Account</th><th className="num">Amount</th><th>Status</th><th>What to do</th></tr></thead>
            <tbody>{data.open.map(t => (
              <tr key={t.id}>
                <td className="nowrap">{t.date}</td><td>{t.narration}</td><td>{t.account}</td>
                <td className="num nowrap">{money(amountOf(t))}</td><td><StatusTag status={t.status} /></td>
                <td><small>{t.status === "ambiguous" ? "Several same-amount candidates — check manually." : t.category === "card_settlement" ? (Number(t.debit) > 0 ? "Upload this card's statement." : "Upload the bank statement that paid this.") : "Upload the other account, or re-categorise if not your own account."}</small></td>
              </tr>
            ))}</tbody>
          </table></div>
        )}
        {data && data.open.length > 0 && <button className="link" onClick={() => go("upload")}>Upload missing statements →</button>}
      </section>
      <section className="panel">
        <div className="panelhead"><h2>Matched pairs</h2><span>{data?.matched.length ?? 0}</span></div>
        {!data ? <div className="empty">Loading…</div> : !data.matched.length ? <div className="empty">No matched pairs yet. Upload both the bank and card statements.</div> : (
          <div className="scroll"><table>
            <thead><tr><th>Paid from</th><th>Received by</th><th className="num">Amount</th></tr></thead>
            <tbody>{data.matched.map(pair => (
              <tr key={pair[0].match_group}>
                <td>{pair[0].account}<small className="muted block">{pair[0].date} · {pair[0].narration}</small></td>
                <td>{pair[1]?.account}<small className="muted block">{pair[1]?.date} · {pair[1]?.narration}</small></td>
                <td className="num nowrap">{money(pair[0].debit)}</td>
              </tr>
            ))}</tbody>
          </table></div>
        )}
      </section>
    </>
  );
}

// ---------------- Report ----------------

type ReportData = { totals: Record<string, string>; categories: { category: string; label: string; group: string; itr_hint: string; count: number; debit: string; credit: string }[]; flags: Flag[] };
const GROUP_LABEL: Record<string, string> = { income: "Income", tax: "Tax paid", deduction_hint: "Possible deductions", investment: "Investments", review: "To review", expense: "Expenses", adjustment: "Adjustments", neutral: "Neutral (excluded)" };

type AccountLine = { account_id: number; account: string; kind: string; count: number; inflow: string; outflow: string; refunds: string; neutral: string; exceptions: number; from: string; to: string };

export function Report({ api, fy, version, go }: ViewProps) {
  const [data, setData] = useState<ReportData & { accounts: AccountLine[] }>();
  const [accountId, setAccountId] = useState<string>("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  useEffect(() => {
    const params = new URLSearchParams();
    if (fy) params.set("fy", fy);
    if (accountId) params.set("account_id", accountId);
    api.get<ReportData & { accounts: AccountLine[] }>(`/report?${params}`).then(setData).catch(e => setError(e.message));
  }, [api, fy, version, accountId]);
  const selected = data?.accounts.find(a => String(a.account_id) === accountId);
  const download = async () => {
    setBusy(true); setError("");
    const params = new URLSearchParams();
    if (fy) params.set("fy", fy);
    if (accountId) params.set("account_id", accountId);
    const suffix = selected ? `-${selected.account.replace(/[^A-Za-z0-9]+/g, "-")}` : "";
    try { await api.download(`/export.xlsx?${params}`, `ledgervault-working-paper-${fy || "all"}${suffix}.xlsx`); } catch (e) { setError((e as Error).message); } finally { setBusy(false); }
  };
  return (
    <>
      <header>
        <div><p className="eyebrow">For your CA {fy && `· FY ${fy}`}</p><h1>Working paper</h1></div>
        <div className="actions tight">
          <select value={accountId} onChange={e => setAccountId(e.target.value)} aria-label="Report scope">
            <option value="">All accounts</option>
            {data?.accounts.map(a => <option key={a.account_id} value={a.account_id}>{a.account}</option>)}
          </select>
          <button onClick={download} disabled={busy}>{busy ? "Preparing…" : selected ? "Download this account" : "Download Excel"}</button>
        </div>
      </header>
      {error && <p className="error">{error}</p>}
      <p className="explain">{selected
        ? <>Showing <b>{selected.account}</b> only ({selected.kind === "card" ? "credit card" : "bank"}, {selected.from} → {selected.to}). <button className="link inline" onClick={() => setAccountId("")}>Back to all accounts</button></>
        : <>The Excel file has a Summary by category with ITR notes, a By account sheet (totals per account, plus a category × account table), the audit Flags, and every Transaction with its source file and row. It's a provisional working paper, not a tax computation. Use it alongside your Form 16, AIS and 26AS.</>}</p>
      {data && (
        <>
          <div className="metrics three">
            <article><p>Money in</p><strong>{money(data.totals.inflow)}</strong></article>
            <article><p>Money out (net)</p><strong>{money(data.totals.outflow)}</strong></article>
            <article><p>Neutral (excluded)</p><strong>{money(data.totals.neutral)}</strong></article>
          </div>
          {!selected && data.accounts.length > 0 && (
            <section className="panel">
              <div className="panelhead"><h2>By account</h2><span>Click an account to see its own report</span></div>
              <div className="scroll"><table>
                <thead><tr><th>Account</th><th>Period</th><th className="num">Transactions</th><th className="num">Money in</th><th className="num">Money out (net)</th><th className="num">Neutral</th><th className="num">Needs attention</th></tr></thead>
                <tbody>{data.accounts.map(a => (
                  <tr key={a.account_id} className="clickable" onClick={() => setAccountId(String(a.account_id))}>
                    <td><b>{a.account}</b><small className="muted block">{a.kind === "card" ? "Credit card" : "Bank"}</small></td>
                    <td className="nowrap">{a.from} → {a.to}</td>
                    <td className="num">{a.count}</td>
                    <td className="num nowrap">{Number(a.inflow) ? money(a.inflow) : "—"}</td>
                    <td className="num nowrap">{Number(a.outflow) ? money(a.outflow) : "—"}</td>
                    <td className="num nowrap">{Number(a.neutral) ? money(a.neutral) : "—"}</td>
                    <td className="num">{a.exceptions || "—"}</td>
                  </tr>
                ))}</tbody>
              </table></div>
            </section>
          )}
          <section className="panel">
            <div className="panelhead"><h2>Audit findings</h2><span>{data.flags.length}</span></div>
            <Flags flags={data.flags} />
          </section>
          <section className="panel">
            <div className="panelhead"><h2>By category{selected ? ` · ${selected.account}` : ""}</h2><span>Click a row to see its transactions</span></div>
            <div className="scroll"><table>
              <thead><tr><th>Category</th><th>Group</th><th className="num">Count</th><th className="num">Out</th><th className="num">In</th><th>ITR note</th></tr></thead>
              <tbody>{data.categories.map(c => (
                <tr key={c.category} className="clickable" onClick={() => go("transactions", `category:${c.category}`)}>
                  <td><b>{c.label}</b></td><td>{GROUP_LABEL[c.group] ?? c.group}</td><td className="num">{c.count}</td>
                  <td className="num nowrap">{Number(c.debit) ? money(c.debit) : "—"}</td><td className="num nowrap">{Number(c.credit) ? money(c.credit) : "—"}</td>
                  <td><small className="muted">{c.itr_hint}</small></td>
                </tr>
              ))}</tbody>
            </table></div>
          </section>
        </>
      )}
    </>
  );
}
