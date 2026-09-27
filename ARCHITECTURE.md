# LedgerVault architecture

## Scope and boundaries

LedgerVault stores statement evidence and computes accountant-facing working papers. It does not determine tax deductibility, file an ITR, or make CA decisions. Amounts are `Decimal` end-to-end. There is no LLM, telemetry or external call.

## Components

`caddy` (TLS, security headers, 60 MB body limit) → `web` (Next.js standalone; UI plus `/api/*` rewrite) → `api` (FastAPI: auth, ingestion, reconciliation, reports) → `db` (PostgreSQL). Only Caddy publishes ports.

## Data model

`workspace` ← `user`, `financial_account` (bank | card), `source_document` (sha256, unique per workspace) ← `transaction` (source row number, date, narration, debit, credit, balance, category, category_source rule|user, note, status, match_group, financial_year) and `audit_event`. Schema changes are applied idempotently by `app/migrate.py` on start-up.

## Ingestion (`services/ingestion.py`)

Readers turn CSV (delimiter sniffed, UTF-8/cp1252), XLSX (openpyxl), XLS (xlrd) and ZIP (validated: no absolute or `..` paths, ≤500 members, ≤250 MB) into rows. The parser scans the first 60 rows for a header containing date, narration and debit/credit or amount columns, using the synonym lists in `COLUMNS`, which cover HDFC, ICICI, SBI, Axis and Kotak style exports. It handles Dr/Cr columns and suffixes, Indian number formats, multi-line narrations, and footer/summary rows. The financial year is derived from each transaction date (April–March). Duplicate files are skipped by hash. Rows already imported for the same account from another file (overlapping periods) are skipped by (date, narration, amount).

## Classification (`services/rules.py`)

Ordered, direction-aware regex rules map narrations to categories. Each category has a group (income, tax, deduction hint, investment, expense, neutral, review) and an ITR hint. On a card account, payment-like credits are card settlements. User edits set `category_source=user` and are never overwritten.

## Reconciliation (`services/reconciliation.py`)

Recomputed from scratch for the workspace after every import or edit. A card-bill debit is linked to a card-payment credit in another account with the same amount within −2…+7 days. A self-transfer debit is linked to a credit in another account within −1…+3 days. A link is made only when the pair is unique in both directions; otherwise the entry is marked `ambiguous`. Statuses: ok, needs_review, unmatched, ambiguous, confirmed_settlement, confirmed_transfer.

## Reports (`services/report.py`)

These produce FY totals (card settlements and self-transfers are excluded; refunds net off spending), a category summary, audit flags (unmatched settlements, unidentified credits ≥ ₹2 lakh, cash deposits and card payments against the ₹10 lakh SFT thresholds, interest/dividends/salary reminders, months with no statement), and the XLSX export.

## Security model

Owner registration closes after the first user unless `ALLOW_REGISTRATION=true`. Sessions are HMAC-signed tokens (24 h). The API refuses to start with a default or short `JWT_SECRET` on PostgreSQL. Login is rate-limited per email. Every data route is workspace-scoped and tested for cross-workspace isolation. Containers run as non-root, and OpenAPI docs are disabled.

## Next milestones

1. PDF statements (text tables first, OCR later) with password support, built from real redacted fixtures.
2. AIS / 26AS / Form 16 import and a reconciliation of bank credits against AIS.
3. CA role with question threads; HttpOnly cookie sessions and CSRF protection.
4. Encrypted backups, a restore drill, and encryption at rest.
