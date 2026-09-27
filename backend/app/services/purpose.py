"""Business vs personal purpose for each transaction.

Priority: the user's own choice > a payee rule the user taught > the account's
use (business / personal / mixed) combined with the category > narration hints.
Anything genuinely ambiguous stays "unknown" rather than being guessed.
"""
import re
from .rules import NEUTRAL, merchant_key

BUSINESS_CATEGORIES = {"business_receipt", "software", "advertising", "professional_services", "office", "courier", "gst_payment"}
PERSONAL_CATEGORIES = {"salary", "dividend", "interest_income", "investment", "investment_redemption", "insurance", "loan_emi",
                       "education", "donation", "medical", "groceries", "entertainment", "tax_payment", "tax_refund",
                       "rental_income", "rent", "dining", "shopping"}
# Personal even on an account used for business.
ALWAYS_PERSONAL = {"salary", "dividend", "investment", "investment_redemption", "tax_refund", "education", "donation"}
BUSINESS_HINTS = re.compile(r"\bgstin?\b|invoice|\binv\b|vendor|\bb2b\b|client|purchase order|\bpo no\b", re.I)


def suggest(category: str, narration: str, account_purpose: str = "mixed", learned: dict[str, str] | None = None) -> str:
    if category in NEUTRAL:
        return "neutral"
    if learned:
        taught = learned.get(merchant_key(narration))
        if taught:
            return taught
    if account_purpose == "business":
        return "personal" if category in ALWAYS_PERSONAL else "business"
    if category in BUSINESS_CATEGORIES:
        return "business"  # e.g. an AWS bill on a personal card
    if account_purpose == "personal":
        return "personal"
    if category in PERSONAL_CATEGORIES:
        return "personal"
    if BUSINESS_HINTS.search(narration):
        return "business"
    return "unknown"


def apply_purposes(db, workspace_id: int) -> None:
    """Recompute rule-based purposes for a workspace; user choices are left alone. Caller commits."""
    from ..models import Transaction, FinancialAccount, PurposeRule
    accounts = {a.id: a.purpose or "mixed" for a in db.query(FinancialAccount).filter_by(workspace_id=workspace_id)}
    learned = {r.key: r.purpose for r in db.query(PurposeRule).filter_by(workspace_id=workspace_id)}
    rows = db.query(Transaction).filter(Transaction.account_id.in_(list(accounts) or [0])).all()
    for t in rows:
        if t.category in NEUTRAL:
            t.purpose = "neutral"
        elif t.purpose_source != "user":
            t.purpose = suggest(t.category, t.narration, accounts.get(t.account_id, "mixed"), learned)
