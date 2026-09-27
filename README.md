# LedgerVault

LedgerVault is a private, evidence-first ITR working-paper application for an Indian taxpayer and their CA. It is not tax-filing software and every tax treatment remains provisional until a CA reviews it.

## What is implemented now

- FastAPI API with PostgreSQL-ready SQLAlchemy schema and Alembic baseline migration
- recursive, bounded folder ingestion for CSV/XLSX plus ZIP safety validation; raw file SHA-256, rows and source locations are preserved
- deterministic Indian narration classification and global transfer/card-settlement matching
- duplicate prevention, statement coverage and balance validation signals
- a responsive Next.js workspace with overview, transaction review and reconciliation screens
- synthetic end-to-end fixture proving a ₹35,000 bank-to-card settlement is neutral while card purchases count once

PDF text/OCR adapters, authenticated multi-user RBAC, CA question threads and full XLSX/PDF handover exports are deliberately staged next; they are described in `ARCHITECTURE.md` rather than presented as done.

## Run locally

```sh
cp .env.example .env
docker compose up --build
```

Open `http://localhost`. The API docs are at `/api/docs`.

To import an explicitly mounted directory: `POST /api/imports/folder` with `{ "path": "/imports" }`. The compose configuration only mounts `./sample-data` read-only as `/imports`; add trusted host directories explicitly to `docker-compose.yml` before use. Browsers never provide arbitrary server paths.

## Security notes

No financial data leaves the host. File inputs are size-limited and ZIP members are validated for path traversal, member count and decompressed size. Do not expose this initial deployment publicly until TLS, firewall rules, secret rotation and a reverse proxy policy are in place. Password-protected PDF support and encryption-at-rest are planned before production use.

## Tests

```sh
cd backend && pytest -q
```

## Adding an institution adapter

Add a parser implementing `StatementParser` in `backend/app/services/ingestion.py`, include real redacted/synthetic layout fixtures, and register it only after regression tests pass. The generic CSV/XLSX mapper is intentionally the only adapter currently advertised as supported.
