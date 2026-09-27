"""Links the two legs of card bill payments and own-account transfers.

Runs over the whole workspace and is idempotent: every run recomputes links and
statuses from scratch. A link is made only when the pairing is unique in both
directions; ties are marked `ambiguous` and never guessed.

When a link needs one leg re-labelled (a plain UPI credit that is really the other
side of a self-transfer, a BBPS debit that is really a card bill), the row gets
category_source="link". Those rows go back to their rule category at the start of
every run, so a link that no longer holds (a statement deleted) leaves nothing behind.

Statuses: ok | needs_review | unmatched | ambiguous | confirmed_settlement | confirmed_transfer
"""
from uuid import uuid4
from sqlalchemy.orm import Session
from ..models import Transaction, FinancialAccount, AuditEvent, UserRule
from .rules import MATCHED, NEUTRAL, REVIEW, classify
from .purpose import apply_purposes

WINDOWS = {"card_settlement": (-2, 7), "own_transfer": (-1, 3)}
# Generic labels a leg may carry when its narration didn't say what it was.
GENERIC = {"bank_transfer", "upi_transfer", "uncategorized"}
# A card bill paid from the bank often reads as a BBPS / auto-debit / debit-card (CRED via POS) payment.
CARD_BILL_DEBITS = GENERIC | {"bill_payment", "auto_debit", "card_purchase"}


def base_status(t: Transaction) -> str:
    if t.category in MATCHED:
        return "unmatched"
    if t.category in NEUTRAL:
        return "ok"
    if t.category in REVIEW and t.category_source != "user":
        return "needs_review"
    return "ok"


def _pair(debits: list, credits: list, lo: int, hi: int):
    """Unique debit↔credit pairs (same amount, other account, credit lo..hi days after the debit), and the debits
    that have several candidates or share their only candidate with another debit."""
    def fits(d, c):
        return c.account_id != d.account_id and c.credit == d.debit and lo <= (c.txn_date - d.txn_date).days <= hi

    options = {d.id: [c for c in credits if fits(d, c)] for d in debits}
    reverse: dict[int, int] = {}
    for opts in options.values():
        for c in opts:
            reverse[c.id] = reverse.get(c.id, 0) + 1
    pairs, ambiguous = [], []
    for d in debits:
        opts = options[d.id]
        if len(opts) == 1 and reverse[opts[0].id] == 1:
            pairs.append((d, opts[0]))
        elif opts:
            ambiguous.append(d)
    return pairs, ambiguous


def _relabel(t: Transaction, category: str) -> None:
    if t.category != category and t.category_source != "user":
        t.category, t.category_source = category, "link"


def reconcile(db: Session, workspace_id: int) -> dict:
    rows = db.query(Transaction, FinancialAccount).join(FinancialAccount).filter(FinancialAccount.workspace_id == workspace_id).all()
    kind = {t.id: a.kind for t, a in rows}
    txns = [t for t, _ in rows]
    learned = {r.key: r.category for r in db.query(UserRule).filter_by(workspace_id=workspace_id)}
    for t in txns:
        if t.category_source == "link":
            t.category, t.category_source = classify(t.narration, t.debit > 0, kind[t.id], learned), "rule"
    for t in txns:
        t.match_group = None
        t.status = base_status(t)
    linked = ambiguous = 0

    def link(d, c, status):
        nonlocal linked
        d.match_group = c.match_group = str(uuid4())
        d.status = c.status = status
        linked += 1

    # Card bills: a bank debit labelled as a card payment ↔ a payment credit on a card statement.
    lo, hi = WINDOWS["card_settlement"]
    card_credits = [t for t in txns if kind[t.id] == "card" and t.credit > 0 and t.category == "card_settlement"]
    bank_bills = [t for t in txns if kind[t.id] == "bank" and t.debit > 0 and t.category == "card_settlement"]
    pairs, amb = _pair(bank_bills, card_credits, lo, hi)
    for d, c in pairs:
        link(d, c, "confirmed_settlement")
    # Then payments still unmatched on a card ↔ bank debits whose narration didn't say "card" (BBPS, UPI to CRED, NEFT…).
    open_credits = [c for c in card_credits if c.match_group is None]
    generic = [t for t in txns if kind[t.id] == "bank" and t.debit > 0 and t.category in CARD_BILL_DEBITS and t.category_source != "user"]
    pairs2, _ = _pair(generic, open_credits, lo, hi)
    for d, c in pairs2:
        _relabel(d, "card_settlement")
        link(d, c, "confirmed_settlement")
    for d in amb:
        if d.match_group is None:
            d.status = "ambiguous"
            ambiguous += 1

    # Own transfers: the receiving leg often reads as a plain NEFT/UPI credit.
    lo, hi = WINDOWS["own_transfer"]
    out = [t for t in txns if t.category == "own_transfer" and t.debit > 0]
    ins = [t for t in txns if t.credit > 0 and t.match_group is None and (t.category == "own_transfer" or t.category in GENERIC and kind[t.id] == "bank")]
    pairs, amb = _pair(out, ins, lo, hi)
    for d, c in pairs:
        _relabel(c, "own_transfer")
        link(d, c, "confirmed_transfer")
    for d in amb:
        d.status = "ambiguous"
        ambiguous += 1

    unmatched = sum(t.status == "unmatched" for t in txns)
    apply_purposes(db, workspace_id)
    db.add(AuditEvent(workspace_id=workspace_id, action="reconciled", detail=f"confirmed={linked}; ambiguous={ambiguous}; unmatched={unmatched}"))
    db.commit()
    return {"confirmed": linked, "ambiguous": ambiguous, "unmatched": unmatched}
