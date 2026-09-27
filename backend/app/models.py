from datetime import datetime, date
from decimal import Decimal
from sqlalchemy import String, Date, DateTime, ForeignKey, Numeric, Text, UniqueConstraint, Boolean
from sqlalchemy.orm import Mapped, mapped_column
from .database import Base

class Workspace(Base):
    __tablename__ = "workspaces"
    id: Mapped[int] = mapped_column(primary_key=True); name: Mapped[str] = mapped_column(String(120), default="My Ledger")
class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True); workspace_id: Mapped[int] = mapped_column(ForeignKey("workspaces.id")); email: Mapped[str] = mapped_column(String(255), unique=True, index=True); password_hash: Mapped[str] = mapped_column(String(300)); full_name: Mapped[str] = mapped_column(String(120)); role: Mapped[str] = mapped_column(String(20), default="owner"); is_active: Mapped[bool] = mapped_column(Boolean, default=True)
class TaxYear(Base):
    __tablename__ = "tax_years"
    id: Mapped[int] = mapped_column(primary_key=True); workspace_id: Mapped[int] = mapped_column(ForeignKey("workspaces.id")); financial_year: Mapped[str] = mapped_column(String(9)); assessment_year: Mapped[str] = mapped_column(String(9)); status: Mapped[str] = mapped_column(String(20), default="open"); __table_args__ = (UniqueConstraint("workspace_id", "financial_year", name="uq_workspace_fy"),)
class FinancialAccount(Base):
    __tablename__ = "financial_accounts"
    id: Mapped[int] = mapped_column(primary_key=True); workspace_id: Mapped[int] = mapped_column(ForeignKey("workspaces.id")); name: Mapped[str] = mapped_column(String(120)); kind: Mapped[str] = mapped_column(String(16)); masked_identity: Mapped[str] = mapped_column(String(32), default="unknown")
class SourceDocument(Base):
    __tablename__ = "source_documents"
    id: Mapped[int] = mapped_column(primary_key=True); sha256: Mapped[str] = mapped_column(String(64), unique=True); filename: Mapped[str] = mapped_column(String(255)); imported_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow); warnings: Mapped[str] = mapped_column(Text, default="")
class Statement(Base):
    __tablename__ = "statements"
    id: Mapped[int] = mapped_column(primary_key=True); account_id: Mapped[int] = mapped_column(ForeignKey("financial_accounts.id")); document_id: Mapped[int] = mapped_column(ForeignKey("source_documents.id")); start_date: Mapped[date|None] = mapped_column(Date, nullable=True); end_date: Mapped[date|None] = mapped_column(Date, nullable=True)
class Transaction(Base):
    __tablename__ = "transactions"; __table_args__ = (UniqueConstraint("document_id", "source_row", name="uq_source_row"),)
    id: Mapped[int] = mapped_column(primary_key=True); document_id: Mapped[int] = mapped_column(ForeignKey("source_documents.id")); account_id: Mapped[int] = mapped_column(ForeignKey("financial_accounts.id")); source_row: Mapped[int] = mapped_column(); txn_date: Mapped[date] = mapped_column(Date); narration: Mapped[str] = mapped_column(Text); debit: Mapped[Decimal] = mapped_column(Numeric(18,2), default=0); credit: Mapped[Decimal] = mapped_column(Numeric(18,2), default=0); category: Mapped[str] = mapped_column(String(64), default="uncategorized"); purpose: Mapped[str] = mapped_column(String(20), default="unknown"); status: Mapped[str] = mapped_column(String(24), default="unmatched"); match_group: Mapped[str|None] = mapped_column(String(36), nullable=True); financial_year: Mapped[str] = mapped_column(String(9), default="2026-27")
class AuditEvent(Base):
    __tablename__ = "audit_events"
    id: Mapped[int] = mapped_column(primary_key=True); action: Mapped[str] = mapped_column(String(80)); detail: Mapped[str] = mapped_column(Text); at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
