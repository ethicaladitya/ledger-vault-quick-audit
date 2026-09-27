"""PDF statements: unlocking, account detection and transaction extraction.

Extraction tries real tables first (reusing the spreadsheet header mapper),
then falls back to reading text lines that start with a date and end with
amounts. For bank statements the running balance decides whether a row is a
debit or a credit, and a broken balance chain is reported as a warning.
"""
import io, re
from dataclasses import dataclass, field
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
DATE = rf"(?:\d{{1,2}}[/.-]\d{{1,2}}[/.-]\d{{2,4}}|\d{{1,2}}[ -]{MONTH}[ -,]*\d{{2,4}}|\d{{4}}-\d{{2}}-\d{{2}}|{MONTH}\s+\d{{1,2}},?\s+\d{{4}})"
TIME = r"\d{1,2}:\d{2}(?::\d{2})?(?:\s*[ap]m)?"
AMT = r"(?:\d{1,3}(?:,\d{2,3})+|\d+)\.\d{2}"
AMOUNT = rf"-?{AMT}"
# date [time] [value date [time]] narration amounts...  (amounts may carry +/- and a Cr/Dr/C/D marker)
LINE = re.compile(rf"^\s*({DATE})\s+(?:{TIME}\s+)?(?:{DATE}\s+(?:{TIME}\s+)?)?(.*?)\s+((?:[+-]?\s*{AMT}\s*(?:cr|dr|c|d)?\.?\s*)+)$", re.I)
AMOUNT_TAIL = re.compile(rf"([+-]?)\s*({AMT})\s*(cr|dr|c|d)?\b", re.I)
CURRENCY = re.compile(r"₹|`|\brs\.?(?=\s|\d)|\binr\b|\|", re.I)
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


@dataclass
class PdfContent:
    """Everything extracted from a PDF. Tables are kept separate: joining rows across tables glued
    unrelated summary rows (EMI tables, reward points) onto the last transaction."""
    text: str
    tables: list[list[list]] = field(default_factory=list)       # ruled tables, one list of rows per table
    text_tables: list[list[list]] = field(default_factory=list)  # tables found by column alignment (no ruling)
    layout_text: str = ""                                        # text with column spacing preserved
    pages: int = 0


def read_pdf(data: bytes) -> PdfContent:
    import pdfplumber
    content = PdfContent(text="")
    texts, layouts = [], []
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        content.pages = len(pdf.pages)
        for page in pdf.pages[:300]:
            texts.append(page.extract_text() or "")
            try:
                layouts.append(page.extract_text(layout=True) or "")
            except Exception:
                pass
            content.tables += [t for t in page.extract_tables() if t]
            try:
                content.text_tables += [t for t in page.extract_tables({"vertical_strategy": "text", "horizontal_strategy": "text"}) if t]
            except Exception:
                pass
    content.text = "\n".join(texts)
    content.layout_text = "\n".join(layouts)
    if len(re.sub(r"\s", "", content.text)) < 40:
        raise PdfError("This looks like a scanned image PDF. Scanned statements aren't supported yet; download the e-statement or Excel version instead.")
    return content


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
        # Some issuers (ICICI) print only the last 2 digits: 4854XXXXXXXXXX45
        m = m or re.search(r"\b\d{4}[x*•]{6,12}(\d{2,4})\b", low)
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


MARKERS = {"cr", "dr", "c", "d", "cr.", "dr."}


def clean_line(raw: str) -> str:
    """Normalise a statement text line: drop currency glyphs and the icons many card statements print after
    the amount (HDFC's coloured PI dot comes out as "l", "•", "●" or "(cid:3)"), keeping Cr/Dr/C/D markers."""
    line = re.sub(r"\(cid:\d+\)", " ", raw)
    line = CURRENCY.sub(" ", line)
    line = re.sub(r"[•●○◦▪■□►▶✓✔★☆]", " ", line)
    # Letters glued onto an amount ("100.00l") that aren't a Cr/Dr marker.
    line = re.sub(r"(\d\.\d{2})([^\d\s.,]{1,2})(?=\s|$)", lambda m: m.group(0) if m.group(2).lower() in MARKERS else m.group(1), line)
    tokens = re.sub(r"\s+", " ", line).strip().split(" ")
    # Trailing 1-3 character tokens without digits after the last amount: icons, not data.
    # A "+" printed after the amount marks a credit (HDFC shows credits as a green "+").
    if len(tokens) > 2 and tokens[-1] == "+" and re.fullmatch(AMT, tokens[-2]):
        tokens[-1] = "Cr"
    while len(tokens) > 2 and not re.search(r"\d", tokens[-1]) and len(tokens[-1]) <= 3 and tokens[-1].lower() not in MARKERS \
            and any(re.fullmatch(rf"[+-]?{AMT}", t) for t in tokens[:-1]):
        tokens.pop()
    return " ".join(tokens)


def parse_lines(text: str, kind: str, warnings: list[str]) -> list[dict]:
    from .ingestion import parse_date
    opening = re.search(rf"opening balance[^\d-]{{0,40}}({AMOUNT})", text, re.I)
    prev_balance = _amt(opening.group(1)) if opening else None
    rows, guessed, broken, extra_lines = [], 0, 0, 0
    for n, raw in enumerate(text.splitlines(), start=1):
        line = clean_line(raw)
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
        narration = re.sub(r"^\d{8,}\s+", "", narration)  # leading transaction/serial reference number
        if kind == "card":
            narration = re.sub(r"(\s+\+?\s?\d{1,5})+$", "", narration) if not re.search(r"\s-\s\d{1,5}$", narration) else narration  # trailing reward-points column ("30", "+ 12")
            narration = re.sub(r"(\s+[+C`])+$", "", narration)  # a rupee glyph some fonts extract as "C" or "`"
        if d is None or SKIP.search(narration):
            if SKIP.search(narration) and "opening" in narration.lower():
                amts = AMOUNT_TAIL.findall(m.group(3))
                prev_balance = _amt(amts[-1][1]) if amts else prev_balance
            continue
        # A leading "+" marks a credit on card statements (e.g. "+ 5,000.00" for a payment received).
        amts = [(abs(_amt(a)), (mk or ("cr" if sign == "+" else "")).lower()) for sign, a, mk in AMOUNT_TAIL.findall(m.group(3))]
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


def _rows_from_tables(tables: list[list[list]], kind: str, warnings: list[str]) -> list[dict]:
    """Map each table with its own header; a header-less table with the same number of columns right
    after one is treated as that table continuing on the next page."""
    from .ingestion import find_header, extract_rows
    out: list[dict] = []
    cols, width = None, None
    for table in tables:
        header = find_header(table)
        if header:
            idx, cols = header
            width = len(table[idx])
        elif cols is not None and table and len(table[0]) == width:
            idx = -1  # continuation of the previous table
        else:
            cols = width = None
            continue
        out += extract_rows(table, cols, idx, kind, warnings)
    return out


def _renumber(rows: list[dict]) -> list[dict]:
    for i, r in enumerate(rows, start=1):
        r["source_row"] = i  # rows from several tables/pages: keep row numbers unique within the file
    return rows


def parse_pdf(content: PdfContent, kind: str, warnings: list[str], diagnostics: dict | None = None) -> list[dict]:
    """Try each extraction method and keep the one that finds the most transactions."""
    attempts = []
    for name, fn in [("tables", lambda w: _rows_from_tables(content.tables, kind, w)),
                     ("aligned tables", lambda w: _rows_from_tables(content.text_tables, kind, w)),
                     ("text lines", lambda w: parse_lines(content.text, kind, w)),
                     ("layout lines", lambda w: parse_lines(content.layout_text, kind, w))]:
        w: list[str] = []
        try:
            rows = fn(w)
        except Exception:
            rows = []
        attempts.append((len(rows), name, rows, w))
    if diagnostics is not None:
        diagnostics.update({name: n for n, name, _, _ in attempts})
        diagnostics["pages"] = content.pages
        diagnostics["date_lines"] = sum(1 for line in content.text.splitlines() if re.match(rf"\s*{DATE}", line.strip(), re.I))
    best = max(attempts, key=lambda a: a[0])  # ties keep the earliest (tables before text)
    n, name, rows, w = best
    if not rows:
        return []
    for x in w:
        if not x.startswith("Skipped") and x not in warnings:
            warnings.append(x)
    if "tables" not in name:
        warnings.append("Read from PDF text — compare the imported total with your statement.")
    return _renumber(rows)
