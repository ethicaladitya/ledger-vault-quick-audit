# LedgerVault architecture

## Scope and boundaries

LedgerVault stores immutable source evidence and computes accountant-facing working papers. It does not infer tax deductibility, file an ITR, or make CA decisions. Amounts use `Decimal` throughout. There is no LLM, telemetry or external AI call.

## Components

`web` (Next.js) calls `/api`; `api` (FastAPI) owns validation, ingestion and reconciliation; `db` (PostgreSQL) holds metadata and normalized records. Source documents are held under a protected volume with their SHA-256 recorded. A future worker process will claim persisted `import_jobs` rows using `FOR UPDATE SKIP LOCKED`; the current vertical slice runs the same idempotent pipeline synchronously.

## Data model

The baseline schema includes workspace, financial_account, source_document, statement, source_row, transaction, reconciliation_group, reconciliation_link and audit_event. `source_row` is append-only original evidence. `transaction` is normalized, carries source location and links. Manual corrections must create audit events rather than mutate evidence. Migration: `backend/alembic/versions/0001_initial.py`.

## Reconciliation policy

The engine links only when evidence is unique: a bank debit and card credit must agree on amount, sit in the configurable date window, and have payment evidence in narration. Exact references would be a stronger future tier. Tied candidates are marked `ambiguous`, never selected. Linked own-account transfers and card settlements are neutral. Underlying card purchases remain expenses. Re-imported document hashes do not create additional transactions.

## Import interfaces

`StatementParser.parse(path) -> ParsedStatement` is the adapter contract. The shipped generic parser detects common CSV delimiters and maps date/narration/debit/credit/amount/balance columns. It emits warnings rather than inventing fields. ZIP validation rejects absolute/parent paths, more than 500 members, or more than 250 MB expanded. PDF/XLS legacy and OCR are extension points pending tested fixtures.

## Security model

The production path requires authenticated Owner/Accountant users, workspace-scoped authorization on every account/document, secure cookies, CSRF protections, TLS and encrypted backups. Deployment uses least-privilege containers, read-only import mounts and no secrets in image layers. API error logging must omit document text, paths, passwords and rows. The current demo mode intentionally has no login; do not place real statements on a public endpoint.

## Milestones

1. Evidence-first CSV/XLSX ingestion, dedupe, card settlement reconciliation and review UI — implemented.
2. Persisted worker, PDFs/OCR, tested bank adapters and upload UX.
3. Auth/RBAC, CA questions, manual override history and audit UX.
4. AIS/26AS inputs, export pack, encrypted backups and restore drill.

## Test plan

Unit tests cover categorization and matching. The integration test imports a bank payment and a next-day card credit plus purchases; it asserts one neutral settlement and no duplicated import. Fixtures contain no personal data. Before enabling a bank adapter, add PDF/table fixtures covering multi-line narrations, opposite conventions, missing fields and duplicate dates.
