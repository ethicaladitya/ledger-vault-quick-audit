import csv, hashlib, io, zipfile
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from sqlalchemy.orm import Session
from ..models import SourceDocument, FinancialAccount, Transaction, AuditEvent
from .rules import classify

MAX_FILE = 50 * 1024 * 1024
def dec(value):
    try: return Decimal(str(value or "0").replace(",", "").replace("₹", "").strip() or "0")
    except InvalidOperation: return Decimal("0")
def parse_date(value):
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%d %b %Y"):
        try: return datetime.strptime(str(value).strip(), fmt).date()
        except ValueError: pass
    raise ValueError(f"Unsupported date: {value}")
def safe_zip(path: Path):
    with zipfile.ZipFile(path) as z:
        entries=z.infolist()
        if len(entries)>500 or sum(x.file_size for x in entries)>250*1024*1024: raise ValueError("ZIP resource limit exceeded")
        if any(Path(x.filename).is_absolute() or ".." in Path(x.filename).parts for x in entries): raise ValueError("Unsafe ZIP path")
def import_csv(db: Session, path: Path, account_name: str, kind: str, workspace_id: int = 1, financial_year: str = "2026-27"):
    if path.stat().st_size > MAX_FILE: raise ValueError("File exceeds 50MB limit")
    digest=hashlib.sha256(path.read_bytes()).hexdigest()
    if db.query(SourceDocument).filter_by(sha256=digest).first(): return {"duplicate": True, "filename": path.name}
    if path.suffix.lower()==".zip": safe_zip(path); raise ValueError("ZIP passed safety validation; extraction adapters are not enabled yet")
    if path.suffix.lower() != ".csv": raise ValueError("This slice supports CSV input; add a tested adapter for this type")
    document=SourceDocument(sha256=digest, filename=path.name); db.add(document); db.flush()
    account=db.query(FinancialAccount).filter_by(workspace_id=workspace_id, name=account_name).first()
    if not account: account=FinancialAccount(workspace_id=workspace_id, name=account_name, kind=kind); db.add(account); db.flush()
    sample=path.read_bytes()[:4096].decode("utf-8-sig", errors="replace"); dialect=csv.Sniffer().sniff(sample, delimiters=",;\t|")
    reader=csv.DictReader(io.StringIO(path.read_text(encoding="utf-8-sig", errors="replace")), dialect=dialect)
    count=0
    for row_no,row in enumerate(reader, start=2):
        low={str(k).lower().strip():v for k,v in row.items()}; date_value=low.get("date") or low.get("transaction date")
        if not date_value: continue
        narration=low.get("narration") or low.get("description") or low.get("particulars") or ""
        txn=Transaction(document_id=document.id, account_id=account.id, source_row=row_no, txn_date=parse_date(date_value), narration=narration, debit=dec(low.get("debit")), credit=dec(low.get("credit")), category=classify(narration), financial_year=financial_year)
        db.add(txn); count+=1
    db.add(AuditEvent(action="document_imported", detail=f"{path.name}: {count} source rows")); db.commit()
    return {"duplicate": False, "filename":path.name, "transactions":count}
