"""Links the two legs of card bill payments and own-account transfers.

Runs over the whole workspace and is idempotent: every run recomputes links and
statuses from scratch. A link is made only when the pairing is unique in both
directions; ties are marked `ambiguous` and never guessed.

When a link needs one leg re-labelled (a plain UPI credit that is really the other
side of a self-transfer, a BBPS debit that is really a card bill), the row gets
category_source="link". Those rows go back to their rule category at the start of
every run, so a link that no longer holds (a statement deleted) leaves nothing behind.

A card bill payment with no credit on an uploaded card statement is still explained when it pays the total due
of an uploaded statement of that card: the purchases it paid are on that statement, and its credit is on the next
one, which may not be uploaded. Such a payment gets status statement_paid and match_group "doc:<document id>".

Statuses: ok | needs_review | unmatched | ambiguous | confirmed_settlement | confirmed_transfer | statement_paid
"""
from uuid import uuid4
from sqlalchemy.orm import Session
from datetime import timedelta
from decimal import Decimal
from ..models import Transaction, FinancialAccount, AuditEvent, UserRule, SourceDocument
from .rules import MATCHED, NEUTRAL, REVIEW, classify
from .purpose import apply_purposes

WINDOWS = {"card_settlement": (-2, 7), "own_transfer": (-1, 3)}
# Generic labels a leg may carry when its narration didn't say what it was.
GENERIC = {"bank_transfer", "upi_transfer", "uncategorized"}
# A card bill paid from the bank often reads as a BBPS / auto-debit / debit-card (CRED via POS) payment.
CARD_BILL_DEBITS = GENERIC | {"bill_payment", "auto_debit", "card_purchase"}
# CRED applies a few rupees of coins/cashback (or adds a fee), so the card can receive slightly more or less than
# the bank sent: up to 1% and ₹50 (at least ₹2).
STATEMENT_PAY_DAYS = 35  # a statement's bill is paid within this many days of its last transaction


def near(a: Decimal, b: Decimal) -> bool:
    return abs(a - b) <= max(Decimal("2"), min(Decimal("50"), a / 100))


def base_status(t: Transaction) -> str:
    if t.category in MATCHED:
        return "unmatched"
    if t.category in NEUTRAL:
        return "ok"
    if t.category in REVIEW and t.category_source != "user":
        return "needs_review"
    return "ok"


def _pair(debits: list, credits: list, lo: int, hi: int, same=lambda a, b: a == b):
    """Unique debit↔credit pairs (same amount, other account, credit lo..hi days after the debit), and the debits
    that have several candidates or share their only candidate with another debit."""
    def fits(d, c):
        return c.account_id != d.account_id and same(d.debit, c.credit) and lo <= (c.txn_date - d.txn_date).days <= hi

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
    # Still open on both sides: amounts a few rupees apart (CRED coins or fees).
    open_bills = [d for d in bank_bills if d.match_group is None]
    pairs3, _ = _pair(open_bills, [c for c in card_credits if c.match_group is None], -1, 3, near)
    for d, c in pairs3:
        link(d, c, "confirmed_settlement")
    # A card credit whose wording read as a refund, but which is exactly one bank card-bill payment's other leg
    # (same amount, −1..+3 days, unique both ways), is that bill payment arriving: not a refund.
    refund_like = [c for c in txns if kind[c.id] == "card" and c.credit > 0 and c.category == "refund_reversal"
                   and c.category_source != "user" and c.match_group is None]
    pairs4, _ = _pair([d for d in bank_bills if d.match_group is None], refund_like, -1, 3)
    for d, c in pairs4:
        _relabel(c, "card_settlement")
        link(d, c, "confirmed_settlement")
    # Then bank payments that pay the total due of an uploaded card statement (its credit is on the next statement).
    statement_paid = _pay_statements(db, workspace_id, [d for d in bank_bills if d.match_group is None], txns, kind)
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
    db.add(AuditEvent(workspace_id=workspace_id, action="reconciled",
                      detail=f"confirmed={linked}; statement_paid={statement_paid}; ambiguous={ambiguous}; unmatched={unmatched}"))
    db.commit()
    return {"confirmed": linked, "statement_paid": statement_paid, "ambiguous": ambiguous, "unmatched": unmatched}


def _pay_statements(db: Session, workspace_id: int, bills: list, txns: list, kind: dict) -> int:
    """Link open bank card-bill payments to the uploaded card statement whose total due they pay, when exactly one
    statement fits the payment and exactly one payment fits the statement."""
    ends: dict[int, object] = {}
    for t in txns:
        if kind[t.id] == "card":
            ends[t.document_id] = max(ends.get(t.document_id, t.txn_date), t.txn_date)
    docs = [d for d in db.query(SourceDocument).filter(SourceDocument.workspace_id == workspace_id, SourceDocument.total_due.isnot(None))
            if d.id in ends]

    def fits(b, doc):
        # CRED coins can take a few rupees off what the bank pays, never add to it.
        return (Decimal() <= doc.total_due - b.debit and near(doc.total_due, b.debit)
                and ends[doc.id] - timedelta(days=1) <= b.txn_date <= ends[doc.id] + timedelta(days=STATEMENT_PAY_DAYS))

    options = {b.id: [d for d in docs if fits(b, d)] for b in bills}
    takers: dict[int, int] = {}
    for opts in options.values():
        for d in opts:
            takers[d.id] = takers.get(d.id, 0) + 1
    n = 0
    for b in bills:
        opts = options[b.id]
        if len(opts) == 1 and takers[opts[0].id] == 1:
            b.match_group, b.status = f"doc:{opts[0].id}", "statement_paid"
            n += 1
    return n
