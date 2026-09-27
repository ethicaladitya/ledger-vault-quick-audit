"""Links the two legs of card bill payments and own-account transfers.

Runs over the whole workspace and is idempotent: every run recomputes links and
statuses from scratch. A link is made only when the pairing is unique in both
directions; ties are marked `ambiguous` and never guessed.

Statuses: ok | needs_review | unmatched | ambiguous | confirmed_settlement | confirmed_transfer
"""
from uuid import uuid4
from sqlalchemy.orm import Session
from ..models import Transaction, FinancialAccount, AuditEvent
from .rules import MATCHED, NEUTRAL, REVIEW
from .purpose import apply_purposes

WINDOWS = {"card_settlement": (-2, 7), "own_transfer": (-1, 3)}


def base_status(t: Transaction) -> str:
    if t.category in MATCHED:
        return "unmatched"
    if t.category in NEUTRAL:
        return "ok"
    if t.category in REVIEW and t.category_source != "user":
        return "needs_review"
    return "ok"


def reconcile(db: Session, workspace_id: int) -> dict:
    txns = db.query(Transaction).join(FinancialAccount).filter(FinancialAccount.workspace_id == workspace_id).all()
    for t in txns:
        t.match_group = None
        t.status = base_status(t)
    linked = ambiguous = 0
    for category, (lo, hi) in WINDOWS.items():
        debits = [t for t in txns if t.category == category and t.debit > 0]
        # The receiving leg of a transfer often reads as a plain NEFT/UPI credit, so accept those too.
        accepted = {category} | ({"bank_transfer", "upi_transfer", "uncategorized"} if category == "own_transfer" else set())
        credits = [t for t in txns if t.credit > 0 and t.category in accepted]

        def fits(d, c):
            return c.account_id != d.account_id and c.credit == d.debit and lo <= (c.txn_date - d.txn_date).days <= hi

        options = {d.id: [c for c in credits if fits(d, c)] for d in debits}
        reverse: dict[int, int] = {}
        for opts in options.values():
            for c in opts:
                reverse[c.id] = reverse.get(c.id, 0) + 1
        for d in debits:
            opts = [c for c in options[d.id] if c.match_group is None]
            if len(opts) == 1 and reverse[opts[0].id] == 1:
                c = opts[0]
                gid = str(uuid4())
                d.match_group = c.match_group = gid
                d.status = c.status = "confirmed_settlement" if category == "card_settlement" else "confirmed_transfer"
                if c.category != category and c.category_source != "user":
                    c.category = category
                linked += 1
            elif len(opts) > 1 or (len(opts) == 1 and reverse[opts[0].id] > 1):
                d.status = "ambiguous"
                ambiguous += 1
    unmatched = sum(t.status == "unmatched" for t in txns)
    apply_purposes(db, workspace_id)
    db.add(AuditEvent(workspace_id=workspace_id, action="reconciled", detail=f"confirmed={linked}; ambiguous={ambiguous}; unmatched={unmatched}"))
    db.commit()
    return {"confirmed": linked, "ambiguous": ambiguous, "unmatched": unmatched}
