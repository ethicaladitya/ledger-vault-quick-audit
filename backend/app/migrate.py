"""Idempotent schema upgrade. Runs on API start-up and via `python -m app.migrate`."""
from sqlalchemy import inspect, text
from .database import Base, engine
from . import models  # noqa: F401  (registers tables)

# (table, column, DDL type) added after the first deployment.
ADDED_COLUMNS = [
    ("transactions", "financial_year", "VARCHAR(9) DEFAULT '2026-27' NOT NULL"),
    ("transactions", "balance", "NUMERIC(18,2)"),
    ("transactions", "category_source", "VARCHAR(8) DEFAULT 'rule' NOT NULL"),
    ("transactions", "note", "TEXT"),
    ("source_documents", "workspace_id", "INTEGER REFERENCES workspaces(id)"),
    ("source_documents", "account_id", "INTEGER REFERENCES financial_accounts(id)"),
    ("source_documents", "row_count", "INTEGER DEFAULT 0 NOT NULL"),
    ("audit_events", "workspace_id", "INTEGER REFERENCES workspaces(id)"),
]


def run():
    Base.metadata.create_all(engine)
    inspector = inspect(engine)
    postgres = engine.url.get_backend_name() == "postgresql"
    added = set()
    with engine.begin() as conn:
        for table, column, ddl in ADDED_COLUMNS:
            if column not in {c["name"] for c in inspector.get_columns(table)}:
                conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}"))
                added.add((table, column))
        # Back-fill ownership for documents imported before workspace scoping.
        conn.execute(text(
            "UPDATE source_documents SET workspace_id = (SELECT fa.workspace_id FROM transactions t "
            "JOIN financial_accounts fa ON fa.id = t.account_id WHERE t.document_id = source_documents.id LIMIT 1), "
            "account_id = (SELECT t.account_id FROM transactions t WHERE t.document_id = source_documents.id LIMIT 1) "
            "WHERE workspace_id IS NULL"))
        conn.execute(text("UPDATE source_documents SET row_count = (SELECT COUNT(*) FROM transactions t WHERE t.document_id = source_documents.id) WHERE row_count = 0"))
        conn.execute(text("UPDATE transactions SET status = 'ok' WHERE status = 'unmatched' AND category NOT IN ('card_settlement', 'own_transfer')"))
        if postgres:
            # The original schema made sha256 globally unique, which leaked across workspaces.
            conn.execute(text("ALTER TABLE source_documents DROP CONSTRAINT IF EXISTS source_documents_sha256_key"))
            conn.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS uq_workspace_document ON source_documents (workspace_id, sha256)"))

    if ("transactions", "category_source") in added:
        _reclassify_legacy_rows()


def _reclassify_legacy_rows():
    """Rows imported before v0.2 used the old rules (e.g. every UPI payment was 'dining')."""
    from .database import SessionLocal
    from .models import Transaction, FinancialAccount, Workspace
    from .services.rules import classify
    from .services.reconciliation import reconcile
    with SessionLocal() as db:
        kinds = {a.id: a.kind for a in db.query(FinancialAccount)}
        for t in db.query(Transaction):
            t.category = classify(t.narration, t.debit > 0, kinds.get(t.account_id, "bank"))
        db.commit()
        for (ws_id,) in db.query(Workspace.id):
            reconcile(db, ws_id)


if __name__ == "__main__":
    run()
