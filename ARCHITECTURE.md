# LedgerVault architecture

## Scope and boundaries

LedgerVault stores statement evidence and computes accountant-facing working papers. It does not determine tax deductibility, file an ITR, or make CA decisions. Amounts are `Decimal` end-to-end. There is no LLM, telemetry or external call.

## Components

`caddy` (TLS, security headers, 60 MB body limit) → `web` (Next.js standalone; UI plus `/api/*` rewrite) → `api` (FastAPI: auth, ingestion, reconciliation, reports) → `db` (PostgreSQL). Only Caddy publishes ports.

## Data model

`workspace` ← `user`, `financial_account` (bank | card), `source_document` (sha256, unique per workspace) ← `transaction` (source row number, date, narration, debit, credit, balance, category, category_source rule|user, note, status, match_group, financial_year) and `audit_event`. Schema changes are applied idempotently by `app/migrate.py` on start-up.

## Ingestion (`services/ingestion.py`)

Readers turn CSV (delimiter sniffed, UTF-8/cp1252), XLSX (openpyxl), XLS (xlrd) and ZIP (validated: no absolute or `..` paths, ≤500 members, ≤250 MB) into rows. The parser scans the first 60 rows for a header containing date, narration and debit/credit or amount columns, using the synonym lists in `COLUMNS`, which cover HDFC, ICICI, SBI, Axis and Kotak style exports. It handles Dr/Cr columns and suffixes, Indian number formats, multi-line narrations, and footer/summary rows. The financial year is derived from each transaction date (April–March). Duplicate files are skipped by hash. Rows already imported for the same account from another file (overlapping periods) are skipped by (date, narration, amount).

## PDFs (`services/pdf.py`, `services/passwords.py`)

`unlock` tries candidate passwords with pikepdf: empty, then passwords the user typed, then formulas built from the name, date of birth, PAN and card/customer numbers supplied with the request. These hints live only in request memory. `read_pdf` (pdfplumber) extracts text and tables; image-only PDFs are rejected. `detect` scores card markers (minimum amount due, credit limit…) against bank markers (IFSC, opening balance…) and finds the institution and last four digits, which gives auto-names like "HDFC Bank Credit Card ••9876". Extraction first tries tables through the spreadsheet header mapper, then parses date-led text lines. For bank statements, the running-balance delta decides debit or credit. `balance_gaps` checks that each row's balance follows from the one before (newest-first statements too); when the reading with the most rows breaks the chain, a reading of about as many rows whose balances carry through is used instead, and any remaining break is reported with its dates ("Running balance breaks … 21 Apr 2025 → 03 Oct 2025"), since that is where pages were skipped. The audit then says a month inside an uploaded statement's dates was not read, rather than calling it a missing statement, and Statement coverage marks such months. For card statements, `card_totals_check` requires previous balance + purchases − payments/credits = total due for amounts printed outside the transaction lines; when nothing fits, the import warns that the statement doesn't add up (rows missing or signs flipped). HDFC's `+ ₹` credits (the ₹ glyph extracts as "C") and descriptions printed above the date line are handled explicitly. `python -m app.tools.inspect_folder <dir>` writes a masked layout report (digits → 9, words → Xxxx) for adding a new layout without sharing personal data. `python -m app.tools.coverage_report --fy 2025-26` prints, from the database, rows per account and month and each file's span, empty months and warning types: counts and dates only.

## Post-upload review and learning

`GET /imports/review` groups the uploaded rows by `merchant_key` (the narration with codes, card numbers, references and dates removed) and category. `POST /imports/confirm` marks them user-confirmed and stores `user_rules` for groups the user changed. `PATCH /transactions/{id}` with `apply_similar` does the same for one payee. Learned rules take precedence over built-in rules on later imports. When `RULES_VERSION` changes, rule-categorised rows (never user-set ones) are re-classified on start-up.

## Business vs personal (`services/purpose.py`)

`workspace.business_mode` switches the UI on. Each account has `purpose` (business | personal | mixed), and each transaction has `purpose` (business | personal | unknown | neutral) with `purpose_source` (rule | user). `apply_purposes` runs at the end of every reconcile and recomputes rule-sourced purposes in this order: payee rules the user taught (`purpose_rules`); then the account's use, where business accounts keep clearly personal categories personal and personal accounts keep business-by-nature categories business; then the category (software, ads, courier, office, professional fees, GST, gateway receipts → business; groceries, dining, medical, salary, dividends, investments… → personal); then narration hints (GSTIN, invoice, vendor). Anything else stays unknown. `/report` and `/export.xlsx` accept `purpose=business|personal`; the report states how many rows were excluded as the other purpose or unknown.

## Duplicate statements

Identical files are skipped by SHA-256 per workspace. Rows overlapping an earlier statement of the same account are skipped by (date, amount, direction, narration prefix). Before creating a new account, `find_same_statement` checks whether at least 80% of the file's (date, debit, credit) rows (minimum 3, measured against the smaller side) already exist in one account. If so, it's the same statement in another format or a re-download, and it's merged there instead of being counted twice.

## Classification (`services/rules.py`)

Ordered, direction-aware regex rules map narrations to categories. Each category has a group (income, tax, deduction hint, investment, expense, neutral, review) and an ITR hint. `category_fits` keeps categories to the direction they make sense in: a credit on a card is only a bill payment, a refund or an EMI conversion (never income), a card debit is never a bill payment, and a learned payee rule is ignored in the other direction. User edits set `category_source=user` and are never overwritten.

## Reconciliation (`services/reconciliation.py`)

Recomputed from scratch for the workspace after every import or edit. A card-bill debit is linked to a card-payment credit in another account with the same amount within −2…+7 days; payment credits still open are then matched to bank debits labelled BBPS / auto-debit / UPI / NEFT / uncategorised (CRED payments rarely name the card). A link that relabels a leg sets `category_source=link`, which is undone at the start of every run. A self-transfer debit is linked to a credit in another account within −1…+3 days. A link is made only when the pair is unique in both directions; otherwise the entry is marked `ambiguous`. Statuses: ok, needs_review, unmatched, ambiguous, confirmed_settlement, confirmed_transfer.

## Reports (`services/report.py`)

These produce FY totals (card settlements and self-transfers are excluded; refunds net off spending), a category summary, the Books ledger (`books`: every bank and card row once in date order with a running net, both legs of card bills, self-transfers and card EMI conversions left out and totalled, bill payments to cards with no statement listed as missing spending), audit flags (unmatched settlements, unidentified credits ≥ ₹2 lakh, cash deposits and card payments against the ₹10 lakh SFT thresholds, interest/dividends/salary reminders, months with no statement), and the XLSX export.

## Security model

Owner registration closes after the first user unless `ALLOW_REGISTRATION=true`. Sessions are HMAC-signed tokens (24 h). The API refuses to start with a default or short `JWT_SECRET` on PostgreSQL. Login is rate-limited per email. Every data route is workspace-scoped and tested for cross-workspace isolation. Containers run as non-root, and OpenAPI docs are disabled.

## Next milestones

1. OCR for scanned statements, and more bank-specific PDF layouts built from redacted fixtures.
2. AIS / 26AS / Form 16 import and a reconciliation of bank credits against AIS.
3. CA role with question threads; HttpOnly cookie sessions and CSRF protection.
4. Encrypted backups, a restore drill, and encryption at rest.
