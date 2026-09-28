# AGENTS.md — LedgerVault

Guide for AI coding agents (and humans) working on this repo. Read this before changing anything.
For deeper detail see `ARCHITECTURE.md`; for user-facing docs see `README.md`.

## 1. What this product is for

LedgerVault turns a year of Indian **bank and credit-card statements** into **CA-ready working papers** for filing an
ITR. A user uploads every statement they have (PDF, CSV, XLS/XLSX or a ZIP of them). The app:

1. reads them, including password-protected PDFs, and works out which account each one belongs to;
2. categorises every transaction (salary, dividends, interest, rent, tax paid, 80C/80D hints, spending…);
3. lets the user confirm or correct the categories, and learns from their corrections;
4. reconciles money moving between their own accounts, so nothing is **counted twice** (card bill payments,
   self-transfers, card EMIs);
5. flags what a CA will ask about (missing statements, unexplained large credits, SFT thresholds, unmatched payments);
6. produces a **Report** (a checklist, final books by ITR head, and details) and an **Excel export** for the CA;
7. optionally separates **business and personal** money for freelancers and small business owners.

**The goal is to make the user's and their CA's life easier.** Every feature should answer: *does this make the final
books more correct, or easier for a CA to trust?*

### Non-goals and hard boundaries
- It does **not** decide tax treatment, compute tax or file returns. ITR hints are prompts for review, never
  determinations.
- **No LLMs, telemetry or external calls.** Classification is deterministic regex rules plus the user's learned rules.
- Capital gains and F&O are out of scope (the broker's P&L statement is the source for those).
- Money is `Decimal` end-to-end. Never use floats for amounts in the backend.

## 2. Privacy rules (the repo is public)

- **Never commit** personal data: real statements, names, PANs, DOBs, account or card numbers, server IPs, hostnames,
  SSH key paths, `.env` or `.deploy.env`. `.gitignore` blocks `*.pdf *.csv *.xls* *.zip *.pem .env* .deploy.env`;
  `sample-data/*.csv` is synthetic and the only exception.
- Test fixtures must be synthetic (see `backend/tests/pdf_fixtures.py`).
- To debug a real PDF layout, use the masking tools, which turn digits into 9 and words into Xxxx:
  `python -m app.tools.inspect_pdf <file.pdf> [--name --dob --pan]` or `python -m app.tools.inspect_folder <dir>`.
  Unreadable PDFs also log a masked `PDF-LAYOUT-BEGIN … END` block.
- Password hints (name, DOB, PAN, extras) exist **only in request memory**. Never store or log them.
- Registration is closed after the first user unless `ALLOW_REGISTRATION=true`. The owner has chosen to keep it
  private, so don't change that default.

## 3. Architecture at a glance

```
caddy (TLS, headers, 60 MB body limit)
  → web  (Next.js 15 standalone; UI + /api/* rewrite)
    → api (FastAPI: auth, ingestion, reconciliation, reports)
      → db  (PostgreSQL 16; SQLite in local dev/tests)
```
Only Caddy publishes ports. The containers run as non-root. The OpenAPI docs are disabled.

### Repo map
| Path | What it does |
|---|---|
| `backend/app/main.py` | All HTTP routes. Every data route depends on `current_user` and filters by `workspace_id`. |
| `backend/app/models.py` | SQLAlchemy models: Workspace, User, TaxYear, FinancialAccount, SourceDocument, Statement, Transaction, AuditEvent, AppMeta, UserRule, PurposeRule. |
| `backend/app/migrate.py` | Idempotent schema upgrades on start-up (`ADDED_COLUMNS`) and re-classification when `RULES_VERSION` changes. |
| `backend/app/security.py` | Password hashing, HMAC-signed bearer tokens (24 h), login rate limit, and a refusal to run with a weak `JWT_SECRET` on Postgres. |
| `backend/app/services/ingestion.py` | File readers (CSV/XLS/XLSX/ZIP), the header mapper, `import_file`, and duplicate handling. |
| `backend/app/services/pdf.py` | PDF unlock, text/table extraction, bank/card detection, line parsers, and card totals check. |
| `backend/app/services/passwords.py` | Candidate PDF passwords built from the name, DOB, PAN and extras. |
| `backend/app/services/rules.py` | `CATEGORIES`, ordered regex `RULES`, `classify`, `merchant_key`, `category_fits`, and `RULES_VERSION`. |
| `backend/app/services/reconciliation.py` | `reconcile()`: links card bills, statement payments and self-transfers; sets statuses. |
| `backend/app/services/purpose.py` | Business/personal purpose (`apply_purposes`, which runs at the end of every reconcile). |
| `backend/app/services/report.py` | Totals, flags, books, coverage, card reconciliation, final heads, closing checklist, and the XLSX export. |
| `backend/app/services/masking.py` | Masks text for layout sharing. |
| `backend/tests/` | pytest suite (API, parsers, PDFs, books, CRED matching, e2e). |
| `web/app/page.tsx` | App shell: landing → auth → workspace, sidebar navigation. |
| `web/app/views.tsx` | All screens: Overview, Upload (with import review), Coverage, Transactions, Books, Reconciliation, Report, Settings. |
| `web/app/lib.ts` | API client (`makeApi`), shared types and `money()`. |
| `web/app/landing.tsx`, `landing.css` | Marketing site (styles scoped under `.mk`). |
| `web/app/style.css` | App styles. |
| `setup.sh`, `deploy.sh`, `remote-deploy.sh` | First-time server setup, redeploy on the server, and deploy from a laptop over rsync+ssh. |

## 4. How the pipeline works

### 4.1 Upload → import (`POST /imports/upload`)
- The request carries files plus an optional `account_name` and `kind` (`auto|bank|card`), and password hints
  (`name`, `dob`, `pan`, `extras`, `password`).
- `import_file` works like this for each file (a ZIP expands into its members, validated against path traversal and
  size limits):
  1. **SHA-256 dedupe** per workspace. An identical file is skipped with the result "Already imported as …".
  2. `load()` reads the file. For a PDF, `unlock` tries these passwords in order: empty, the typed password, then
     formulas from `passwords.candidates` (first 4 letters of the name in several cases + DDMM/DDMMYYYY/…, PAN, PAN+DOB,
     and card last-4 combinations). If none works, the result has `needs_password: true`.
  3. `detect()` scores card markers against bank markers and finds the institution and last 4 digits. That gives an
     auto-name like "HDFC Bank Credit Card ••1234".
  4. Parsing:
     - Spreadsheets: a header row is found in the first 60 rows using the synonym lists in `COLUMNS`.
     - PDFs: `parse_pdf` tries six strategies (tables, aligned tables, text lines, layout lines, and loose versions of
       the two line readers) and keeps the best. For a card statement, a reading that adds up against previous
       balance + purchases − payments = total due wins. `clean_line` strips icons, `(cid:N)` glyphs and stray dots,
       and treats a trailing `+` as a credit.
     - Bank PDFs use the running-balance delta to decide debit or credit.
  5. **Cross-file dedupe**: `find_same_statement` detects when ≥80% of the rows already exist in another account; the
     file is then merged into that account instead of creating a second one. Rows overlapping an earlier statement of
     the same account are skipped by (date, narration, amount).
  6. Each row gets `classify()`'d, taking the workspace's learned `UserRule`s into account.
- After all files are imported, `reconcile()` runs. The response lists per-file results (rows, account, period,
  warnings) for the UI.

### 4.2 Review and learning
- `GET /imports/review` groups new rows by `merchant_key` + category. `POST /imports/confirm` marks them as
  user-confirmed and stores `UserRule`s for groups the user changed. This is the confirm screen after an upload.
- `PATCH /transactions/{id}` changes a category, note or purpose. With `apply_similar`, the change is learned for that
  payee.
- **Order of precedence:** the user's own choice > learned payee rule > built-in rule. Rows with
  `category_source=user` are never overwritten.
- Categories are direction-aware (`category_fits`):
  - a card credit can only be a bill payment, a refund or an EMI;
  - a card debit is never a bill payment;
  - income categories are only valid for credits.

### 4.3 Categories (`rules.py`)
- Each category has a **group**: income, tax, deduction_hint, investment, expense, neutral, adjustment or review.
  Each also has an **ITR hint**.
- `NEUTRAL = {card_settlement, own_transfer, card_emi}`. These are never income or spending, and are left out of
  totals.
- Categories in the `review` group (uncategorised, unidentified UPI/NEFT, BBPS, auto-debit) are what "needs a
  category" means.
- **Whenever you change `RULES` or `CATEGORIES`, bump `RULES_VERSION`.** On start-up, rows categorised by rules
  (never user rows) are then re-classified and every workspace is re-reconciled.

### 4.4 Reconciliation (`reconcile`, runs after every import or edit)
Everything is recomputed from scratch for the workspace. Link-made relabels (`category_source=link`) are undone
first. The steps, in order:
1. **Card bills**: a bank debit labelled `card_settlement` is matched to a card payment credit of the same amount,
   −2…+7 days apart.
2. Open card credits are matched to generic bank debits (BBPS, UPI to CRED, NEFT, auto-debit, uncategorised). A match
   relabels the debit as `card_settlement`.
3. Near-amount matches (CRED coins or a few rupees of fees), −1…+3 days apart.
4. A card credit worded like a refund that is exactly one bill payment's other leg is relabelled as a settlement.
5. **statement_paid**: a bank payment that pays an uploaded card statement's `total_due` (within 35 days of the
   statement's last transaction).
6. **Self-transfers**: an `own_transfer` debit is matched to a credit in another account, −1…+3 days apart.
7. A link is made only when the pair is unique in both directions; otherwise the status is `ambiguous`.
8. `apply_purposes()`.

Statuses are: `ok`, `needs_review`, `unmatched`, `ambiguous`, `confirmed_settlement`, `confirmed_transfer` and
`statement_paid`.

### 4.5 Business vs personal (`purpose.py`)
Only active when `workspace.business_mode` is on. Each account has a purpose of business, personal or mixed. Each
transaction gets one of business, personal, unknown or neutral. They are decided in this order:
1. the user's own choice;
2. a learned `PurposeRule`;
3. the account's use;
4. the category (e.g. software or advertising means business; salary or groceries means personal);
5. narration hints (GSTIN, invoice…).

Anything else stays `unknown` and is reported as excluded, never silently dropped.

### 4.6 Reports (`report.py`, `GET /report`, `/books`, `/coverage`, `/export.xlsx`)
- **totals**: income, expenses, refunds (net against spending), and neutral flows excluded.
- **closing_checklist**, shown at the top of the Report page as "Before you close the books". It covers:
  - statement gaps and missing card statements;
  - rows that need a category;
  - unmatched or ambiguous payments;
  - credits of ₹2 lakh or more with no note;
  - unknown purpose, in business mode.

  Each item carries an action the UI turns into a **Fix →** button.
- **final_heads**: income by head, tax paid, possible deductions, and spending by category.
- **books**: every bank and card row once, in date order with a running net. Neutral legs are excluded and totalled.
  Bills paid to cards with no uploaded statement are listed as missing spending.
- **card_reconciliation / missing_card_statements / card_hint**: finds card bills paid from the bank whose card
  statement was never uploaded. UPI handles and debit-card POS digits are ignored when guessing the card.
- **statement_coverage**: a month-by-account grid of uploaded statements, showing gaps and bad reads.
- **flags**: unmatched settlements, big unexplained credits, cash and card spend near the ₹10 lakh SFT limits,
  interest/dividend/salary reminders to match with AIS, and months with no statement.
- **export_xlsx**: sheets for Summary, By account, Credit cards, Flags and Transactions.
- `/report` and `/export.xlsx` accept `fy`, `account_id` and `purpose=business|personal`.

## 5. Invariants — don't break these

1. **No double counting.** Card bill payments, self-transfers and card EMIs are never income or spending. A
   statement uploaded twice, in another format or with an overlapping period must not add rows twice.
2. **Workspace isolation.** Every query goes through `workspace_id`. Unauthenticated calls return 401. Cross-workspace
   IDs return 404. There are tests for this, so keep them passing and add one for any new route.
3. **User choices win.** Never overwrite `category_source=user` or `purpose_source=user`.
4. **Deterministic and offline.** No network calls and no randomness in classification.
5. **Decimal money.** Amounts are strings in JSON and `Decimal` in Python.
6. **Schema changes** go into `migrate.ADDED_COLUMNS`, since there is no Alembic. They must be idempotent and work on
   both SQLite and Postgres.
7. **Nothing disappears silently.** Anything excluded from a total is counted and shown somewhere: the neutral strip,
   the excluded list or the flags.

## 6. Developing

```sh
# API on :8000 (SQLite locally)
cd backend && pip install -r requirements-dev.txt && uvicorn app.main:app --reload
# UI on :3000
cd web && npm install && API_URL=http://localhost:8000 npm run dev
# Tests (must pass before every push)
cd backend && pytest -q
# Type-check and build the UI (catches Next.js page-export errors)
cd web && npm run build
```
- In the app, **Try with sample data** loads `sample-data/bank.csv` and `card.csv`.
- New parsing behaviour needs a synthetic test in `tests/test_parsers.py` or `tests/test_pdf.py`. New report logic
  needs a test in `tests/test_api.py` or `tests/test_books.py`.
- `page.tsx` must only export the default component, because Next.js rejects extra exports from a page. Shared UI
  code goes in `views.tsx` or `lib.ts`.
- Deploy scripts must stay **ASCII-only** and use `${braced}` variables, because macOS ships bash 3.2.

## 7. Deploying

- **New server:** clone the repo, run `SITE_ADDRESS=your.domain ./setup.sh` (it writes `.env` with random
  secrets) and it starts the stack.
- **Update on the server:** `./deploy.sh` rebuilds the images, runs `docker compose up -d` and waits for `/health`.
- **Update from a laptop:** `./remote-deploy.sh user@host /path [key]`, or with no arguments it reads the git-ignored
  `.deploy.env` (`DEPLOY_TARGET`, `DEPLOY_DIR`, `DEPLOY_KEY`). It rsyncs **git-tracked files only** and then runs
  `deploy.sh` remotely. It refuses to run with uncommitted changes.
- Database upgrades run automatically on API start-up.

## 8. Working conventions

- Several agents work on this repo (e.g. Claude and Codex). **Always `git fetch origin main` and merge or
  fast-forward before pushing.** Never force-push `main`.
- Match the existing style: compact functions, docstrings that explain *why*, and short comments.
- UI copy is written for a non-accountant user and their CA. Explain plainly what a number means and what to do next.
- Don't put model names, personal details or server details in commits, code or docs.

## 9. Roadmap (from ARCHITECTURE.md)

1. OCR for scanned statements, and more bank-specific PDF layouts built from masked fixtures.
2. AIS / 26AS / Form 16 import, and a reconciliation of bank credits against AIS.
3. A CA role with question threads; HttpOnly cookie sessions and CSRF protection.
4. Encrypted backups, a restore drill, and encryption at rest.
