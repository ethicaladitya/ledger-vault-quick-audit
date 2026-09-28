"""Read-only health check of what is in the database: rows per account and month, and how each file was read.

Prints counts and dates only: no amounts, narrations or file names (files are numbered), so the output
can be shared when something looks wrong, e.g. "no transactions in May, Jun..." for a statement you uploaded.

    docker compose exec api python -m app.tools.coverage_report [--fy 2025-26]
"""
import argparse
from collections import Counter, defaultdict

MONTHS = [4, 5, 6, 7, 8, 9, 10, 11, 12, 1, 2, 3]
NAMES = ["Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec", "Jan", "Feb", "Mar"]
KNOWN = ["Running balance breaks", "Doesn't add up", "Only one transaction was read", "merged there instead",
         "already imported", "inferred from", "Read from PDF text", "Skipped"]


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--fy", default=None, help="financial year, e.g. 2025-26 (default: every year)")
    args = ap.parse_args(argv)
    from app.database import SessionLocal
    from app.models import FinancialAccount, SourceDocument, Transaction
    with SessionLocal() as db:
        q = db.query(Transaction.account_id, Transaction.document_id, Transaction.txn_date)
        if args.fy:
            q = q.filter(Transaction.financial_year == args.fy)
        per_month = defaultdict(Counter)
        doc_dates = defaultdict(list)
        for acc, doc, d in q:
            per_month[acc][(d.year, d.month)] += 1
            doc_dates[doc].append(d)
        accounts = db.query(FinancialAccount).order_by(FinancialAccount.workspace_id, FinancialAccount.kind, FinancialAccount.name).all()
        docs = db.query(SourceDocument).order_by(SourceDocument.id).all()
        start = int(args.fy[:4]) if args.fy else None
        for a in accounts:
            print(f"\n== [{a.kind}] {a.name}  (workspace {a.workspace_id}, account {a.id}) ==")
            if start:
                cells = [f"{NAMES[i]}:{per_month[a.id][(start + (m < 4), m)]:>3}" for i, m in enumerate(MONTHS)]
                print("   rows per month: " + "  ".join(cells))
            else:
                print("   rows per month: " + ", ".join(f"{y}-{m:02d}:{n}" for (y, m), n in sorted(per_month[a.id].items())))
            for n, doc in enumerate(docs, 1):
                if doc.account_id != a.id:
                    continue
                dates = doc_dates.get(doc.id, [])
                span = f"{min(dates)} to {max(dates)}" if dates else "no rows in this year"
                months = {(d.year, d.month) for d in dates}
                empty = []
                if dates:
                    y, m = min(dates).year, min(dates).month
                    while (y, m) <= (max(dates).year, max(dates).month):
                        if (y, m) not in months:
                            empty.append(f"{y}-{m:02d}")
                        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
                notes = [k for k in KNOWN if k in (doc.warnings or "")]
                print(f"   file {n}: {doc.row_count} rows stored, {span}"
                      + (f"; NO ROWS for {', '.join(empty)} inside that span" if empty else "")
                      + (f"; warnings: {', '.join(notes)}" if notes else ""))
        orphans = sum(1 for d in docs if d.account_id is None)
        if orphans:
            print(f"\n{orphans} file(s) are not attached to any account.")


if __name__ == "__main__":
    main()
