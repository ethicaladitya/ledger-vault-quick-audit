"""FY working-paper summary, audit flags and XLSX export."""
import io
from collections import defaultdict
from datetime import date
from decimal import Decimal
from sqlalchemy.orm import Session
from ..models import Transaction, FinancialAccount, SourceDocument
from .rules import CATEGORIES, NEUTRAL, REVIEW

LAKH = Decimal("100000")
MONTHS = ["Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec", "Jan", "Feb", "Mar"]


def inr(v: Decimal) -> str:
    """Indian digit grouping: 12,34,567."""
    v = Decimal(v).quantize(Decimal("1"))
    s = str(abs(v))
    head, tail = s[:-3], s[-3:]
    groups = []
    while len(head) > 2:
        groups.insert(0, head[-2:])
        head = head[:-2]
    if head:
        groups.insert(0, head)
    return ("-" if v < 0 else "") + "₹" + ",".join(groups + [tail]) if groups else ("-" if v < 0 else "") + "₹" + tail


def fy_transactions(db: Session, workspace_id: int, fy: str | None):
    q = db.query(Transaction, FinancialAccount).join(FinancialAccount, Transaction.account_id == FinancialAccount.id).filter(FinancialAccount.workspace_id == workspace_id)
    if fy:
        q = q.filter(Transaction.financial_year == fy)
    return q.order_by(Transaction.txn_date, Transaction.id).all()


def totals(rows) -> dict:
    inflow = outflow = refunds = neutral = Decimal()
    for t, _ in rows:
        if t.category in NEUTRAL:
            neutral += t.debit
        elif t.category == "refund_reversal":
            refunds += t.credit
            outflow += t.debit
        else:
            inflow += t.credit
            outflow += t.debit
    return {"inflow": inflow, "outflow": outflow - refunds, "refunds": refunds, "neutral": neutral}


def category_summary(rows) -> list[dict]:
    agg = defaultdict(lambda: {"count": 0, "debit": Decimal(), "credit": Decimal()})
    for t, _ in rows:
        a = agg[t.category]
        a["count"] += 1
        a["debit"] += t.debit
        a["credit"] += t.credit
    out = []
    for key, a in agg.items():
        label, group, hint = CATEGORIES.get(key, (key, "review", ""))
        out.append({"category": key, "label": label, "group": group, "itr_hint": hint, "count": a["count"], "debit": str(a["debit"]), "credit": str(a["credit"])})
    order = ["income", "tax", "deduction_hint", "investment", "review", "expense", "adjustment", "neutral"]
    return sorted(out, key=lambda r: (order.index(r["group"]) if r["group"] in order else 99, -Decimal(r["debit"]) - Decimal(r["credit"])))


def flags(rows, fy: str | None) -> list[dict]:
    out = []

    def add(level, title, detail):
        out.append({"level": level, "title": title, "detail": detail})

    by_status = defaultdict(list)
    for t, a in rows:
        by_status[(t.category, t.status, a.kind, t.debit > 0)].append(t)
    bank_card_payments = [t for (c, s, k, d), ts in by_status.items() if c == "card_settlement" and s == "unmatched" and d for t in ts]
    card_payments_in = [t for (c, s, k, d), ts in by_status.items() if c == "card_settlement" and s == "unmatched" and not d for t in ts]
    transfers = [t for (c, s, k, d), ts in by_status.items() if c == "own_transfer" and s == "unmatched" for t in ts]
    ambiguous = [t for t, _ in rows if t.status == "ambiguous"]
    review = [t for t, _ in rows if t.status == "needs_review"]

    if bank_card_payments:
        add("warning", f"{len(bank_card_payments)} credit card bill payment(s) without a card statement",
            f"{inr(sum(t.debit for t in bank_card_payments))} was paid to credit cards but no matching payment was found on an uploaded card statement. "
            "Upload those card statements so the actual purchases are counted (the bill payment itself is not an expense).")
    if card_payments_in:
        add("info", f"{len(card_payments_in)} card payment(s) received with no paying bank statement",
            f"{inr(sum(t.credit for t in card_payments_in))} of card bills were paid from an account that isn't uploaded. Upload that bank statement if it is yours.")
    if transfers:
        add("info", f"{len(transfers)} self-transfer(s) without the other side",
            "These look like transfers between your own accounts but the other account's statement isn't uploaded. Upload it, or re-categorise if the money went to someone else.")
    if ambiguous:
        add("warning", f"{len(ambiguous)} payment(s) could match more than one counterpart",
            "Several same-amount payments fall on nearby dates. Check these in Reconciliation; nothing was auto-linked.")
    if review:
        add("warning", f"{len(review)} transaction(s) need a category",
            f"{inr(sum(t.debit + t.credit for t in review))} of UPI/NEFT/unrecognised entries. Open Transactions → 'Needs review' and assign categories.")

    big = [t for t, _ in rows if t.credit >= 2 * LAKH and (t.category in REVIEW or t.category in {"business_receipt"})]
    if big:
        add("warning", f"{len(big)} large credit(s) of ₹2 lakh or more with no clear source",
            "The tax department can ask you to explain large credits (sec. 68/69). Note the source of each — e.g. loan, gift from relative, sale of asset. "
            + "; ".join(f"{t.txn_date.isoformat()} {inr(t.credit)}" for t in big[:5]) + ("…" if len(big) > 5 else ""))

    cash_dep = sum((t.credit for t, a in rows if t.category == "cash_deposit"), Decimal())
    if cash_dep >= 10 * LAKH:
        add("warning", f"Cash deposits of {inr(cash_dep)} this year",
            "Cash deposits of ₹10 lakh or more in a year are reported by banks to the IT dept (SFT) and appear in your AIS. Keep evidence of the source.")
    elif cash_dep > 0:
        add("info", f"Cash deposits of {inr(cash_dep)}", "Below the ₹10 lakh SFT reporting threshold, but keep a note of the source.")

    card_paid = sum((t.debit for t, a in rows if t.category == "card_settlement" and a.kind == "bank"), Decimal())
    if card_paid >= 10 * LAKH:
        add("info", f"Credit card bills paid: {inr(card_paid)}", "Card bill payments of ₹10 lakh or more in a year are reported in AIS (SFT). Make sure your declared income supports this spend.")

    interest = sum((t.credit for t, _ in rows if t.category == "interest_income"), Decimal())
    if interest > 0:
        add("info", f"Interest received: {inr(interest)}", "Declare under 'Income from other sources' and compare with AIS/26AS — FD interest is often missed.")
    dividend = sum((t.credit for t, _ in rows if t.category == "dividend"), Decimal())
    if dividend > 0:
        add("info", f"Dividends received: {inr(dividend)}", "Dividends are taxable at slab rates. Match with AIS and claim any TDS deducted.")
    salary = sum((t.credit for t, _ in rows if t.category == "salary"), Decimal())
    if salary > 0:
        add("info", f"Salary credits: {inr(salary)} (net of deductions)", "Bank credits are take-home pay. Use gross salary and TDS from Form 16 for the return.")

    if fy:
        start = int(fy[:4])
        months_in_fy = [(start if m >= 4 else start + 1, m) for m in [4, 5, 6, 7, 8, 9, 10, 11, 12, 1, 2, 3]]
        today = date.today()
        by_account = defaultdict(set)
        names = {}
        for t, a in rows:
            by_account[a.id].add((t.txn_date.year, t.txn_date.month))
            names[a.id] = a.name
        for acc_id, seen in by_account.items():
            missing = [MONTHS[i] for i, ym in enumerate(months_in_fy) if ym not in seen and date(ym[0], ym[1], 1) <= today]
            if missing and len(missing) < 12:
                add("info", f"{names[acc_id]}: no transactions in {', '.join(missing)}",
                    "This may be a missing statement period. Upload it if the account was active.")
    if not rows:
        add("info", "No statements uploaded for this year", "Upload bank and credit card statements to begin.")
    return out


def export_xlsx(db: Session, workspace_id: int, fy: str | None) -> bytes:
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill
    rows = fy_transactions(db, workspace_id, fy)
    docs = {d.id: d.filename for d in db.query(SourceDocument).filter_by(workspace_id=workspace_id)}
    wb = Workbook()
    bold = Font(bold=True)
    head_fill = PatternFill("solid", fgColor="D9EEE4")

    ws = wb.active
    ws.title = "Summary"
    tot = totals(rows)
    ws.append([f"LedgerVault working paper — FY {fy or 'all years'}"])
    ws["A1"].font = Font(bold=True, size=14)
    ws.append(["Provisional. Prepared from bank/card statements for review by a Chartered Accountant; not a tax computation."])
    ws.append([])
    for label, key in [("Money in (excl. transfers & refunds)", "inflow"), ("Money out (net of refunds, excl. card bill payments & transfers)", "outflow"), ("Refunds / reversals", "refunds"), ("Neutral: card bill payments & self transfers", "neutral")]:
        ws.append([label, float(tot[key])])
    ws.append([])
    ws.append(["Category", "Group", "Count", "Debit (₹)", "Credit (₹)", "ITR note"])
    for c in ws[ws.max_row]:
        c.font, c.fill = bold, head_fill
    for r in category_summary(rows):
        ws.append([r["label"], r["group"].replace("_", " "), r["count"], float(r["debit"]), float(r["credit"]), r["itr_hint"]])
    for col, width in zip("ABCDEF", [48, 16, 8, 16, 16, 80]):
        ws.column_dimensions[col].width = width

    fl = wb.create_sheet("Flags")
    fl.append(["Level", "Flag", "Detail"])
    for c in fl[1]:
        c.font, c.fill = bold, head_fill
    for f in flags(rows, fy):
        fl.append([f["level"], f["title"], f["detail"]])
    for col, width in zip("ABC", [10, 60, 120]):
        fl.column_dimensions[col].width = width

    tx = wb.create_sheet("Transactions")
    tx.append(["FY", "Date", "Account", "Type", "Narration", "Debit (₹)", "Credit (₹)", "Balance (₹)", "Category", "Group", "Status", "Note", "Source file", "Source row"])
    for c in tx[1]:
        c.font, c.fill = bold, head_fill
    for t, a in rows:
        label, group, _ = CATEGORIES.get(t.category, (t.category, "review", ""))
        tx.append([t.financial_year, t.txn_date, a.name, a.kind, t.narration, float(t.debit), float(t.credit),
                   float(t.balance) if t.balance is not None else None, label, group.replace("_", " "), t.status.replace("_", " "), t.note or "", docs.get(t.document_id, ""), t.source_row])
    for col, width in zip("ABCDEFGHIJKLMN", [9, 12, 22, 7, 60, 13, 13, 13, 30, 14, 20, 30, 30, 9]):
        tx.column_dimensions[col].width = width
    tx.freeze_panes = "A2"
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
