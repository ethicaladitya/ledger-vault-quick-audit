"""Statement ingestion: PDF / CSV / XLSX / XLS / ZIP bank and credit-card statements.

The generic parser finds the header row (Indian bank exports usually have
several lines of account details above it), maps common column names, and
keeps every imported row traceable to its file and row number.
"""
import csv, hashlib, io, re, zipfile
from collections import Counter
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path, PurePosixPath
from sqlalchemy.orm import Session
from ..models import SourceDocument, FinancialAccount, Transaction, AuditEvent, UserRule
from .rules import classify
from .passwords import Hints
from .pdf import NeedsPassword, PdfError, unlock, read_pdf, detect, parse_pdf, account_name as pdf_account_name

MAX_FILE = 50 * 1024 * 1024
SUPPORTED = {".pdf", ".csv", ".txt", ".xlsx", ".xlsm", ".xls"}

# Ordered by preference: the first synonym found wins for each field.
COLUMNS = {
    "date": ["date", "txn date", "transaction date", "tran date", "trans date", "posting date", "date of transaction", "value date", "value dt", "txn dt"],
    "narration": ["narration", "description", "particulars", "transaction details", "transaction description", "transaction remarks", "remarks", "details", "transaction particulars", "merchant name", "merchant"],
    "debit": ["debit", "withdrawal amt", "withdrawal amount", "withdrawal", "withdrawals", "debit amount", "debit amt", "amount debited", "dr amount", "dr"],
    "credit": ["credit", "deposit amt", "deposit amount", "deposit", "deposits", "credit amount", "credit amt", "amount credited", "cr amount", "cr"],
    "amount": ["amount", "transaction amount", "txn amount", "amt", "billing amount", "amount in inr", "inr amount"],
    "drcr": ["dr/cr", "cr/dr", "dr / cr", "debit/credit", "type", "transaction type", "txn type", "dr cr"],
    "balance": ["balance", "closing balance", "available balance", "running balance", "balance amount", "closing bal"],
}
DEBIT_MARKERS = {"d", "dr", "debit", "withdrawal", "db"}
CREDIT_MARKERS = {"c", "cr", "credit", "deposit"}
DATE_FORMATS = ["%Y-%m-%d", "%d/%m/%Y", "%d/%m/%y", "%d-%m-%Y", "%d-%m-%y", "%d.%m.%Y", "%d.%m.%y", "%d %b %Y", "%d-%b-%Y", "%d-%b-%y", "%d %b %y", "%d %B %Y", "%d-%B-%Y", "%b %d, %Y", "%Y/%m/%d", "%d/%b/%Y"]


class ImportError_(ValueError):
    pass


def financial_year(d: date) -> str:
    start = d.year if d.month >= 4 else d.year - 1
    return f"{start}-{(start + 1) % 100:02d}"


def _norm_header(value) -> str:
    text = str(value or "").lower().replace("\n", " ")
    text = re.sub(r"\((inr|rs\.?|₹)\s*\)|\binr\b|₹|rs\.", " ", text)
    text = re.sub(r"[.:_*]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def dec(value) -> Decimal:
    """Parse an Indian-formatted amount. Returns a signed Decimal; Dr/parentheses are negative."""
    if value is None:
        return Decimal("0")
    if isinstance(value, (int, float, Decimal)):
        return Decimal(str(value)).quantize(Decimal("0.01"))
    text = str(value).strip()
    negative = text.startswith("(") and text.endswith(")") or text.startswith("-") or re.search(r"\bdr\.?$", text, re.I) is not None
    cleaned = re.sub(r"[^0-9.]", "", text)
    if not cleaned or cleaned == ".":
        return Decimal("0")
    try:
        amount = Decimal(cleaned).quantize(Decimal("0.01"))
    except InvalidOperation:
        return Decimal("0")
    return -amount if negative else amount


def parse_date(value) -> date | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = re.sub(r"\s+", " ", str(value)).strip()
    candidates = [text]
    if re.match(r"^\d", text):
        candidates += [re.split(r"[ T]", text)[0], " ".join(text.split(" ")[:3])]
    for candidate in candidates:
        for fmt in DATE_FORMATS:
            try:
                parsed = datetime.strptime(candidate, fmt).date()
                if 1990 <= parsed.year <= 2100:
                    return parsed
            except ValueError:
                pass
    return None


def safe_zip(data: bytes) -> list[tuple[str, bytes]]:
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        entries = [e for e in z.infolist() if not e.is_dir()]
        if len(entries) > 500 or sum(e.file_size for e in entries) > 250 * 1024 * 1024:
            raise ImportError_("ZIP resource limit exceeded (max 500 files / 250 MB)")
        members = []
        for e in entries:
            p = PurePosixPath(e.filename.replace("\\", "/"))
            if p.is_absolute() or ".." in p.parts:
                raise ImportError_("Unsafe ZIP path")
            if p.name.startswith(".") or "__MACOSX" in p.parts or e.file_size > MAX_FILE:
                continue
            if p.suffix.lower() in SUPPORTED:
                members.append((str(p), z.read(e)))
        return members


# ---------- readers: every reader returns sheets as lists of rows ----------

def _read_csv(data: bytes) -> list[list[list]]:
    for encoding in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            text = data.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    try:
        dialect = csv.Sniffer().sniff(text[:8192], delimiters=",;\t|")
    except csv.Error:
        dialect = csv.excel
    return [list(csv.reader(io.StringIO(text), dialect))]


def _read_xlsx(data: bytes) -> list[list[list]]:
    from openpyxl import load_workbook
    wb = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    try:
        return [[list(r) for r in ws.iter_rows(values_only=True)] for ws in wb.worksheets]
    finally:
        wb.close()


def _read_xls(data: bytes) -> list[list[list]]:
    import xlrd
    try:
        book = xlrd.open_workbook(file_contents=data)
    except xlrd.XLRDError:
        # Several banks serve HTML or CSV with an .xls extension.
        text = data[:2048].lower()
        if b"<html" in text or b"<table" in text:
            raise ImportError_("This .xls is really a web page export. Open it in Excel/LibreOffice and save as .xlsx or .csv, then upload again.")
        return _read_csv(data)
    sheets = []
    for sh in book.sheets():
        rows = []
        for r in range(sh.nrows):
            row = []
            for c in range(sh.ncols):
                cell = sh.cell(r, c)
                if cell.ctype == xlrd.XL_CELL_DATE:
                    row.append(xlrd.xldate_as_datetime(cell.value, book.datemode))
                else:
                    row.append(cell.value)
            rows.append(row)
        sheets.append(rows)
    return sheets


def read_sheets(filename: str, data: bytes) -> list[list[list]]:
    suffix = Path(filename).suffix.lower()
    if suffix in {".xlsx", ".xlsm"}:
        return _read_xlsx(data)
    if suffix == ".xls":
        return _read_xls(data)
    if suffix in {".csv", ".txt"}:
        return _read_csv(data)
    raise ImportError_(f"Unsupported file type {suffix or '(none)'}. Upload PDF, CSV, XLS, XLSX or a ZIP of those.")


# ---------- header detection and row mapping ----------

def _match_columns(row: list) -> dict[str, int]:
    headers = [_norm_header(v) for v in row]
    found: dict[str, int] = {}
    used: set[int] = set()
    for field, synonyms in COLUMNS.items():
        for syn in synonyms:
            idx = next((i for i, h in enumerate(headers) if i not in used and h == syn), None)
            if idx is None and len(syn) > 3:
                idx = next((i for i, h in enumerate(headers) if i not in used and h.startswith(syn + " ")), None)
            if idx is not None:
                found[field] = idx
                used.add(idx)
                break
    return found


def find_header(rows: list[list]) -> tuple[int, dict[str, int]] | None:
    for i, row in enumerate(rows[:60]):
        cols = _match_columns(row)
        if "date" in cols and "narration" in cols and ({"debit", "credit"} & cols.keys() or "amount" in cols):
            return i, cols
    return None


def _cell(row: list, idx: int | None):
    if idx is None or idx >= len(row):
        return None
    return row[idx]


def extract_rows(rows: list[list], cols: dict[str, int], header_idx: int, kind: str, warnings: list[str]):
    """Yield dicts: source_row, date, narration, debit, credit, balance."""
    out: list[dict] = []
    skipped = 0
    sign_assumed = False
    for i in range(header_idx + 1, len(rows)):
        row = rows[i]
        if not any(str(v).strip() for v in row if v is not None):
            continue
        d = parse_date(_cell(row, cols["date"]))
        narration = re.sub(r"\s+", " ", str(_cell(row, cols["narration"]) or "")).strip()
        if d is None:
            # Multi-line narrations: a row with only text continues the previous transaction.
            if out and narration and not any(_cell(row, cols.get(k)) not in (None, "") for k in ("debit", "credit", "amount")):
                out[-1]["narration"] = (out[-1]["narration"] + " " + narration)[:2000]
            else:
                skipped += 1
            continue
        if "debit" in cols or "credit" in cols:
            debit, credit = abs(dec(_cell(row, cols.get("debit")))), abs(dec(_cell(row, cols.get("credit"))))
        else:
            raw = _cell(row, cols["amount"])
            amount = dec(raw)
            marker = re.sub(r"[^a-z]", "", str(_cell(row, cols.get("drcr")) or "").lower())
            marker = marker if marker in DEBIT_MARKERS | CREDIT_MARKERS else ""
            if not marker and isinstance(raw, str) and re.search(r"\b(cr|dr)\.?\s*$", raw, re.I):
                marker = re.search(r"\b(cr|dr)\.?\s*$", raw, re.I).group(1).lower()
            if marker in DEBIT_MARKERS:
                debit, credit = abs(amount), Decimal("0")
            elif marker in CREDIT_MARKERS:
                debit, credit = Decimal("0"), abs(amount)
            else:
                # No explicit marker: bank exports use negative = debit; card exports list spends as positive.
                sign_assumed = True
                is_debit = amount > 0 if kind == "card" else amount < 0
                debit, credit = (abs(amount), Decimal("0")) if is_debit else (Decimal("0"), abs(amount))
        if debit == 0 and credit == 0:
            skipped += 1
            continue
        bal = _cell(row, cols.get("balance"))
        out.append({"source_row": i + 1, "date": d, "narration": narration or "(no narration)", "debit": debit, "credit": credit,
                    "balance": dec(bal) if bal not in (None, "") else None})
    if skipped:
        warnings.append(f"Skipped {skipped} row(s) without a valid date or amount (totals, opening balance, footers).")
    if sign_assumed:
        warnings.append("No Dr/Cr column found; debit/credit was inferred from the amount sign — spot-check a few rows.")
    return out


class Loaded:
    """A statement read into memory: PDF text/tables or spreadsheet rows, plus text for detection."""
    def __init__(self, text: str, sheets: list[list[list]] | None = None, tables: list[list] | None = None):
        self.text, self.sheets, self.tables = text, sheets, tables


def load(filename: str, data: bytes, hints: Hints) -> Loaded:
    if Path(filename).suffix.lower() == ".pdf":
        try:
            text, tables = read_pdf(unlock(data, hints))
        except PdfError as e:
            raise ImportError_(str(e))
        return Loaded(text, tables=tables)
    sheets = read_sheets(filename, data)
    text = "\n".join(" ".join(str(v) for v in row if v not in (None, "")) for sheet in sheets for row in sheet[:40])
    return Loaded(text, sheets=sheets)


def parse_loaded(loaded: Loaded, kind: str) -> tuple[list[dict], list[str]]:
    warnings: list[str] = []
    if loaded.sheets is None:
        rows = parse_pdf(loaded.text, loaded.tables or [], kind, warnings)
        if not rows:
            raise ImportError_("The PDF text was readable, but no transaction rows matched its layout. This statement needs a bank/card-specific parser; no rows were imported.")
        return rows, warnings
    for sheet in loaded.sheets:
        header = find_header(sheet)
        if header:
            idx, cols = header
            return extract_rows(sheet, cols, idx, kind, warnings), warnings
    raise ImportError_("Couldn't find a header row with Date, Narration/Description and Debit/Credit (or Amount) columns.")


def parse_statement(filename: str, data: bytes, kind: str, hints: Hints | None = None) -> tuple[list[dict], list[str]]:
    return parse_loaded(load(filename, data, hints or Hints()), kind)


# ---------- persistence ----------

def _dedupe_key(account_id: int, d: date, narration: str, debit: Decimal, credit: Decimal):
    # Only the start of the narration: PDF and Excel versions of one statement wrap and truncate it differently.
    return (account_id, d, re.sub(r"[^a-z0-9]+", "", narration.lower())[:10], Decimal(debit).quantize(Decimal("0.01")), Decimal(credit).quantize(Decimal("0.01")))


def find_same_statement(db: Session, workspace_id: int, rows: list[dict]) -> FinancialAccount | None:
    """An existing account that already holds most of these rows (same statement in another format or re-download)."""
    if len(rows) < 3:
        return None
    wanted = Counter((r["date"], Decimal(r["debit"]).quantize(Decimal("0.01")), Decimal(r["credit"]).quantize(Decimal("0.01"))) for r in rows)
    lo, hi = min(r["date"] for r in rows), max(r["date"] for r in rows)
    existing = (db.query(Transaction).join(FinancialAccount)
                .filter(FinancialAccount.workspace_id == workspace_id, Transaction.txn_date >= lo, Transaction.txn_date <= hi).all())
    per_account: dict[int, Counter] = {}
    for t in existing:
        per_account.setdefault(t.account_id, Counter())[(t.txn_date, Decimal(t.debit).quantize(Decimal("0.01")), Decimal(t.credit).quantize(Decimal("0.01")))] += 1
    best, best_score = None, 0.0
    for acc_id, have in per_account.items():
        overlap = sum((wanted & have).values())
        # Relative to the smaller side, so a statement that contains (or is contained by) an earlier one matches.
        score = overlap / min(len(rows), sum(have.values()))
        if overlap >= 3 and score > best_score:
            best, best_score = acc_id, score
    return db.get(FinancialAccount, best) if best is not None and best_score >= 0.8 else None


def get_account(db: Session, workspace_id: int, name: str, kind: str) -> FinancialAccount:
    name = name.strip()[:120] or "Imported account"
    account = db.query(FinancialAccount).filter_by(workspace_id=workspace_id, name=name).first()
    if not account:
        account = FinancialAccount(workspace_id=workspace_id, name=name, kind=kind if kind in {"bank", "card"} else "bank")
        db.add(account)
        db.flush()
    return account


def import_file(db: Session, filename: str, data: bytes, account_name: str, kind: str, workspace_id: int, hints: Hints | None = None) -> list[dict]:
    """Import one uploaded file (a ZIP expands to several). Returns one result per statement.

    With an empty account_name or kind="auto", the account is detected from the statement itself.
    """
    hints = hints or Hints()
    filename = PurePosixPath(filename.replace("\\", "/")).name or "upload"
    if len(data) > MAX_FILE:
        return [{"filename": filename, "error": "File exceeds the 50 MB limit"}]
    if filename.lower().endswith(".zip"):
        try:
            members = safe_zip(data)
        except (ImportError_, zipfile.BadZipFile) as e:
            return [{"filename": filename, "error": str(e) or "Not a valid ZIP file"}]
        if not members:
            return [{"filename": filename, "error": "ZIP contained no PDF/CSV/XLS/XLSX statements"}]
        results = []
        for name, content in members:
            results += import_file(db, f"{filename}:{name}".replace("/", "_"), content, account_name, kind, workspace_id, hints)
        return results

    digest = hashlib.sha256(data).hexdigest()
    existing = db.query(SourceDocument).filter_by(workspace_id=workspace_id, sha256=digest).first()
    if existing:
        return [{"filename": filename, "duplicate": True, "transactions": 0, "message": f"Already imported as {existing.filename}"}]
    try:
        loaded = load(filename, data, hints)
    except NeedsPassword:
        tried = "None of the passwords worked. " if not hints.empty else ""
        return [{"filename": filename, "needs_password": True, "error": f"{tried}This PDF is password-protected. Enter its password to unlock it."}]
    except ImportError_ as e:
        return [{"filename": filename, "error": str(e)}]
    except Exception:
        return [{"filename": filename, "error": "The file could not be read. Is it a valid PDF, CSV, XLS or XLSX statement?"}]

    info = detect(loaded.text + "\n" + filename.replace("_", " "))
    name = account_name.strip() or pdf_account_name(info, re.sub(r"[_-]+", " ", Path(filename).stem).strip()[:120] or "Imported account")
    known = db.query(FinancialAccount).filter_by(workspace_id=workspace_id, name=name[:120]).first()
    effective_kind = known.kind if known else kind if kind in {"bank", "card"} else info["kind"] or "bank"
    try:
        rows, warnings = parse_loaded(loaded, effective_kind)
    except ImportError_ as e:
        return [{"filename": filename, "error": str(e)}]
    except Exception:
        return [{"filename": filename, "error": "The file could not be read. Is it a valid PDF, CSV, XLS or XLSX statement?"}]
    if not rows:
        return [{"filename": filename, "error": "No transactions found in the file.", "warnings": warnings}]
    same = find_same_statement(db, workspace_id, rows)
    if same and (not known or same.id != known.id):
        # Same transactions already live in another account: merge instead of counting them twice.
        warnings.append(f"This looks like a statement already imported into “{same.name}” (another format or a re-download), "
                        f"so it was merged there instead of creating “{name}”. Only rows not already present were added.")
        account = same
    else:
        account = known or get_account(db, workspace_id, name, effective_kind)

    # Overlapping statement periods: skip rows already imported for this account from another file.
    seen = Counter(_dedupe_key(t.account_id, t.txn_date, t.narration, t.debit, t.credit)
                   for t in db.query(Transaction).filter_by(account_id=account.id))
    document = SourceDocument(workspace_id=workspace_id, account_id=account.id, sha256=digest, filename=filename[:255])
    db.add(document)
    db.flush()
    learned = {u.key: u.category for u in db.query(UserRule).filter_by(workspace_id=workspace_id)}
    count = overlap = 0
    for r in rows:
        key = _dedupe_key(account.id, r["date"], r["narration"], r["debit"], r["credit"])
        if seen[key] > 0:
            seen[key] -= 1
            overlap += 1
            continue
        db.add(Transaction(document_id=document.id, account_id=account.id, source_row=r["source_row"], txn_date=r["date"],
                           narration=r["narration"], debit=r["debit"], credit=r["credit"], balance=r["balance"],
                           category=classify(r["narration"], r["debit"] > 0, account.kind, learned), financial_year=financial_year(r["date"])))
        count += 1
    if overlap:
        warnings.append(f"Skipped {overlap} row(s) already imported for {account.name} from another statement (overlapping period).")
    dates = [r["date"] for r in rows]
    document.row_count = count
    document.warnings = "\n".join(warnings)
    db.add(AuditEvent(workspace_id=workspace_id, action="document_imported", detail=f"{filename}: {count} rows into {account.name}"))
    db.commit()
    return [{"filename": filename, "duplicate": False, "transactions": count, "account": account.name, "kind": account.kind,
             "document_id": document.id, "account_id": account.id,
             "period": f"{min(dates).isoformat()} to {max(dates).isoformat()}", "warnings": warnings}]


def import_path(db: Session, path: Path, account_name: str, kind: str, workspace_id: int, hints: Hints | None = None) -> list[dict]:
    return import_file(db, path.name, path.read_bytes(), account_name, kind, workspace_id, hints)
