"""PDF statements: unlocking, account detection and transaction extraction.

Extraction tries real tables first (reusing the spreadsheet header mapper),
then falls back to reading text lines that start with a date and end with
amounts. For bank statements the running balance decides whether a row is a
debit or a credit, and a broken balance chain is reported as a warning.
"""
import io, re
from decimal import Decimal
from .passwords import Hints, candidates

CARD_MARKERS = ["minimum amount due", "min amt due", "minimum due", "total amount due", "total dues", "payment due date",
                "credit limit", "available credit", "cash limit", "credit card statement", "card statement", "reward points"]
BANK_MARKERS = ["opening balance", "closing balance", "ifsc", "statement of account", "account statement", "savings account",
                "current account", "a/c no", "account no", "account number", "branch", "micr"]
INSTITUTIONS = [
    (r"sbi\s*card|sbi\s*credit\s*card", "SBI Card"), (r"american\s*express|amex", "American Express"),
    (r"hdfc\s*bank", "HDFC Bank"), (r"icici\s*bank", "ICICI Bank"), (r"state\s*bank\s*of\s*india|\bsbi\b", "SBI"),
    (r"axis\s*bank", "Axis Bank"), (r"kotak", "Kotak Mahindra Bank"), (r"idfc\s*first", "IDFC FIRST Bank"),
    (r"yes\s*bank", "Yes Bank"), (r"indusind", "IndusInd Bank"), (r"\brbl\b", "RBL Bank"), (r"au\s*small\s*finance", "AU Bank"),
    (r"federal\s*bank", "Federal Bank"), (r"bank\s*of\s*baroda", "Bank of Baroda"), (r"punjab\s*national", "PNB"),
    (r"canara\s*bank", "Canara Bank"), (r"union\s*bank", "Union Bank of India"), (r"standard\s*chartered", "Standard Chartered"),
    (r"\bhsbc\b", "HSBC"), (r"citi\s*bank|citibank", "Citibank"), (r"onecard|one\s*card", "OneCard"), (r"hdfc", "HDFC Bank"),
]
MONTH = r"(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*"
DATE = rf"(?:\d{{1,2}}[/.-]\d{{1,2}}[/.-]\d{{2,4}}|\d{{1,2}}[ -]{MONTH}[ -,]*\d{{2,4}}|\d{{4}}-\d{{2}}-\d{{2}})"
AMOUNT = r"-?(?:\d{1,3}(?:,\d{2,3})+|\d+)\.\d{2}"
LINE = re.compile(rf"^\s*({DATE})\s+(?:{DATE}\s+)?(.*?)\s+((?:{AMOUNT}\s*(?:cr|dr|c|d)?\.?\s*)+)$", re.I)
AMOUNT_TAIL = re.compile(rf"({AMOUNT})\s*(cr|dr|c|d)?\b", re.I)
SKIP = re.compile(r"opening balance|closing balance|\btotal\b|b/f|c/f|brought forward|carried forward|balance forward", re.I)
CREDIT_HINT = re.compile(r"\b(salary|interest|int\.?pd|refund|reversal|cashback|dividend|neft cr|imps cr|upi cr|by transfer|deposit|credit|cr)\b", re.I)


class NeedsPassword(Exception):
    pass


class PdfError(ValueError):
    pass


def unlock(data: bytes, hints: Hints) -> bytes:
    """Returns decrypted PDF bytes, trying the owner's password patterns. Raises NeedsPassword."""
    import pikepdf
    for pw in candidates(hints):
        try:
            with pikepdf.open(io.BytesIO(data), password=pw) as pdf:
                if not pdf.is_encrypted:
                    return data
                out = io.BytesIO()
                pdf.save(out, encryption=False)
                return out.getvalue()
        except pikepdf.PasswordError:
            continue
        except pikepdf.PdfError:
            raise PdfError("This PDF is damaged or not a real PDF.")
    raise NeedsPassword()


def read_pdf(data: bytes) -> tuple[str, list[list]]:
    import pdfplumber
    texts, tables = [], []
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        for page in pdf.pages[:300]:
            texts.append(page.extract_text() or "")
            for t in page.extract_tables():
                tables.extend(t)
    text = "\n".join(texts)
    if len(re.sub(r"\s", "", text)) < 40:
        raise PdfError("This looks like a scanned image PDF. Scanned statements aren't supported yet; download the e-statement or Excel version instead.")
    return text, tables


def detect(text: str) -> dict:
    """Guess kind (bank/card), institution and last four digits from statement text."""
    low = text.lower()
    card = sum(m in low for m in CARD_MARKERS)
    bank = sum(m in low for m in BANK_MARKERS)
    kind = "card" if card >= 2 and card >= bank - 1 else "bank" if bank >= 1 else ("card" if card else None)
    head = low[:4000]
    hits = [(m.start(), name) for pattern, name in INSTITUTIONS if (m := re.search(pattern, head))]
    institution = min(hits)[1] if hits else None
    last4 = None
    if kind == "card":
        m = re.search(r"(?:\d{4}|[x*•]{4})[ -]?(?:[\dx*•]{2,4})[ -]?[x*•]{2,4}[ -]?[x*•]{0,4}[ -]?(\d{4})\b", low)
        last4 = m.group(1) if m else None
    else:
        m = re.search(r"(?:a/?c|account)\s*(?:no|number|num)?\.?\s*:?\s*([x*\d]{6,20})", low)
        if m and re.search(r"\d{4}$", m.group(1)):
            last4 = m.group(1)[-4:]
    return {"kind": kind, "institution": institution, "last4": last4}


def account_name(info: dict, fallback: str) -> str:
    inst = info.get("institution")
    if not inst:
        return fallback
    kind = "Credit Card" if info.get("kind") == "card" else "Account"
    name = inst if "card" in inst.lower() or "express" in inst.lower() else f"{inst} {kind}"
    return f"{name} ••{info['last4']}" if info.get("last4") else name


def _amt(s: str) -> Decimal:
    return Decimal(s.replace(",", ""))


def parse_lines(text: str, kind: str, warnings: list[str]) -> list[dict]:
    from .ingestion import parse_date
    opening = re.search(rf"opening balance[^\d-]{{0,40}}({AMOUNT})", text, re.I)
    prev_balance = _amt(opening.group(1)) if opening else None
    rows, guessed, broken, extra_lines = [], 0, 0, 0
    for n, raw in enumerate(text.splitlines(), start=1):
        line = re.sub(r"₹|rs\.?\s|inr\s", " ", raw, flags=re.I).strip()
        m = LINE.match(line)
        if not m:
            # Wrapped narration: a short text-only line right after a transaction.
            if rows and extra_lines < 2 and line and not re.search(AMOUNT, line) and not re.match(DATE, line) \
                    and len(line) < 80 and not re.search(r"page|statement|balance|total|continued", line, re.I):
                rows[-1]["narration"] += " " + line
                extra_lines += 1
            else:
                extra_lines = 2
            continue
        extra_lines = 0
        d = parse_date(m.group(1))
        narration = re.sub(r"\s+", " ", m.group(2)).strip()
        if kind == "card":
            narration = re.sub(r"\s+\d{1,5}$", "", narration)  # trailing reward-points column
        if d is None or SKIP.search(narration):
            if SKIP.search(narration) and "opening" in narration.lower():
                amts = AMOUNT_TAIL.findall(m.group(3))
                prev_balance = _amt(amts[-1][0]) if amts else prev_balance
            continue
        amts = [(abs(_amt(a)), (mk or "").lower()) for a, mk in AMOUNT_TAIL.findall(m.group(3))]
        debit = credit = Decimal("0")
        balance = None
        if kind == "bank" and len(amts) >= 2:
            if len(amts) >= 3 and (amts[-3][0] == 0 or amts[-2][0] == 0):
                w, dpt = amts[-3][0], amts[-2][0]
                debit, credit, balance = w, dpt, amts[-1][0]
            else:
                amount, balance = amts[-2][0], amts[-1][0]
                if amts[-1][1] in ("dr", "d"):
                    balance = -balance  # overdrawn balance marked Dr
                if prev_balance is not None and abs(abs(balance - prev_balance) - amount) < Decimal("0.02"):
                    is_credit = balance > prev_balance
                elif amts[-2][1]:
                    is_credit = amts[-2][1] in ("cr", "c")
                else:
                    is_credit = bool(CREDIT_HINT.search(narration))
                    guessed += 1
                debit, credit = (Decimal("0"), amount) if is_credit else (amount, Decimal("0"))
            if prev_balance is not None and abs(prev_balance - debit + credit - balance) > Decimal("0.02"):
                broken += 1
            prev_balance = balance
        else:
            amount, marker = amts[-1]
            if marker in ("cr", "c"):
                credit = amount
            elif marker in ("dr", "d") or kind == "card":
                debit = amount
            elif CREDIT_HINT.search(narration):
                credit = amount
                guessed += 1
            else:
                debit = amount
                guessed += 1
        if debit == 0 and credit == 0:
            continue
        rows.append({"source_row": n, "date": d, "narration": narration or "(no narration)", "debit": debit, "credit": credit, "balance": balance})
    if guessed:
        warnings.append(f"Debit/credit was inferred from the narration for {guessed} row(s) — spot-check them.")
    if broken:
        warnings.append(f"{broken} row(s) don't follow the running balance; some lines may have been misread. Compare totals with the PDF.")
    return rows


def parse_pdf(text: str, tables: list[list], kind: str, warnings: list[str]) -> list[dict]:
    from .ingestion import find_header, extract_rows
    if tables:
        header = find_header(tables)
        if header:
            idx, cols = header
            table_warnings: list[str] = []
            rows = extract_rows(tables, cols, idx, kind, table_warnings)
            if rows:
                warnings += [w for w in table_warnings if not w.startswith("Skipped")]
                return rows
    rows = parse_lines(text, kind, warnings)
    if rows:
        warnings.append("Read from PDF text — compare the imported total with your statement.")
    return rows
