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
    ("workspaces", "business_mode", "BOOLEAN DEFAULT FALSE NOT NULL"),
    ("financial_accounts", "purpose", "VARCHAR(10) DEFAULT 'mixed' NOT NULL"),
    ("transactions", "purpose_source", "VARCHAR(8) DEFAULT 'rule' NOT NULL"),
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

    reclassify_if_rules_changed()


def reclassify_if_rules_changed():
    """Re-apply narration rules to rule-categorised rows when RULES_VERSION changes; user choices are kept."""
    from .database import SessionLocal
    from .models import AppMeta, Transaction, FinancialAccount, Workspace, UserRule
    from .services.rules import RULES_VERSION, classify
    from .services.reconciliation import reconcile
    with SessionLocal() as db:
        meta = db.get(AppMeta, "rules_version")
        if meta and meta.value == str(RULES_VERSION):
            return
        accounts = {a.id: a for a in db.query(FinancialAccount)}
        learned: dict[int, dict[str, str]] = {}
        for r in db.query(UserRule):
            learned.setdefault(r.workspace_id, {})[r.key] = r.category
        for t in db.query(Transaction).filter(Transaction.category_source != "user"):
            a = accounts.get(t.account_id)
            t.category = classify(t.narration, t.debit > 0, a.kind if a else "bank", learned.get(a.workspace_id) if a else None)
        if meta:
            meta.value = str(RULES_VERSION)
        else:
            db.add(AppMeta(key="rules_version", value=str(RULES_VERSION)))
        db.commit()
        for (ws_id,) in db.query(Workspace.id):
            reconcile(db, ws_id)


if __name__ == "__main__":
    run()
