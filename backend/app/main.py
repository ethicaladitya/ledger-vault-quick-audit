import os, re
from decimal import Decimal
from pathlib import Path
from fastapi import FastAPI, Depends, HTTPException, UploadFile, File, Form, Query
from fastapi.responses import Response
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import func, or_
from sqlalchemy.orm import Session
from .database import get_db
from .models import Workspace, Transaction, FinancialAccount, User, SourceDocument, AuditEvent, UserRule
from .security import hash_password, verify_password, token_for, current_user, check_login_allowed, record_login_failure
from .services.ingestion import import_file, import_path, MAX_FILE
from .services.passwords import Hints
from .services.reconciliation import reconcile, base_status
from .services.report import fy_transactions, totals, category_summary, flags, export_xlsx
from .services.rules import CATEGORIES, NEUTRAL, merchant_key, classify
from . import migrate

# Registration is open only until the first account exists, unless explicitly enabled.
ALLOW_REGISTRATION = os.getenv("ALLOW_REGISTRATION", "false").lower() == "true"
MAX_FILES_PER_UPLOAD = 50

app = FastAPI(title="LedgerVault", version="0.2.0", docs_url=None, redoc_url=None, openapi_url=None)


@app.on_event("startup")
def startup():
    migrate.run()


class Register(BaseModel):
    email: EmailStr
    password: str = Field(min_length=10, max_length=200)
    full_name: str = Field(min_length=2, max_length=120)


class Login(BaseModel):
    email: EmailStr
    password: str = Field(max_length=200)


class TxUpdate(BaseModel):
    category: str | None = None
    note: str | None = Field(default=None, max_length=1000)
    apply_similar: bool = False  # also re-categorise same-counterparty rows and remember it for future uploads


class AccountUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    kind: str | None = Field(default=None, pattern="^(bank|card)$")


class ConfirmGroup(BaseModel):
    tx_ids: list[int] = Field(max_length=5000)
    category: str
    remember_key: str | None = Field(default=None, max_length=120)


class ConfirmImport(BaseModel):
    groups: list[ConfirmGroup] = Field(max_length=2000)


class FolderImport(BaseModel):
    path: str
    account_name: str = "Imported account"
    kind: str = "bank"


def _user_json(user: User) -> dict:
    return {"email": user.email, "full_name": user.full_name, "role": user.role}


def _money(v) -> str:
    return str(v) if v is not None else None


def _tx_json(t: Transaction, a: FinancialAccount | None = None) -> dict:
    label, group, hint = CATEGORIES.get(t.category, (t.category, "review", ""))
    return {"id": t.id, "date": t.txn_date.isoformat(), "narration": t.narration, "debit": str(t.debit), "credit": str(t.credit),
            "balance": _money(t.balance), "category": t.category, "category_label": label, "group": group, "itr_hint": hint,
            "category_source": t.category_source, "note": t.note, "status": t.status, "match_group": t.match_group,
            "financial_year": t.financial_year, "account_id": t.account_id, "account": a.name if a else None, "account_kind": a.kind if a else None,
            "document_id": t.document_id, "source_row": t.source_row}


# ---------------- auth ----------------

@app.get("/auth/config")
def auth_config(db: Session = Depends(get_db)):
    has_users = db.query(User.id).first() is not None
    return {"registration_open": ALLOW_REGISTRATION or not has_users, "has_users": has_users}


@app.post("/auth/register")
def register(body: Register, db: Session = Depends(get_db)):
    if not ALLOW_REGISTRATION and db.query(User.id).first() is not None:
        raise HTTPException(403, "Registration is closed on this server. Ask the owner for access.")
    email = body.email.lower()
    if db.query(User).filter_by(email=email).first():
        raise HTTPException(409, "Email already registered")
    ws = Workspace(name=f"{body.full_name}'s Ledger")
    db.add(ws)
    db.flush()
    user = User(workspace_id=ws.id, email=email, password_hash=hash_password(body.password), full_name=body.full_name)
    db.add(user)
    db.commit()
    db.refresh(user)
    return {"token": token_for(user), "user": _user_json(user)}


@app.post("/auth/login")
def login(body: Login, db: Session = Depends(get_db)):
    email = body.email.lower()
    check_login_allowed(email)
    user = db.query(User).filter_by(email=email).first()
    if not user or not verify_password(body.password, user.password_hash):
        record_login_failure(email)
        raise HTTPException(401, "Email or password is incorrect")
    return {"token": token_for(user), "user": _user_json(user)}


@app.get("/auth/me")
def me(user: User = Depends(current_user)):
    return _user_json(user)


@app.get("/health")
def health():
    return {"status": "ok"}


# ---------------- imports ----------------

@app.post("/imports/upload")
async def upload(files: list[UploadFile] = File(...), account_name: str = Form("", max_length=120),
                 kind: str = Form("auto", pattern="^(auto|bank|card)$"),
                 name: str = Form("", max_length=120), dob: str = Form("", max_length=20), pan: str = Form("", max_length=10),
                 extras: str = Form("", max_length=500), password: str = Form("", max_length=200),
                 db: Session = Depends(get_db), user: User = Depends(current_user)):
    """Leave account_name empty and kind=auto to detect accounts from the statements themselves.

    name/dob/pan/extras only generate candidate PDF passwords for this request; they are never stored or logged.
    """
    if len(files) > MAX_FILES_PER_UPLOAD:
        raise HTTPException(400, f"Upload at most {MAX_FILES_PER_UPLOAD} files at a time")
    hints = Hints(name=name, dob=dob, pan=pan, extras=[e for e in re.split(r"[,\s]+", extras) if e], passwords=[password] if password else [])
    results = []
    for f in files:
        data = await f.read(MAX_FILE + 1)
        results += import_file(db, f.filename or "upload", data, account_name, kind, user.workspace_id, hints)
    return {"files": results, "reconciliation": reconcile(db, user.workspace_id)}


def _sample_dir() -> Path:
    configured = os.getenv("SAMPLE_DATA_DIR")
    if configured:
        return Path(configured)
    local = Path(__file__).resolve().parents[2] / "sample-data"
    return local if local.is_dir() else Path("/imports")


@app.post("/imports/demo")
def import_demo(db: Session = Depends(get_db), user: User = Depends(current_user)):
    """Loads the synthetic sample statements so a new user can see how the app works."""
    root = _sample_dir()
    results = []
    for filename, account, kind in [("bank.csv", "Demo Bank (sample)", "bank"), ("card.csv", "Demo Credit Card (sample)", "card")]:
        if (root / filename).is_file():
            results += import_path(db, root / filename, account, kind, user.workspace_id)
    if not results:
        raise HTTPException(404, "Sample data is not available on this server")
    return {"files": results, "reconciliation": reconcile(db, user.workspace_id)}


@app.post("/imports/folder")
def folder_import(body: FolderImport, db: Session = Depends(get_db), user: User = Depends(current_user)):
    """Imports statements from a directory mounted into the API container under /imports."""
    root = Path(body.path).resolve()
    allowed = Path("/imports").resolve()
    if not root.is_relative_to(allowed) or not root.is_dir():
        raise HTTPException(403, "Path must be a directory within the configured /imports mount")
    results = []
    for p in sorted(root.rglob("*")):
        if p.is_file() and p.suffix.lower() in {".pdf", ".csv", ".xls", ".xlsx", ".zip"}:
            results += import_path(db, p, body.account_name, body.kind, user.workspace_id)
    return {"files": results, "reconciliation": reconcile(db, user.workspace_id)}


# ---------------- post-upload review ----------------

@app.get("/imports/review")
def import_review(docs: str = Query(..., max_length=2000), db: Session = Depends(get_db), user: User = Depends(current_user)):
    """Detected accounts and suggested categories for just-uploaded statements, grouped by payee."""
    ids = [int(x) for x in docs.split(",") if x.strip().isdigit()][:200]
    documents = db.query(SourceDocument).filter(SourceDocument.workspace_id == user.workspace_id, SourceDocument.id.in_(ids)).all()
    accounts = {a.id: a for a in db.query(FinancialAccount).filter_by(workspace_id=user.workspace_id)}
    rows = db.query(Transaction).filter(Transaction.document_id.in_([d.id for d in documents])).order_by(Transaction.txn_date).all()
    statements = []
    for d in documents:
        mine = [t for t in rows if t.document_id == d.id]
        a = accounts.get(d.account_id)
        statements.append({"document_id": d.id, "filename": d.filename, "account_id": d.account_id, "account": a.name if a else None,
                           "kind": a.kind if a else None, "transactions": len(mine),
                           "period": f"{mine[0].txn_date.isoformat()} to {mine[-1].txn_date.isoformat()}" if mine else None})
    groups: dict[tuple, dict] = {}
    for t in rows:
        key = merchant_key(t.narration)
        gk = (key or t.narration.lower(), t.category, t.debit > 0)
        g = groups.setdefault(gk, {"key": key, "example": t.narration, "category": t.category, "direction": "out" if t.debit > 0 else "in",
                                   "count": 0, "total": Decimal(), "tx_ids": [], "confirmed": True})
        g["count"] += 1
        g["total"] += t.debit if t.debit > 0 else t.credit
        g["tx_ids"].append(t.id)
        g["confirmed"] = g["confirmed"] and t.category_source == "user"
    out = sorted(groups.values(), key=lambda g: (CATEGORIES.get(g["category"], ("", "review", ""))[1] != "review", -g["count"], -g["total"]))
    for g in out:
        g["total"] = str(g["total"])
        g["needs_review"] = CATEGORIES.get(g["category"], ("", "review", ""))[1] == "review"
    return {"statements": statements, "groups": out}


@app.post("/imports/confirm")
def import_confirm(body: ConfirmImport, db: Session = Depends(get_db), user: User = Depends(current_user)):
    """Saves the reviewed categories; changed groups can be remembered as rules for future uploads."""
    updated = remembered = 0
    for g in body.groups:
        if g.category not in CATEGORIES:
            raise HTTPException(400, f"Unknown category {g.category}")
        rows = (db.query(Transaction).join(FinancialAccount)
                .filter(FinancialAccount.workspace_id == user.workspace_id, Transaction.id.in_(g.tx_ids)).all())
        for t in rows:
            t.category, t.category_source = g.category, "user"
        updated += len(rows)
        if g.remember_key:
            rule = db.query(UserRule).filter_by(workspace_id=user.workspace_id, key=g.remember_key).first()
            if rule:
                rule.category = g.category
            else:
                db.add(UserRule(workspace_id=user.workspace_id, key=g.remember_key, category=g.category))
            remembered += 1
    db.add(AuditEvent(workspace_id=user.workspace_id, action="import_confirmed", detail=f"{updated} rows confirmed; {remembered} rules remembered"))
    db.commit()
    return {"updated": updated, "remembered": remembered, "reconciliation": reconcile(db, user.workspace_id)}


@app.patch("/accounts/{account_id}")
def update_account(account_id: int, body: AccountUpdate, db: Session = Depends(get_db), user: User = Depends(current_user)):
    account = db.query(FinancialAccount).filter_by(id=account_id, workspace_id=user.workspace_id).first()
    if not account:
        raise HTTPException(404, "Account not found")
    if body.name and body.name.strip() != account.name:
        if db.query(FinancialAccount).filter_by(workspace_id=user.workspace_id, name=body.name.strip()).first():
            raise HTTPException(409, "You already have an account with that name")
        account.name = body.name.strip()
    if body.kind and body.kind != account.kind:
        account.kind = body.kind
        learned = {u.key: u.category for u in db.query(UserRule).filter_by(workspace_id=user.workspace_id)}
        for t in db.query(Transaction).filter(Transaction.account_id == account.id, Transaction.category_source != "user"):
            t.category = classify(t.narration, t.debit > 0, account.kind, learned)
    db.add(AuditEvent(workspace_id=user.workspace_id, action="account_updated", detail=f"account #{account.id}"))
    db.commit()
    reconcile(db, user.workspace_id)
    return {"id": account.id, "name": account.name, "kind": account.kind}


# ---------------- documents & accounts ----------------

@app.get("/accounts")
def accounts(db: Session = Depends(get_db), user: User = Depends(current_user)):
    counts = dict(db.query(Transaction.account_id, func.count(Transaction.id)).group_by(Transaction.account_id).all())
    return [{"id": a.id, "name": a.name, "kind": a.kind, "transactions": counts.get(a.id, 0)}
            for a in db.query(FinancialAccount).filter_by(workspace_id=user.workspace_id).order_by(FinancialAccount.name)]


@app.get("/documents")
def documents(db: Session = Depends(get_db), user: User = Depends(current_user)):
    accounts = {a.id: a for a in db.query(FinancialAccount).filter_by(workspace_id=user.workspace_id)}
    spans = {d: (lo, hi) for d, lo, hi in db.query(Transaction.document_id, func.min(Transaction.txn_date), func.max(Transaction.txn_date)).group_by(Transaction.document_id)}
    out = []
    for d in db.query(SourceDocument).filter_by(workspace_id=user.workspace_id).order_by(SourceDocument.imported_at.desc()):
        a = accounts.get(d.account_id)
        lo, hi = spans.get(d.id, (None, None))
        out.append({"id": d.id, "filename": d.filename, "imported_at": d.imported_at.isoformat(), "transactions": d.row_count,
                    "account": a.name if a else None, "kind": a.kind if a else None,
                    "from": lo.isoformat() if lo else None, "to": hi.isoformat() if hi else None,
                    "warnings": [w for w in (d.warnings or "").split("\n") if w]})
    return out


@app.delete("/documents/{doc_id}")
def delete_document(doc_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    doc = db.query(SourceDocument).filter_by(id=doc_id, workspace_id=user.workspace_id).first()
    if not doc:
        raise HTTPException(404, "Statement not found")
    removed = db.query(Transaction).filter_by(document_id=doc.id).delete()
    db.add(AuditEvent(workspace_id=user.workspace_id, action="document_deleted", detail=f"{doc.filename}: {removed} rows removed"))
    account_id = doc.account_id
    db.delete(doc)
    db.flush()
    if account_id and not db.query(Transaction.id).filter_by(account_id=account_id).first() and not db.query(SourceDocument.id).filter_by(account_id=account_id).first():
        db.query(FinancialAccount).filter_by(id=account_id, workspace_id=user.workspace_id).delete()
    db.commit()
    return {"removed": removed, "reconciliation": reconcile(db, user.workspace_id)}


# ---------------- ledger ----------------

@app.get("/years")
def years(db: Session = Depends(get_db), user: User = Depends(current_user)):
    rows = (db.query(Transaction.financial_year, func.count(Transaction.id)).join(FinancialAccount)
            .filter(FinancialAccount.workspace_id == user.workspace_id).group_by(Transaction.financial_year).all())
    return sorted([{"financial_year": fy, "transactions": n} for fy, n in rows], key=lambda r: r["financial_year"], reverse=True)


@app.get("/categories")
def categories():
    return [{"key": k, "label": label, "group": group, "itr_hint": hint} for k, (label, group, hint) in CATEGORIES.items()]


@app.get("/dashboard")
def dashboard(fy: str | None = None, db: Session = Depends(get_db), user: User = Depends(current_user)):
    rows = fy_transactions(db, user.workspace_id, fy)
    t = totals(rows)
    return {"income": str(t["inflow"]), "expenses": str(t["outflow"]), "refunds": str(t["refunds"]), "neutral": str(t["neutral"]),
            "transactions": len(rows), "exceptions": sum(tx.status in {"needs_review", "unmatched", "ambiguous"} for tx, _ in rows),
            "accounts": len({a.id for _, a in rows}), "flags": flags(rows, fy)}


@app.get("/transactions")
def transactions(fy: str | None = None, status: str | None = None, category: str | None = None, account_id: int | None = None,
                 q: str | None = Query(default=None, max_length=100), limit: int = Query(default=100, le=1000), offset: int = 0,
                 db: Session = Depends(get_db), user: User = Depends(current_user)):
    query = db.query(Transaction, FinancialAccount).join(FinancialAccount, Transaction.account_id == FinancialAccount.id).filter(FinancialAccount.workspace_id == user.workspace_id)
    if fy:
        query = query.filter(Transaction.financial_year == fy)
    if status == "exceptions":
        query = query.filter(Transaction.status.in_(["needs_review", "unmatched", "ambiguous"]))
    elif status:
        query = query.filter(Transaction.status == status)
    if category:
        query = query.filter(Transaction.category == category)
    if account_id:
        query = query.filter(Transaction.account_id == account_id)
    if q:
        like = f"%{q}%"
        query = query.filter(or_(Transaction.narration.ilike(like), Transaction.note.ilike(like)))
    total = query.count()
    rows = query.order_by(Transaction.txn_date.desc(), Transaction.id.desc()).offset(offset).limit(limit).all()
    return {"total": total, "items": [_tx_json(t, a) for t, a in rows]}


def _similar(db: Session, workspace_id: int, row: Transaction):
    """Other rows from the same counter-party that the user hasn't categorised by hand."""
    key = merchant_key(row.narration)
    if not key:
        return key, []
    candidates = (db.query(Transaction).join(FinancialAccount)
                  .filter(FinancialAccount.workspace_id == workspace_id, Transaction.id != row.id, Transaction.category_source != "user",
                          (Transaction.debit > 0) if row.debit > 0 else (Transaction.credit > 0)).all())
    return key, [t for t in candidates if merchant_key(t.narration) == key]


@app.patch("/transactions/{tx_id}")
def update_transaction(tx_id: int, body: TxUpdate, db: Session = Depends(get_db), user: User = Depends(current_user)):
    row = (db.query(Transaction).join(FinancialAccount).filter(Transaction.id == tx_id, FinancialAccount.workspace_id == user.workspace_id).first())
    if not row:
        raise HTTPException(404, "Transaction not found")
    changes = []
    if body.category is not None and body.category not in CATEGORIES:
        raise HTTPException(400, "Unknown category")
    if body.category is not None and body.category != row.category:
        changes.append(f"category {row.category} -> {body.category}")
        row.category, row.category_source = body.category, "user"
    elif body.category is not None:
        row.category_source = "user"  # confirming the suggested category clears it from review
    if body.note is not None:
        changes.append("note updated")
        row.note = body.note.strip() or None
    applied = 0
    key, similar = _similar(db, user.workspace_id, row)
    if body.apply_similar and body.category and key:
        for t in similar:
            t.category, t.category_source = body.category, "user"
        applied = len(similar)
        rule = db.query(UserRule).filter_by(workspace_id=user.workspace_id, key=key).first()
        if rule:
            rule.category = body.category
        else:
            db.add(UserRule(workspace_id=user.workspace_id, key=key, category=body.category))
        changes.append(f"applied to {applied} similar and remembered for '{key}'")
    db.add(AuditEvent(workspace_id=user.workspace_id, action="transaction_updated", detail=f"#{row.id}: {'; '.join(changes) or 'confirmed'}"))
    db.commit()
    reconcile(db, user.workspace_id)
    db.refresh(row)
    pending = [t for t in similar if t.category != row.category] if not body.apply_similar else []
    return {**_tx_json(row, db.get(FinancialAccount, row.account_id)), "applied": applied,
            "similar": {"key": key, "count": len(pending)} if pending and body.category else None}


@app.get("/reconciliation")
def reconciliation(fy: str | None = None, db: Session = Depends(get_db), user: User = Depends(current_user)):
    rows = [(t, a) for t, a in fy_transactions(db, user.workspace_id, fy) if t.category in NEUTRAL or t.match_group]
    groups: dict[str, list] = {}
    for t, a in rows:
        if t.match_group:
            groups.setdefault(t.match_group, []).append(_tx_json(t, a))
    return {"matched": [sorted(g, key=lambda x: x["credit"] != "0.00") for g in groups.values()],
            "open": [_tx_json(t, a) for t, a in rows if not t.match_group]}


@app.get("/report")
def report(fy: str | None = None, db: Session = Depends(get_db), user: User = Depends(current_user)):
    rows = fy_transactions(db, user.workspace_id, fy)
    t = totals(rows)
    return {"totals": {k: str(v) for k, v in t.items()}, "categories": category_summary(rows), "flags": flags(rows, fy)}


@app.get("/export.xlsx")
def export(fy: str | None = None, db: Session = Depends(get_db), user: User = Depends(current_user)):
    data = export_xlsx(db, user.workspace_id, fy)
    name = f"ledgervault-working-paper-{fy or 'all'}.xlsx"
    return Response(data, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": f'attachment; filename="{name}"', "Cache-Control": "no-store"})
