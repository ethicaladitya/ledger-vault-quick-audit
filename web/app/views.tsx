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

export function Upload({ api, version, refresh, go }: ViewProps) {
  const [accounts, setAccounts] = useState<Account[]>([]);
  const [docs, setDocs] = useState<Doc[] | null>(null);
  const [account, setAccount] = useState("");
  const [kind, setKind] = useState<"bank" | "card">("bank");
  const [files, setFiles] = useState<File[]>([]);
  const [results, setResults] = useState<FileResult[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [drag, setDrag] = useState(false);
  const input = useRef<HTMLInputElement>(null);

  useEffect(() => {
    api.get<Account[]>("/accounts").then(setAccounts).catch(() => {});
    api.get<Doc[]>("/documents").then(setDocs).catch(() => {});
  }, [api, version]);

  const pickAccount = (name: string) => {
    setAccount(name);
    const existing = accounts.find(a => a.name === name);
    if (existing) setKind(existing.kind as "bank" | "card");
  };
  const addFiles = (list: FileList | null) => { if (list) setFiles(prev => [...prev, ...Array.from(list)]); };
  const submit = async (e: React.FormEvent) => {
    e.preventDefault(); setError("");
    if (!files.length) { setError("Choose at least one statement file."); return; }
    setBusy(true);
    const form = new FormData();
    form.append("account_name", account.trim()); form.append("kind", kind);
    files.forEach(f => form.append("files", f));
    try {
      const r = await api.post<{ files: FileResult[] }>("/imports/upload", form);
      setResults(r.files); setFiles([]); if (input.current) input.current.value = ""; refresh();
    } catch (err) { setError((err as Error).message); } finally { setBusy(false); }
  };
  const remove = async (d: Doc) => {
    if (!confirm(`Delete ${d.filename} and its ${d.transactions} transactions? Your category edits on those rows will be lost.`)) return;
    try { await api.del(`/documents/${d.id}`); refresh(); } catch (err) { setError((err as Error).message); }
  };

  return (
    <>
      <header><div><p className="eyebrow">Evidence</p><h1>Upload statements</h1></div></header>
      <section className="panel">
        <form className="upload" onSubmit={submit}>
          <div className="fields">
            <label>Account name
              <input list="accounts" value={account} onChange={e => pickAccount(e.target.value)} placeholder="e.g. HDFC Savings, ICICI Amazon Pay card" required maxLength={120} />
              <datalist id="accounts">{accounts.map(a => <option key={a.id} value={a.name} />)}</datalist>
              <small className="muted">Use the same name each time you add statements for this account.</small>
            </label>
            <fieldset>
              <legend>Account type</legend>
              <div className="toggle">
                <button type="button" className={kind === "bank" ? "on" : ""} onClick={() => setKind("bank")}>Bank account</button>
                <button type="button" className={kind === "card" ? "on" : ""} onClick={() => setKind("card")}>Credit card</button>
              </div>
            </fieldset>
          </div>
          <div className={`drop ${drag ? "drag" : ""}`} onClick={() => input.current?.click()}
            onDragOver={e => { e.preventDefault(); setDrag(true); }} onDragLeave={() => setDrag(false)}
            onDrop={e => { e.preventDefault(); setDrag(false); addFiles(e.dataTransfer.files); }}>
            <input ref={input} type="file" multiple accept=".csv,.xls,.xlsx,.zip,.txt" hidden onChange={e => addFiles(e.target.files)} />
            <b>Drop statement files here, or click to choose</b>
            <span className="muted">CSV, XLS, XLSX, or a ZIP of them · up to 50 MB each · several months at once is fine</span>
            {files.length > 0 && <ul className="chosen">{files.map((f, i) => <li key={i}>{f.name} <small>({Math.ceil(f.size / 1024)} KB)</small></li>)}</ul>}
          </div>
          {error && <p className="error">{error}</p>}
          <div className="actions">
            <button disabled={busy || !files.length || !account.trim()}>{busy ? "Importing…" : `Import ${files.length || ""} file${files.length === 1 ? "" : "s"}`}</button>
            {files.length > 0 && <button type="button" className="secondary" onClick={() => { setFiles([]); if (input.current) input.current.value = ""; }}>Clear</button>}
          </div>
        </form>
        {results.length > 0 && (
          <ul className="results">
            {results.map((r, i) => (
              <li key={i} className={r.error ? "bad" : r.duplicate ? "dup" : "ok"}>
                <b>{r.filename}</b>
                <span>{r.error ?? (r.duplicate ? `Skipped: ${r.message ?? "already imported"}` : `${r.transactions} transactions imported into ${r.account} (${r.period})`)}</span>
                {r.warnings?.map((w, j) => <small key={j}>{w}</small>)}
              </li>
            ))}
            {results.some(r => !r.error && !r.duplicate) && <li className="next"><button className="link" onClick={() => go("transactions", "exceptions")}>Review flagged transactions →</button></li>}
          </ul>
        )}
      </section>
      <details className="panel help">
        <summary>Where do I get these files?</summary>
        <ul>
          <li><b>HDFC Bank:</b> NetBanking → Accounts → Account Statement → choose the period → Download as <i>XLS</i> or <i>Delimited</i>.</li>
          <li><b>ICICI Bank:</b> Bank Accounts → Account Statement → choose dates → Download → <i>XLS</i>.</li>
          <li><b>SBI:</b> YONO / OnlineSBI → Account Statement → choose the period → Download in <i>Excel</i> format.</li>
          <li><b>Axis / Kotak / others:</b> look for “Account statement” → Excel or CSV. Credit-card portals often offer only PDF; where the card app offers an Excel/CSV export, use that.</li>
          <li>Password-protected or PDF statements aren't supported yet. Open them and export to Excel, or upload the other accounts for now.</li>
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

  const update = async (t: Tx, body: { category?: string; note?: string }) => {
    setError("");
    try {
      const updated = await api.patch<Tx>(`/transactions/${t.id}`, body);
      setItems(list => list && list.map(x => (x.id === t.id ? updated : x)));
      if (body.category && status) setTimeout(() => setTick(v => v + 1), 600);
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
      {status === "exceptions" || status === "needs_review" ? <p className="notice">Pick the right category for each row. Choosing the suggested category again confirms it and clears it from this list.</p> : null}
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

function NoteInput({ value, onSave }: { value: string; onSave: (v: string) => void }) {
  const [v, setV] = useState(value);
  useEffect(() => setV(value), [value]);
  return <input className="note" value={v} placeholder="Add note" maxLength={1000} onChange={e => setV(e.target.value)}
    onBlur={() => v !== value && onSave(v)} onKeyDown={e => e.key === "Enter" && (e.target as HTMLInputElement).blur()} />;
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

export function Report({ api, fy, version, go }: ViewProps) {
  const [data, setData] = useState<ReportData>();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  useEffect(() => { api.get<ReportData>(`/report?${q(fy)}`).then(setData).catch(e => setError(e.message)); }, [api, fy, version]);
  const download = async () => {
    setBusy(true); setError("");
    try { await api.download(`/export.xlsx?${q(fy)}`, `ledgervault-working-paper-${fy || "all"}.xlsx`); } catch (e) { setError((e as Error).message); } finally { setBusy(false); }
  };
  return (
    <>
      <header>
        <div><p className="eyebrow">For your CA {fy && `· FY ${fy}`}</p><h1>Working paper</h1></div>
        <button onClick={download} disabled={busy}>{busy ? "Preparing…" : "Download Excel"}</button>
      </header>
      {error && <p className="error">{error}</p>}
      <p className="explain">The Excel file has three sheets: a Summary by category with ITR notes, the audit Flags, and every Transaction with its source file and row. It's a provisional working paper, not a tax computation. Use it alongside your Form 16, AIS and 26AS.</p>
      {data && (
        <>
          <div className="metrics three">
            <article><p>Money in</p><strong>{money(data.totals.inflow)}</strong></article>
            <article><p>Money out (net)</p><strong>{money(data.totals.outflow)}</strong></article>
            <article><p>Neutral (excluded)</p><strong>{money(data.totals.neutral)}</strong></article>
          </div>
          <section className="panel">
            <div className="panelhead"><h2>Audit findings</h2><span>{data.flags.length}</span></div>
            <Flags flags={data.flags} />
          </section>
          <section className="panel">
            <div className="panelhead"><h2>By category</h2><span>Click a row to see its transactions</span></div>
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
