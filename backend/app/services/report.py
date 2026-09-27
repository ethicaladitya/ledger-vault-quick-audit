"""FY working-paper summary, audit flags and XLSX export."""
import io, re
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


def fy_transactions(db: Session, workspace_id: int, fy: str | None, account_id: int | None = None, purpose: str | None = None):
    q = db.query(Transaction, FinancialAccount).join(FinancialAccount, Transaction.account_id == FinancialAccount.id).filter(FinancialAccount.workspace_id == workspace_id)
    if fy:
        q = q.filter(Transaction.financial_year == fy)
    if account_id:
        q = q.filter(Transaction.account_id == account_id)
    if purpose:
        q = q.filter(Transaction.purpose == purpose)
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
    card = sum((t.debit for t, _ in rows if t.category == "card_settlement"), Decimal())
    return {"inflow": inflow, "outflow": outflow - refunds, "refunds": refunds, "neutral": neutral,
            "card_payments": card, "self_transfers": sum((t.debit for t, _ in rows if t.category == "own_transfer"), Decimal()),
            "card_emi": sum((t.debit for t, _ in rows if t.category == "card_emi"), Decimal())}


CASH = re.compile(r"\bcash\b", re.I)
# Card issuers as they appear in bank narrations for card bill payments.
ISSUERS = [(r"\bsbi ?card|sbicard", "SBI Card"), (r"amex|american express", "American Express"), (r"\bhdfc", "HDFC Bank"),
           (r"\bicici", "ICICI Bank"), (r"\baxis", "Axis Bank"), (r"kotak", "Kotak"), (r"idfc", "IDFC FIRST"), (r"\byes ?bank", "Yes Bank"),
           (r"indusind", "IndusInd"), (r"\brbl\b", "RBL"), (r"\bau\b.*(bank|card)", "AU Bank"), (r"standard chartered|\bscb\b", "Standard Chartered"),
           (r"\bhsbc\b", "HSBC"), (r"citi", "Citi"), (r"onecard|one card", "OneCard"), (r"federal", "Federal Bank"), (r"\bbob\b|baroda", "Bank of Baroda"),
           (r"\bsbi\b", "SBI Card")]
VIA = [(r"dreamplug|\bcred\b", "CRED"), (r"bbps|billdesk|bill ?pay", "BBPS"), (r"autopay|si-tad|si-mad|\bsi\b", "auto-debit")]
MONTH_NAMES = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def card_hint(narration: str) -> dict:
    """Which card a bank-side bill payment went to, as far as the narration says: issuer and last 4 digits."""
    low = narration.lower()
    via = next((name for pattern, name in VIA if re.search(pattern, low)), None)
    # Bank names inside UPI handles say whose rails carried the payment, not which card was paid:
    # CRED collects every card bill through cred.club@axisb, so "axis" there means nothing.
    low = re.sub(r"[\w.\-]+@[\w.\-]+", " ", low)
    # "POS 416021XXXXXX9685 ..." is the debit card that paid (e.g. through CRED), not the credit card being paid.
    paid_by_debit_card = re.match(r"\s*(pos\b|pos-|vps/|ips/)", low) is not None
    m = None if paid_by_debit_card else (re.search(r"(?:x{2,}|\*{2,}|\d{4}[x*]{2,})[x*\d]*?(\d{4})\b", low)
                                         or re.search(r"(?:credit ?card|\bcc\b|\bcard\b)\D{0,25}?(\d{4})\b", low))
    issuer = next((name for pattern, name in ISSUERS if re.search(pattern, low)), None)
    return {"issuer": issuer, "last4": m.group(1) if m else None, "via": via}


def _label(hint: dict) -> str:
    if hint["issuer"] or hint["last4"]:
        name = hint["issuer"] or "Credit"
        name = name if name.lower().endswith(("card", "express")) else f"{name} card"
        return name + (f" ••{hint['last4']}" if hint["last4"] else "")
    return f"Card not identified (paid via {hint['via']})" if hint["via"] else "Card not identified"


def _month(d) -> str:
    return f"{MONTH_NAMES[d.month - 1]} {d.year}"


def missing_card_statements(rows) -> list[dict]:
    """Bank-side card bill payments with no matching credit on an uploaded card statement, grouped by card, saying
    whether the card was never uploaded, a month is missing, or the statement is there but the payment isn't."""
    card_accounts = {a.id: a for _, a in rows if a.kind == "card"}
    coverage: dict[int, list[tuple]] = {}
    spans: dict[tuple, list] = {}
    for t, a in rows:
        if a.kind == "card":
            spans.setdefault((a.id, t.document_id), []).append(t.txn_date)
    for (acc_id, _), dates in spans.items():
        coverage.setdefault(acc_id, []).append((min(dates), max(dates)))
    for acc_id in coverage:
        coverage[acc_id].sort()
    from datetime import timedelta

    def find_account(h):
        cands = list(card_accounts.values())
        if h["last4"]:
            by_digits = [a for a in cands if h["last4"] in a.name]
            if by_digits:
                return by_digits[0]
            return None  # digits known but no uploaded card has them: a different card
        if h["issuer"]:
            by_issuer = [a for a in cands if h["issuer"].split()[0].lower() in a.name.lower()]
            return by_issuer[0] if len(by_issuer) == 1 else None
        return None

    groups: dict[tuple, dict] = {}
    for t, a in rows:
        if not (t.category == "card_settlement" and t.debit > 0 and a.kind == "bank" and not t.match_group):
            continue
        h = card_hint(t.narration)
        acc = find_account(h)
        if acc is None:
            status, key = "not_uploaded", ("n", h["issuer"], h["last4"], None if (h["issuer"] or h["last4"]) else h["via"])
        else:
            covered = any(lo - timedelta(days=3) <= t.txn_date <= hi + timedelta(days=7) for lo, hi in coverage.get(acc.id, []))
            status, key = ("not_matched" if covered else "period_missing"), ("a", acc.id, "covered" if covered else "gap")
        covered = [f"{lo.strftime('%d %b %Y')} to {hi.strftime('%d %b %Y')}" for lo, hi in coverage.get(acc.id, [])] if acc else []
        g = groups.setdefault(key, {"card": acc.name if acc else _label(h), "account_id": acc.id if acc else None, "status": status,
                                    "count": 0, "amount": Decimal(), "months": [], "payments": [], "covered": covered})
        g["count"] += 1
        g["amount"] += t.debit
        if _month(t.txn_date) not in g["months"]:
            g["months"].append(_month(t.txn_date))
        g["payments"].append({"id": t.id, "date": t.txn_date.isoformat(), "bank": a.name, "narration": t.narration, "amount": str(t.debit)})
    order = {"not_uploaded": 0, "period_missing": 1, "not_matched": 2}
    out = sorted(groups.values(), key=lambda g: (order[g["status"]], -g["amount"]))
    for g in out:
        g["amount"] = str(g["amount"])
        g["message"] = {
            "not_uploaded": f"No statement uploaded for this card. Upload its statements for {', '.join(g['months'])} so its purchases are counted.",
            "period_missing": (f"This card is uploaded, but not the statement(s) covering {', '.join(g['months'])}. "
                               + (f"Statements uploaded for it cover: {'; '.join(g['covered'])}. " if g["covered"] else "None of its uploaded statements fall in this financial year. ")
                               + "Upload the missing ones so those purchases are counted."),
            "not_matched": "The statement for this period is uploaded, but no matching payment was found on it. Check the amount, or whether this payment went to a different card.",
        }[g["status"]]
    return out


def card_reconciliation(rows) -> dict:
    """Per credit card: purchases (already counted as expenses), refunds and bill payments, with how many
    payments were matched to a bank debit. Card bill payments are reported to the IT dept (AIS), so the
    total paid is shown for the CA to compare. Each payment is counted once even when both legs exist."""
    cards: dict[int, dict] = {}
    for t, a in rows:
        if a.kind != "card":
            continue
        c = cards.setdefault(a.id, {"account_id": a.id, "account": a.name, "purchases": Decimal(), "purchase_count": 0, "refunds": Decimal(),
                                    "payments": Decimal(), "payment_count": 0, "matched": Decimal(), "matched_count": 0,
                                    "unmatched": Decimal(), "unmatched_count": 0, "cash_payments": Decimal()})
        if t.category == "card_settlement" and t.credit > 0:
            c["payments"] += t.credit
            c["payment_count"] += 1
            if t.match_group:
                c["matched"] += t.credit
                c["matched_count"] += 1
            else:
                c["unmatched"] += t.credit
                c["unmatched_count"] += 1
            if CASH.search(t.narration):
                c["cash_payments"] += t.credit
        elif t.category == "refund_reversal" and t.credit > 0:
            c["refunds"] += t.credit
        elif t.debit > 0 and t.category not in NEUTRAL:
            c["purchases"] += t.debit
            c["purchase_count"] += 1
    # Bill payments made from an uploaded bank account to a card whose statement isn't uploaded.
    orphan = [(t, a) for t, a in rows if t.category == "card_settlement" and t.debit > 0 and a.kind == "bank" and not t.match_group]
    orphan_total = sum((t.debit for t, _ in orphan), Decimal())
    card_list = sorted(cards.values(), key=lambda c: c["account"].lower())
    total_paid = sum((c["payments"] for c in card_list), Decimal()) + orphan_total
    cash_total = sum((c["cash_payments"] for c in card_list), Decimal())
    as_str = lambda d: {k: (str(v) if isinstance(v, Decimal) else v) for k, v in d.items()}
    return {
        "cards": [as_str(c) for c in card_list],
        "missing_statements": missing_card_statements(rows),
        "unmatched_bank_payments": [{"id": t.id, "date": t.txn_date.isoformat(), "account": a.name, "narration": t.narration, "amount": str(t.debit)} for t, a in orphan],
        "unmatched_bank_total": str(orphan_total),
        "total_paid": str(total_paid),
        "total_purchases": str(sum((c["purchases"] for c in card_list), Decimal())),
        "cash_paid": str(cash_total),
        "sft_reportable": total_paid >= 10 * LAKH or cash_total >= LAKH,
    }


def purpose_split(rows) -> dict:
    """Money in/out and counts by business / personal / unknown (neutral flows excluded)."""
    out = {}
    for p in ("business", "personal", "unknown"):
        sel = [(t, a) for t, a in rows if t.purpose == p]
        tot = totals(sel)
        out[p] = {"count": len(sel), "inflow": str(tot["inflow"]), "outflow": str(tot["outflow"])}
    return out


def purpose_flags(rows, purpose: str | None) -> list[dict]:
    """In a business/personal report, say what was left out so nothing silently disappears."""
    if not purpose:
        return []
    unknown = [t for t, _ in rows if t.purpose == "unknown"]
    other = "personal" if purpose == "business" else "business"
    excluded = [t for t, _ in rows if t.purpose == other]
    out = []
    if unknown:
        out.append({"level": "warning", "title": f"{len(unknown)} transaction(s) have no business/personal purpose yet",
                    "detail": f"{inr(sum(t.debit + t.credit for t in unknown))} is left out of this {purpose} report until you choose. "
                              "Open Transactions → Purpose: Unknown, or set what each account is used for in Settings."})
    if excluded:
        out.append({"level": "info", "title": f"{len(excluded)} {other} transaction(s) excluded",
                    "detail": f"{inr(sum(t.debit for t in excluded))} out and {inr(sum(t.credit for t in excluded))} in are marked {other} and not part of this report."})
    return out


def account_summary(rows) -> list[dict]:
    """One line per account: the same totals as the overall report, split by account."""
    by_account: dict[int, list] = defaultdict(list)
    for t, a in rows:
        by_account[a.id].append((t, a))
    out = []
    for acc_rows in by_account.values():
        a = acc_rows[0][1]
        tot = totals(acc_rows)
        dates = [t.txn_date for t, _ in acc_rows]
        out.append({"account_id": a.id, "account": a.name, "kind": a.kind, "count": len(acc_rows),
                    "inflow": str(tot["inflow"]), "outflow": str(tot["outflow"]), "refunds": str(tot["refunds"]), "neutral": str(tot["neutral"]),
                    "exceptions": sum(t.status in {"needs_review", "unmatched", "ambiguous"} for t, _ in acc_rows),
                    "from": min(dates).isoformat(), "to": max(dates).isoformat()})
    return sorted(out, key=lambda r: (r["kind"] != "bank", r["account"].lower()))


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

    for g in missing_card_statements(rows):
        title = {"not_uploaded": f"{g['card']}: statement not uploaded",
                 "period_missing": f"{g['card']}: statement missing for {', '.join(g['months'])}",
                 "not_matched": f"{g['card']}: payment not found on the uploaded statement"}[g["status"]]
        add("warning", title, f"{g['count']} bill payment(s) of {inr(Decimal(g['amount']))} from your bank ({', '.join(g['months'])}). {g['message']}")
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

    card_paid = Decimal(card_reconciliation(rows)["total_paid"])
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


def export_xlsx(db: Session, workspace_id: int, fy: str | None, account_id: int | None = None, purpose: str | None = None,
                business_mode: bool = False) -> bytes:
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill
    all_rows = fy_transactions(db, workspace_id, fy, account_id)
    rows = [(t, a) for t, a in all_rows if t.purpose == purpose] if purpose else all_rows
    docs = {d.id: d.filename for d in db.query(SourceDocument).filter_by(workspace_id=workspace_id)}
    wb = Workbook()
    bold = Font(bold=True)
    head_fill = PatternFill("solid", fgColor="D9EEE4")

    ws = wb.active
    ws.title = "Summary"
    tot = totals(rows)
    scope = f" — {all_rows[0][1].name}" if account_id and all_rows else ""
    kind = f"{purpose.capitalize()} working paper" if purpose else "working paper"
    ws.append([f"LedgerVault {kind} — FY {fy or 'all years'}{scope}"])
    ws["A1"].font = Font(bold=True, size=14)
    ws.append(["Provisional. Prepared from bank/card statements for review by a Chartered Accountant; not a tax computation."])
    if purpose:
        split = purpose_split(all_rows)
        ws.append([f"Only transactions marked {purpose}. Excluded: {split['personal' if purpose == 'business' else 'business']['count']} "
                   f"{'personal' if purpose == 'business' else 'business'} and {split['unknown']['count']} with no purpose yet."])
    ws.append([])
    for label, key in [("Money in (excl. transfers & refunds)", "inflow"), ("Money out (net of refunds, excl. card bill payments & transfers)", "outflow"),
                       ("Refunds / reversals", "refunds"), ("Credit card bill payments (not an expense — see 'Credit cards' sheet)", "card_payments"),
                       ("Transfers between own accounts (not income or expense)", "self_transfers")]:
        ws.append([label, float(tot[key])])
    ws.append([])
    ws.append(["Category", "Group", "Count", "Debit (₹)", "Credit (₹)", "ITR note"])
    for c in ws[ws.max_row]:
        c.font, c.fill = bold, head_fill
    for r in category_summary(rows):
        if r["group"] == "neutral":
            continue  # card bill payments and self-transfers are listed above and reconciled on their own sheet
        ws.append([r["label"], r["group"].replace("_", " "), r["count"], float(r["debit"]), float(r["credit"]), r["itr_hint"]])
    ws.append(["Credit card bill payments and transfers between own accounts are not income or expenses; see the lines above and the 'Credit cards' sheet."])
    for col, width in zip("ABCDEF", [48, 16, 8, 16, 16, 80]):
        ws.column_dimensions[col].width = width

    if not account_id:
        ba = wb.create_sheet("By account")
        ba.append(["Account", "Type", "Period", "Transactions", "Money in (₹)", "Money out, net (₹)", "Refunds (₹)", "Neutral (₹)", "Needs attention"])
        for c in ba[1]:
            c.font, c.fill = bold, head_fill
        for r in account_summary(rows):
            ba.append([r["account"], "Credit card" if r["kind"] == "card" else "Bank", f"{r['from']} to {r['to']}", r["count"],
                       float(r["inflow"]), float(r["outflow"]), float(r["refunds"]), float(r["neutral"]), r["exceptions"]])
        # Category × account matrix, so the CA can see where each category came from.
        accounts = [(r["account_id"], r["account"]) for r in account_summary(rows)]
        ba.append([])
        ba.append(["Category (net: in − out)"] + [name for _, name in accounts] + ["Total"])
        for c in ba[ba.max_row]:
            c.font, c.fill = bold, head_fill
        matrix: dict[str, dict[int, Decimal]] = defaultdict(lambda: defaultdict(Decimal))
        for t, a in rows:
            matrix[t.category][a.id] += t.credit - t.debit
        for cat in sorted(matrix, key=lambda k: CATEGORIES.get(k, (k,))[0]):
            vals = [matrix[cat].get(acc_id, Decimal()) for acc_id, _ in accounts]
            ba.append([CATEGORIES.get(cat, (cat,))[0]] + [float(v) if v else None for v in vals] + [float(sum(vals))])
        ba.column_dimensions["A"].width = 44
        for i in range(2, len(accounts) + 3):
            ba.column_dimensions[ba.cell(row=1, column=i).column_letter].width = 20

    cr = card_reconciliation(rows)
    if cr["cards"] or cr["unmatched_bank_payments"]:
        cc = wb.create_sheet("Credit cards")
        cc.append(["Credit card reconciliation"])
        cc["A1"].font = Font(bold=True, size=13)
        cc.append(["Card purchases are already counted as expenses under their categories. Bill payments to the card only settle those purchases, "
                   "so they are shown here for reconciliation and never counted as expenses."])
        cc.append([])
        cc.append(["Card", "Purchases (₹)", "No. of purchases", "Refunds (₹)", "Bill payments received (₹)", "Matched to a bank debit (₹)",
                   "Matched (no.)", "Not matched (₹)", "Not matched (no.)", "Paid in cash (₹)"])
        for c in cc[cc.max_row]:
            c.font, c.fill = bold, head_fill
        for c in cr["cards"]:
            cc.append([c["account"], float(c["purchases"]), c["purchase_count"], float(c["refunds"]), float(c["payments"]), float(c["matched"]),
                       c["matched_count"], float(c["unmatched"]), c["unmatched_count"], float(c["cash_payments"])])
        cc.append([])
        cc.append(["Total card bill payments this year (₹)", float(cr["total_paid"])])
        cc[cc.max_row][0].font = bold
        cc.append(["Compare with AIS → SFT 'Payment of credit card bills'. Issuers report payments of ₹10 lakh or more a year (₹1 lakh or more in cash)."])
        if cr["missing_statements"]:
            cc.append([])
            cc.append(["Missing card statements: bill payments seen in the bank with no matching card statement"])
            cc[cc.max_row][0].font = bold
            cc.append(["Card", "Issue", "Months", "Payments", "Amount (₹)", "What to do"])
            for c in cc[cc.max_row]:
                c.font, c.fill = bold, head_fill
            for g in cr["missing_statements"]:
                issue = {"not_uploaded": "Statement not uploaded", "period_missing": "Month(s) missing", "not_matched": "Payment not found on statement"}[g["status"]]
                cc.append([g["card"], issue, ", ".join(g["months"]), g["count"], float(g["amount"]), g["message"]])
            cc.append([])
            cc.append(["Date", "Bank account", "Narration", "Amount (₹)", "Card"])
            for c in cc[cc.max_row]:
                c.font, c.fill = bold, head_fill
            for g in cr["missing_statements"]:
                for u in g["payments"]:
                    cc.append([u["date"], u["bank"], u["narration"], float(u["amount"]), g["card"]])
        for col, width in zip("ABCDEFGHIJ", [38, 16, 12, 14, 18, 18, 12, 16, 12, 14]):
            cc.column_dimensions[col].width = width

    fl = wb.create_sheet("Flags")
    fl.append(["Level", "Flag", "Detail"])
    for c in fl[1]:
        c.font, c.fill = bold, head_fill
    for f in purpose_flags(all_rows, purpose) + flags(rows, fy):
        fl.append([f["level"], f["title"], f["detail"]])
    for col, width in zip("ABC", [10, 60, 120]):
        fl.column_dimensions[col].width = width

    tx = wb.create_sheet("Transactions")
    show_purpose = business_mode or bool(purpose)
    tx.append(["FY", "Date", "Account", "Type", "Narration", "Debit (₹)", "Credit (₹)", "Balance (₹)", "Category", "Group", "Status", "Note", "Source file", "Source row"]
              + (["Purpose"] if show_purpose else []))
    for c in tx[1]:
        c.font, c.fill = bold, head_fill
    for t, a in rows:
        label, group, _ = CATEGORIES.get(t.category, (t.category, "review", ""))
        tx.append([t.financial_year, t.txn_date, a.name, a.kind, t.narration, float(t.debit), float(t.credit),
                   float(t.balance) if t.balance is not None else None, label, group.replace("_", " "), t.status.replace("_", " "), t.note or "", docs.get(t.document_id, ""), t.source_row]
                  + ([t.purpose] if show_purpose else []))
    for col, width in zip("ABCDEFGHIJKLMN", [9, 12, 22, 7, 60, 13, 13, 13, 30, 14, 20, 30, 30, 9]):
        tx.column_dimensions[col].width = width
    tx.freeze_panes = "A2"
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
