from pathlib import Path
from decimal import Decimal
from fastapi import FastAPI, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import func
from sqlalchemy.orm import Session
from .database import Base, engine, get_db
from .models import Workspace, Transaction, FinancialAccount, User, TaxYear
from .security import hash_password, verify_password, token_for, current_user
from .services.ingestion import import_csv
from .services.reconciliation import reconcile

app=FastAPI(title="LedgerVault", version="0.1.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
@app.on_event("startup")
def startup():
    Base.metadata.create_all(engine)
    from .database import SessionLocal
    with SessionLocal() as db:
        if not db.query(Workspace).first(): db.add(Workspace(name="My Ledger")); db.commit()
class Register(BaseModel): email:EmailStr; password:str=Field(min_length=10); full_name:str=Field(min_length=2, max_length=120)
class Login(BaseModel): email:EmailStr; password:str
class FolderImport(BaseModel): path:str; account_name:str="Imported account"; kind:str="bank"; financial_year:str=Field(pattern=r"^\d{4}-\d{2}$")
@app.post("/auth/register")
def register(body:Register, db:Session=Depends(get_db)):
    email=body.email.lower()
    if db.query(User).filter_by(email=email).first(): raise HTTPException(409,"Email already registered")
    ws=Workspace(name=f"{body.full_name}'s Ledger"); db.add(ws); db.flush(); user=User(workspace_id=ws.id,email=email,password_hash=hash_password(body.password),full_name=body.full_name); db.add(user); db.add(TaxYear(workspace_id=ws.id, financial_year="2026-27", assessment_year="2027-28")); db.commit(); db.refresh(user); return {"token":token_for(user),"user":{"email":user.email,"full_name":user.full_name}}
@app.post("/auth/login")
def login(body:Login, db:Session=Depends(get_db)):
    user=db.query(User).filter_by(email=body.email.lower()).first()
    if not user or not verify_password(body.password,user.password_hash): raise HTTPException(401,"Email or password is incorrect")
    return {"token":token_for(user),"user":{"email":user.email,"full_name":user.full_name,"role":user.role}}
@app.get("/auth/me")
def me(user:User=Depends(current_user)): return {"email":user.email,"full_name":user.full_name,"role":user.role}
@app.get("/health")
def health(): return {"status":"ok"}
@app.post("/imports/folder")
def folder_import(body: FolderImport, db:Session=Depends(get_db), user:User=Depends(current_user)):
    root=Path(body.path).resolve(); allowed=Path("/imports").resolve()
    if not root.is_relative_to(allowed): raise HTTPException(403,"Path must be within a configured import mount")
    results=[]
    for p in root.rglob("*"):
        if p.is_file() and p.suffix.lower() in {".csv", ".zip"}:
            try: results.append(import_csv(db,p,body.account_name,body.kind,user.workspace_id,body.financial_year))
            except ValueError as e: results.append({"filename":p.name,"error":str(e)})
    outcome=reconcile(db); return {"files":results,"reconciliation":outcome}
@app.get("/dashboard")
def dashboard(db:Session=Depends(get_db), user:User=Depends(current_user)):
    tx=db.query(Transaction).join(FinancialAccount).filter(FinancialAccount.workspace_id==user.workspace_id).all(); income=sum((Decimal(str(t.credit)) for t in tx if t.category not in {"card_settlement","own_transfer"}),Decimal())
    expenses=sum((Decimal(str(t.debit)) for t in tx if t.category not in {"card_settlement","own_transfer"}),Decimal())
    neutral=sum((Decimal(str(t.debit)) for t in tx if t.category in {"card_settlement","own_transfer"}),Decimal())
    return {"income":str(income),"expenses":str(expenses),"neutral":str(neutral),"transactions":len(tx),"exceptions":sum(t.status in {"unmatched","ambiguous"} for t in tx),"accounts":db.query(FinancialAccount).filter_by(workspace_id=user.workspace_id).count()}
@app.get("/transactions")
def transactions(db:Session=Depends(get_db), user:User=Depends(current_user)):
    return [{"id":t.id,"date":t.txn_date,"narration":t.narration,"debit":str(t.debit),"credit":str(t.credit),"category":t.category,"status":t.status,"match_group":t.match_group,"financial_year":t.financial_year} for t in db.query(Transaction).join(FinancialAccount).filter(FinancialAccount.workspace_id==user.workspace_id).order_by(Transaction.txn_date.desc()).limit(500)]
@app.get("/reconciliation")
def reconciliation(db:Session=Depends(get_db)):
    return [{"id":t.id,"date":t.txn_date,"narration":t.narration,"amount":str(t.debit or t.credit),"status":t.status,"group":t.match_group} for t in db.query(Transaction).filter(Transaction.status!="unmatched").all()]
