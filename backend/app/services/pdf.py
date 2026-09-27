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
# The narration may be empty: HDFC prints a two-line description above and below the date line.
LINE = re.compile(rf"^\s*({DATE})\s+(?:{TIME}\s+)?(?:{DATE}\s+(?:{TIME}\s+)?)?(?:(.*?)\s+)?((?:[+-]?\s*{AMT}\s*(?:cr|dr|c|d)?\.?\s*)+)$", re.I)
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
    # HDFC prints credits as "+ ₹ 25,000.00" and the ₹ glyph often extracts as "C": "+ C 25,000.00". Unless the
    # "+" is tied to the amount here, it is cut off with the glyph and every payment received reads as a purchase.
    line = re.sub(rf"(?<!\S)\+\s*(?:C\s+)?({AMT})(?!\S)", r"\1 Cr", line)
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


# Loose reading, used only when the strict one fails (see parse_pdf): amounts may lack paise if they are
# digit-grouped ("1,250"), and anything after the first amount (reward points, status) is ignored.
MONEY = rf"(?<![\w,.])(?:{AMT}|\d{{1,3}}(?:,\d{{2,3}})+)(?![\d,.])"
LOOSE = re.compile(rf"^\s*({DATE})\s+(?:{TIME}\s+)?(?:{DATE}\s+(?:{TIME}\s+)?)?(.*?)\s*([+-]?)\s*({MONEY})\s*(cr|dr|c|d)?\b", re.I)


def _loose_match(line: str):
    m = LOOSE.match(line)
    if not m:
        return None
    amount = m.group(4).replace(",", "")
    return m.group(1), m.group(2), f"{m.group(3)}{amount if '.' in amount else amount + '.00'} {m.group(5) or ''}".strip()


def _joined_lines(text: str) -> list[str]:
    """Rows whose date, description and amount come out on separate lines: join a date line that has no amount
    with the lines after it, up to the first one with an amount. Nothing is joined if no amount follows."""
    raw = [l.strip() for l in text.splitlines()]
    out, i = [], 0
    while i < len(raw):
        head = re.match(rf"{DATE}(?:\s+{TIME})?", raw[i], re.I)
        if head and not re.search(MONEY, clean_line(raw[i][head.end():])):
            parts, j = [raw[i]], i + 1
            while j < len(raw) and len(parts) < 4 and raw[j] and not re.match(DATE, raw[j], re.I):
                parts.append(raw[j])
                j += 1
                if re.search(MONEY, clean_line(parts[-1])):
                    break
            if len(parts) > 1 and re.search(MONEY, clean_line(parts[-1])):
                out.append(" ".join(parts))
                i = j
                continue
        out.append(raw[i])
        i += 1
    return out


def parse_lines(text: str, kind: str, warnings: list[str], loose: bool = False) -> list[dict]:
    from .ingestion import parse_date
    opening = re.search(rf"opening balance[^\d-]{{0,40}}({AMOUNT})", text, re.I)
    prev_balance = _amt(opening.group(1)) if opening else None
    rows, guessed, broken, extra_lines = [], 0, 0, 0
    for n, raw in enumerate(_joined_lines(text) if loose else text.splitlines(), start=1):
        line = clean_line(raw)
        m = LINE.match(line)
        m = (m.group(1), m.group(2), m.group(3)) if m else _loose_match(line) if loose else None
        if not m:
            # Wrapped narration: a short text-only line right after a transaction.
            if rows and extra_lines < 2 and line and not re.search(AMOUNT, line) and not re.match(DATE, line) \
                    and len(line) < 80 and not re.search(r"page|statement|balance|total|continued", line, re.I):
                rows[-1]["narration"] += " " + line
                rows[-1]["_wrapped"].append(line)
                extra_lines += 1
            else:
                extra_lines = 2
            continue
        extra_lines = 0
        d = parse_date(m[0])
        narration = re.sub(r"\s+", " ", m[1] or "").strip()
        narration = re.sub(r"^\d{8,}\s+", "", narration)  # leading transaction/serial reference number
        if kind == "card":
            # Trailing reward points ("30", "+ 12") and a rupee glyph some fonts extract as "C" or "`", in either order.
            tail = r"(\s+[+C`])+$" if re.search(r"\s-\s\d{1,5}$", narration) else r"(\s+(?:[+C`]|\+?\s?\d{1,5}))+$"
            narration = re.sub(r"^[+C`](\s+|$)", "", re.sub(tail, "", " " + narration).strip())
        if not narration and rows and rows[-1]["_wrapped"]:
            # Nothing on the date line: the description's first line was printed above it and got attached to the
            # previous transaction as a wrapped line. Move it back, or that purchase reads as e.g. "CC PAYMENT".
            narration = rows[-1]["_wrapped"].pop()
            rows[-1]["narration"] = rows[-1]["narration"][: -len(narration) - 1]
        if d is None or SKIP.search(narration):
            if SKIP.search(narration) and "opening" in narration.lower():
                amts = AMOUNT_TAIL.findall(m[2])
                prev_balance = _amt(amts[-1][1]) if amts else prev_balance
            continue
        # A leading "+" marks a credit on card statements (e.g. "+ 5,000.00" for a payment received).
        amts = [(abs(_amt(a)), (mk or ("cr" if sign == "+" else "")).lower()) for sign, a, mk in AMOUNT_TAIL.findall(m[2])]
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
        rows.append({"source_row": n, "date": d, "narration": narration, "debit": debit, "credit": credit, "balance": balance, "_wrapped": []})
    for r in rows:
        del r["_wrapped"]
        r["narration"] = r["narration"].strip() or "(no narration)"
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


def card_totals_check(text: str, rows: list[dict]) -> bool | None:
    """Does previous balance + purchases − payments/credits = total due, for amounts printed outside the
    transaction lines? True if some pair fits, False if none does, None if the statement prints no summary
    amounts. A payment read as a purchase (or a dropped row) breaks the equation, so this catches what
    a layout change does silently."""
    fits = _balance_fits(text, rows)
    return None if fits is None else bool(fits)


def _summary_lines(text: str) -> list[str]:
    return [clean_line(l) for l in text.splitlines() if l.strip() and not re.match(rf"\s*{DATE}", l.strip(), re.I)]


def _balance_fits(text: str, rows: list[dict]) -> list[tuple[Decimal, Decimal]] | None:
    """(previous balance, total due) pairs among the printed summary amounts that the parsed rows reconcile."""
    debits = sum((r["debit"] for r in rows), Decimal())
    credits = sum((r["credit"] for r in rows), Decimal())
    amounts = {abs(_amt(a)) for line in _summary_lines(text) for _, a, _ in AMOUNT_TAIL.findall(line)}
    if not amounts:
        return None
    tol = Decimal("1.00")
    return [(prev, due) for prev in amounts | {Decimal()} for due in amounts
            if abs(prev + debits - credits - due) <= tol or abs(prev + debits - credits + due) <= tol]  # a credit balance prints as due


TOTAL_DUE_LABEL = re.compile(r"total\s*(?:amount\s*)?dues?|amount\s*due|closing\s*balance", re.I)


def statement_due(text: str, rows: list[dict]) -> Decimal | None:
    """The card statement's total amount due, when the parsed rows prove it: the one due amount that previous
    balance + purchases − payments/credits works out to. A "Total Amount Due" label only breaks ties."""
    dues = {due for _, due in _balance_fits(text, rows) or [] if due > 0}
    if len(dues) > 1:
        lines = _summary_lines(text)
        labelled = set()
        for i, line in enumerate(lines):
            if TOTAL_DUE_LABEL.search(line) and not re.search(r"minimum|min\.? amt", line, re.I):
                for nearby in lines[i:i + 2]:
                    labelled |= {abs(_amt(a)) for _, a, _ in AMOUNT_TAIL.findall(nearby)}
        dues &= labelled
    return dues.pop() if len(dues) == 1 else None


def parse_pdf(content: PdfContent, kind: str, warnings: list[str], diagnostics: dict | None = None) -> list[dict]:
    """Try each extraction method and keep the best reading.

    Strict readings (tables, then date-led text lines) come first. The loose text readings (split rows joined,
    amounts without paise, trailing columns ignored) are used only when the strict ones find fewer than two rows,
    or, for a card, when a loose reading adds up against the statement's printed balances and no strict one does.
    Among readings that add up, the one with the most rows wins; otherwise the strict one with the most rows."""
    methods = [("tables", lambda w: _rows_from_tables(content.tables, kind, w)),
               ("aligned tables", lambda w: _rows_from_tables(content.text_tables, kind, w)),
               ("text lines", lambda w: parse_lines(content.text, kind, w)),
               ("layout lines", lambda w: parse_lines(content.layout_text, kind, w)),
               ("text lines (loose)", lambda w: parse_lines(content.text, kind, w, loose=True)),
               ("layout lines (loose)", lambda w: parse_lines(content.layout_text, kind, w, loose=True))]
    attempts = []
    for name, fn in methods:
        w: list[str] = []
        try:
            rows = fn(w)
        except Exception:
            rows = []
        check = card_totals_check(content.text, rows) if kind == "card" and rows else None
        attempts.append((len(rows), name, rows, w, check))
    date_lines = sum(1 for line in content.text.splitlines() if re.match(rf"\s*{DATE}", line.strip(), re.I))
    strict = max((a for a in attempts if "loose" not in a[1]), key=lambda a: a[0])  # ties keep the earliest
    adds_up = [a for a in attempts if a[4] is True]
    best = max(adds_up, key=lambda a: a[0]) if adds_up else strict if strict[0] >= 2 else max(attempts, key=lambda a: a[0])
    n, name, rows, w, check = best
    if diagnostics is not None:
        diagnostics.update({a[1]: a[0] for a in attempts})
        diagnostics.update({"pages": content.pages, "date_lines": date_lines, "used": name, "totals_check": check,
                            "total_due": statement_due(content.text, rows) if check else None})
    if not rows:
        return []
    for x in w:
        if not x.startswith("Skipped") and x not in warnings:
            warnings.append(x)
    if "tables" not in name:
        warnings.append("Read from PDF text — compare the imported total with your statement.")
    if len(rows) == 1 and date_lines > 1:
        warnings.append("Only one transaction was read from a statement with many dated lines; its layout probably isn't supported yet. "
                        "Check it before relying on this import.")
    if check is False:
        debits, credits = sum((r["debit"] for r in rows), Decimal()), sum((r["credit"] for r in rows), Decimal())
        warnings.append(f"Doesn't add up: purchases of {debits:,.2f} and payments/credits of {credits:,.2f} read from this statement don't "
                        "reconcile with its previous balance and total due. Some rows may be missing or have the wrong debit/credit "
                        "sign; check this statement before relying on it.")
    return _renumber(rows)
