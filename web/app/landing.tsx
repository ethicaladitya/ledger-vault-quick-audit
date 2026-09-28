"use client";
import { useEffect, useState } from "react";
import { motion, MotionConfig } from "motion/react";
import "./landing.css";

type Props = { onSignIn: () => void; onGetStarted: () => void };

const Reveal = ({ children, delay = 0, className }: { children: React.ReactNode; delay?: number; className?: string }) => (
  <motion.div className={className} initial={{ opacity: 0, y: 24 }} whileInView={{ opacity: 1, y: 0 }}
    viewport={{ once: true, margin: "-80px" }} transition={{ duration: 0.6, delay, ease: [0.22, 1, 0.36, 1] }}>
    {children}
  </motion.div>
);

const PROBLEMS = [
  { title: "Statements everywhere", body: "Two savings accounts, three credit cards, twelve months each, in PDF, Excel and CSV. Half of them locked with a different password." },
  { title: "Everything counted twice", body: "A card bill paid from savings looks like spending. So do the purchases on the card. Add them up and your expenses double." },
  { title: "Questions you can't answer", body: "“What was this ₹2.5 lakh credit?” gets asked in July, about a transaction from last August." },
  { title: "Numbers that must match AIS", body: "Interest, dividends, card payments and cash deposits are already reported to the tax department. Your return has to agree." },
];

const STEPS = [
  { n: "01", title: "Drop in every statement", body: "Bank and card statements in PDF, Excel or CSV, or one ZIP. Each file is recognised as a bank account or card and filed automatically. Locked PDFs are opened with the usual bank password formulas built from your details.", art: ["hdfc_apr-mar.xlsx", "4854XX…45_19-12.pdf 🔒", "icici_savings.csv"] },
  { n: "02", title: "Review in minutes, not days", body: "Transactions arrive categorised and grouped by payee. Confirm a group with one click, or correct it once and LedgerVault applies it to every similar row, now and next year.", art: ["REC LIMITED · 6 credits → Dividend", "CRED · 12 payments → Card bill", "UPI-Ramesh · 4 → Rent"] },
  { n: "03", title: "Hand over the working paper", body: "Download an Excel workbook with category totals, a per-account and per-card breakdown, audit findings and every transaction traced to its file and row.", art: ["Summary", "By account", "Credit cards", "Flags", "Transactions"] },
];

const FEATURES = [
  { icon: "▤", title: "Reads Indian statements", body: "HDFC, ICICI, SBI, Axis, Kotak, IDFC FIRST and more. It handles account-detail headers, Dr/Cr columns, lakh-style amounts, wrapped narrations and multi-page tables." },
  { icon: "⚿", title: "Unlocks protected PDFs", body: "Tries the formulas banks use (name + birth date, PAN + birth date, card digits) from details you enter once. Asks for a password only when none of them work." },
  { icon: "≡", title: "Speaks bank narration", body: "UPI, NEFT, IMPS, NACH and ACH dividends, CRED and BBPS bill payments, POS, NWD and ATW withdrawals, card EMI conversions, GST and tax challans." },
  { icon: "⇄", title: "Nothing counted twice", body: "Card bills are matched to the credit on the card statement and self-transfers to the other account. Duplicate and overlapping statements are merged, not added." },
  { icon: "△", title: "Audit findings, up front", body: "Large credits without a source, cash deposits and card payments near SFT limits, interest and dividends to declare, and statements that are missing." },
  { icon: "▣", title: "Credit card reconciliation", body: "Per card: purchases, refunds, bill payments received and how many were matched. Plus a yearly total to compare with the card payments in your AIS." },
  { icon: "◐", title: "Business and personal, separated", body: "Mark accounts as business, personal or mixed. Every transaction gets a purpose, and one click produces a business-only working paper." },
  { icon: "↻", title: "Learns from you", body: "Correct a payee once and the rule sticks for every similar transaction and every future upload. Your choices are never overwritten." },
];

const AUDIENCES = [
  { title: "Salaried professionals", body: "Match what your bank saw with Form 16 and AIS. See your interest, dividends and deduction-relevant payments (insurance, rent, tuition, home loan) in one place." },
  { title: "Freelancers and consultants", body: "Separate client receipts, software and ad spend from personal life, across every account and card. Hand over a business-only paper." },
  { title: "Chartered Accountants", body: "Get one organised workbook instead of forty statements. Every figure links back to its source row, and every open question is already flagged." },
];

const SECURITY = [
  { title: "Runs on your own server", body: "Your statements and your database never leave the machine you deploy it on." },
  { title: "No third-party AI, no tracking", body: "Categorisation is deterministic and explainable. No analytics, no telemetry, no external calls." },
  { title: "Passwords never stored", body: "Your name, date of birth and PAN are used in memory to open PDFs, then discarded." },
  { title: "Evidence you can audit", body: "Each file is fingerprinted, and each transaction keeps its source file and row number." },
  { title: "Locked down by default", body: "Each account gets its own workspace, and the owner can close sign-up at any time. Sign-in is rate-limited, passwords are hashed with scrypt, and traffic is served over HTTPS." },
  { title: "Isolated workspaces", body: "Every page and API call is scoped to your own workspace, and tested for it." },
];

const FAQ = [
  { q: "Is LedgerVault tax-filing software?", a: "No. It prepares the working paper your return is based on: categorised, reconciled and traceable. You or your CA file the return. Tax treatment stays provisional until your CA reviews it." },
  { q: "Which banks and cards does it support?", a: "It reads PDF, Excel and CSV statements from the major Indian banks and card issuers, including HDFC, ICICI, SBI, Axis, Kotak and IDFC FIRST. If a layout isn't recognised, it tells you and logs a masked version of the layout so support can be added without seeing your data." },
  { q: "What happens to my PDF passwords and personal details?", a: "They are used only while your upload is processed, to try the usual bank password formulas, and are never written to the database or logs. You can choose to remember them in your own browser." },
  { q: "Will it double-count my credit card?", a: "No. Paying a card bill is treated as settling the card, not as spending. The purchases on the card statement are the spending, and each bill payment is matched to its credit on the card." },
  { q: "Does it handle business income?", a: "Yes. Turn on business tracking, mark each account's use, and generate a business-only report. Capital gains still need your broker's P&L statement." },
  { q: "Can it read scanned statements?", a: "Not yet. It needs the e-statement PDF, or the Excel/CSV download from net banking. Scanned image PDFs are flagged clearly rather than guessed." },
];

function ProductPreview() {
  return (
    <div className="mk-frame" aria-label="LedgerVault overview, sample data">
      <div className="mk-chrome"><i /><i /><i /><span>ledgervault · Overview · FY 2025-26</span></div>
      <div className="mk-app">
        <div className="mk-side">
          <b>Ledger<span>Vault</span></b>
          {["Overview", "Upload", "Transactions", "Reconciliation", "Report"].map((x, i) => <em key={x} className={i === 0 ? "on" : ""}>{x}</em>)}
        </div>
        <div className="mk-main">
          <div className="mk-tiles">
            <div><small>Money in</small><strong>₹18,42,300</strong></div>
            <div><small>Money out (net)</small><strong>₹9,76,810</strong></div>
            <div><small>Card bills</small><strong>₹4,12,560</strong><em>31 of 31 matched</em></div>
          </div>
          <div className="mk-panel">
            <small>Audit findings</small>
            <p className="warn"><b>1 credit of ₹2 lakh or more without a clear source</b><span>Note the source before your CA asks: loan, gift or asset sale.</span></p>
            <p><b>Interest received: ₹41,230</b><span>Declare under other sources and compare with AIS.</span></p>
            <p><b>Axis card ••9534: statement missing for Nov 2025</b><span>Upload it so those purchases are counted.</span></p>
          </div>
          <div className="mk-rows">
            {[["Salary · ACME Pvt Ltd", "Salary", "+₹1,52,000"], ["ACH C- REC LIMITED", "Dividend", "+₹363"], ["AWS · Amazon Web Services", "Software", "−₹4,210"], ["HDFC card bill via CRED", "Matched", "−₹38,400"]].map(r => (
              <div key={r[0]}><span>{r[0]}</span><em>{r[1]}</em><b className={r[2].startsWith("+") ? "in" : ""}>{r[2]}</b></div>
            ))}
          </div>
        </div>
      </div>
      <div className="mk-caption">Sample data</div>
    </div>
  );
}

export default function Landing({ onSignIn, onGetStarted }: Props) {
  const [open, setOpen] = useState<number | null>(0);
  const [registrationOpen, setRegistrationOpen] = useState(false);
  useEffect(() => { fetch("/api/auth/config").then(r => r.json()).then(c => setRegistrationOpen(!!c.registration_open)).catch(() => {}); }, []);
  const primary = registrationOpen ? onGetStarted : onSignIn;
  const primaryLabel = registrationOpen ? "Get started" : "Sign in to your workspace";

  return (
    <MotionConfig reducedMotion="user">
      <main className="mk">
        <header className="mk-nav">
          <a className="mk-brand" href="#top">Ledger<span>Vault</span></a>
          <nav>
            <a href="#how">How it works</a><a href="#features">Features</a><a href="#ca">For CAs</a><a href="#security">Security</a><a href="#faq">FAQ</a>
          </nav>
          <div className="mk-nav-actions">
            <button className="mk-btn ghost" onClick={onSignIn}>Sign in</button>
            {registrationOpen && <button className="mk-btn" onClick={onGetStarted}>Get started</button>}
          </div>
        </header>

        <section className="mk-hero" id="top">
          <Reveal className="mk-hero-copy">
            <p className="mk-eyebrow">ITR working papers for India</p>
            <h1>Every rupee accounted for, <span>before your CA asks.</span></h1>
            <p className="mk-lead">LedgerVault reads a full year of bank and credit-card statements (PDF, Excel or CSV, even password-protected), categorises every transaction, matches card bills and transfers so nothing is counted twice, and hands your Chartered Accountant a working paper they can trust.</p>
            <div className="mk-cta">
              <button className="mk-btn lg" onClick={primary}>{primaryLabel} <span aria-hidden>→</span></button>
              <a className="mk-btn lg ghost" href="#how">See how it works</a>
            </div>
            <ul className="mk-trust">
              <li>Self-hosted</li><li>No third-party AI</li><li>No telemetry</li><li>Built for Indian banks and cards</li>
            </ul>
          </Reveal>
          <Reveal delay={0.15} className="mk-hero-visual"><ProductPreview /></Reveal>
        </section>

        <section className="mk-section" id="problem">
          <Reveal className="mk-intro">
            <p className="mk-eyebrow">The problem</p>
            <h2>Tax season shouldn’t feel like forensic accounting.</h2>
            <p>The information is all there, spread across banks, cards, formats and passwords. Pulling it together by hand is slow, error-prone and easy to get wrong in exactly the places the tax department checks.</p>
          </Reveal>
          <div className="mk-grid four">
            {PROBLEMS.map((p, i) => <Reveal key={p.title} delay={i * 0.06}><article className="mk-card"><h3>{p.title}</h3><p>{p.body}</p></article></Reveal>)}
          </div>
        </section>

        <section className="mk-section tinted" id="how">
          <Reveal className="mk-intro">
            <p className="mk-eyebrow">How it works</p>
            <h2>From forty statements to one working paper.</h2>
            <p>Three steps. Most of the work happens in the first one, automatically.</p>
          </Reveal>
          <div className="mk-steps">
            {STEPS.map((s, i) => (
              <Reveal key={s.n} delay={i * 0.08}>
                <article className="mk-step">
                  <span className="mk-step-n">{s.n}</span>
                  <h3>{s.title}</h3>
                  <p>{s.body}</p>
                  <div className="mk-chips">{s.art.map(a => <span key={a}>{a}</span>)}</div>
                </article>
              </Reveal>
            ))}
          </div>
        </section>

        <section className="mk-section" id="features">
          <Reveal className="mk-intro">
            <p className="mk-eyebrow">Features</p>
            <h2>Built for the way Indian money actually moves.</h2>
            <p>UPI to a landlord, NACH dividends of ₹14, CRED paying three cards a month, a tax payment converted to EMI. LedgerVault understands the details that generic finance tools get wrong.</p>
          </Reveal>
          <div className="mk-grid four">
            {FEATURES.map((f, i) => (
              <Reveal key={f.title} delay={(i % 4) * 0.06}>
                <article className="mk-card feature"><span className="mk-icon" aria-hidden>{f.icon}</span><h3>{f.title}</h3><p>{f.body}</p></article>
              </Reveal>
            ))}
          </div>
        </section>

        <section className="mk-section dark" id="ca">
          <div className="mk-split">
            <Reveal>
              <p className="mk-eyebrow light">The handover</p>
              <h2>The working paper your CA actually wants.</h2>
              <p className="mk-lead light">One Excel workbook, organised the way an accountant reviews a return, with the evidence attached.</p>
              <ul className="mk-checks">
                <li><b>Summary by category</b> with notes for the relevant ITR heads and sections (80C, 80D, 24(b), other sources)</li>
                <li><b>By account and by card</b>: totals for every bank account and credit card, plus a category × account table</li>
                <li><b>Credit card reconciliation</b> with the yearly total to compare with AIS</li>
                <li><b>Audit findings</b> your CA would otherwise have to discover</li>
                <li><b>Every transaction</b> with its source file and row, your notes and its status</li>
              </ul>
              <button className="mk-btn lg light" onClick={primary}>{primaryLabel} <span aria-hidden>→</span></button>
            </Reveal>
            <Reveal delay={0.12}>
              <div className="mk-sheet" aria-label="Working paper excerpt, sample data">
                <div className="mk-tabs"><b>Summary</b><span>By account</span><span>Credit cards</span><span>Flags</span><span>Transactions</span></div>
                <table>
                  <thead><tr><th>Category</th><th>Out (₹)</th><th>In (₹)</th><th>ITR note</th></tr></thead>
                  <tbody>
                    <tr><td>Salary</td><td>—</td><td>18,24,000</td><td>Match with Form 16 / AIS</td></tr>
                    <tr><td>Interest received</td><td>—</td><td>41,230</td><td>Other sources · 80TTA</td></tr>
                    <tr><td>Dividend</td><td>—</td><td>6,118</td><td>Other sources · match AIS</td></tr>
                    <tr><td>Insurance premium</td><td>54,000</td><td>—</td><td>Possible 80C / 80D</td></tr>
                    <tr><td>Income tax paid</td><td>60,425</td><td>—</td><td>Match 26AS challans</td></tr>
                    <tr><td>Rent paid</td><td>3,60,000</td><td>—</td><td>Possible HRA / 80GG</td></tr>
                  </tbody>
                </table>
                <p className="mk-sheet-foot">Provisional · prepared for review by a Chartered Accountant · sample data</p>
              </div>
            </Reveal>
          </div>
        </section>

        <section className="mk-section" id="who">
          <Reveal className="mk-intro">
            <p className="mk-eyebrow">Who it’s for</p>
            <h2>For taxpayers who want to be ready, and the CAs who work with them.</h2>
          </Reveal>
          <div className="mk-grid three">
            {AUDIENCES.map((a, i) => <Reveal key={a.title} delay={i * 0.07}><article className="mk-card audience"><h3>{a.title}</h3><p>{a.body}</p></article></Reveal>)}
          </div>
        </section>

        <section className="mk-section tinted" id="security">
          <div className="mk-split top">
            <Reveal>
              <p className="mk-eyebrow">Security and privacy</p>
              <h2>Your financial life, on your own terms.</h2>
              <p className="mk-lead">Bank statements are some of the most sensitive documents you own. LedgerVault is designed so that they stay with you, and so every number stays explainable.</p>
            </Reveal>
            <div className="mk-grid two">
              {SECURITY.map((s, i) => <Reveal key={s.title} delay={(i % 2) * 0.06}><article className="mk-mini"><h3>{s.title}</h3><p>{s.body}</p></article></Reveal>)}
            </div>
          </div>
        </section>

        <section className="mk-section" id="faq">
          <div className="mk-split top">
            <Reveal>
              <p className="mk-eyebrow">FAQ</p>
              <h2>Questions, answered plainly.</h2>
            </Reveal>
            <div className="mk-faq">
              {FAQ.map((f, i) => (
                <div key={f.q} className={`mk-q ${open === i ? "open" : ""}`}>
                  <button onClick={() => setOpen(open === i ? null : i)} aria-expanded={open === i}>{f.q}<span aria-hidden>{open === i ? "−" : "+"}</span></button>
                  {open === i && <p>{f.a}</p>}
                </div>
              ))}
            </div>
          </div>
        </section>

        <section className="mk-final">
          <Reveal>
            <h2>Close the books on this financial year.</h2>
            <p>Upload your statements tonight. Walk into your CA’s office with the answers.</p>
            <div className="mk-cta center">
              <button className="mk-btn lg light" onClick={primary}>{primaryLabel} <span aria-hidden>→</span></button>
              {registrationOpen && <button className="mk-btn lg outline" onClick={onSignIn}>Sign in</button>}
            </div>
          </Reveal>
        </section>

        <footer className="mk-footer">
          <div>
            <a className="mk-brand" href="#top">Ledger<span>Vault</span></a>
            <p>Evidence-first ITR working papers.</p>
          </div>
          <nav><a href="#how">How it works</a><a href="#features">Features</a><a href="#security">Security</a><a href="#faq">FAQ</a><button className="mk-link" onClick={onSignIn}>Sign in</button></nav>
          <p className="mk-disclaimer">LedgerVault prepares working papers from your own statements. It does not file returns or provide tax advice. Tax treatment is provisional until reviewed by a Chartered Accountant.</p>
        </footer>
      </main>
    </MotionConfig>
  );
}
