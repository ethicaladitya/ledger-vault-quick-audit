from datetime import datetime, date
from decimal import Decimal
from sqlalchemy import String, Date, DateTime, ForeignKey, Numeric, Text, UniqueConstraint, Boolean, Integer
from sqlalchemy.orm import Mapped, mapped_column
from .database import Base


class Workspace(Base):
    __tablename__ = "workspaces"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), default="My Ledger")


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    workspace_id: Mapped[int] = mapped_column(ForeignKey("workspaces.id"))
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(300))
    full_name: Mapped[str] = mapped_column(String(120))
    role: Mapped[str] = mapped_column(String(20), default="owner")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class TaxYear(Base):
    __tablename__ = "tax_years"
    __table_args__ = (UniqueConstraint("workspace_id", "financial_year", name="uq_workspace_fy"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    workspace_id: Mapped[int] = mapped_column(ForeignKey("workspaces.id"))
    financial_year: Mapped[str] = mapped_column(String(9))
    assessment_year: Mapped[str] = mapped_column(String(9))
    status: Mapped[str] = mapped_column(String(20), default="open")


class FinancialAccount(Base):
    __tablename__ = "financial_accounts"
    id: Mapped[int] = mapped_column(primary_key=True)
    workspace_id: Mapped[int] = mapped_column(ForeignKey("workspaces.id"))
    name: Mapped[str] = mapped_column(String(120))
    kind: Mapped[str] = mapped_column(String(16))  # bank | card
    masked_identity: Mapped[str] = mapped_column(String(32), default="unknown")


class SourceDocument(Base):
    __tablename__ = "source_documents"
    __table_args__ = (UniqueConstraint("workspace_id", "sha256", name="uq_workspace_document"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    workspace_id: Mapped[int | None] = mapped_column(ForeignKey("workspaces.id"), nullable=True)
    account_id: Mapped[int | None] = mapped_column(ForeignKey("financial_accounts.id"), nullable=True)
    sha256: Mapped[str] = mapped_column(String(64))
    filename: Mapped[str] = mapped_column(String(255))
    imported_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    row_count: Mapped[int] = mapped_column(Integer, default=0)
    warnings: Mapped[str] = mapped_column(Text, default="")


class Statement(Base):
    __tablename__ = "statements"
    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("financial_accounts.id"))
    document_id: Mapped[int] = mapped_column(ForeignKey("source_documents.id"))
    start_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    end_date: Mapped[date | None] = mapped_column(Date, nullable=True)


class Transaction(Base):
    __tablename__ = "transactions"
    __table_args__ = (UniqueConstraint("document_id", "source_row", name="uq_source_row"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("source_documents.id"))
    account_id: Mapped[int] = mapped_column(ForeignKey("financial_accounts.id"))
    source_row: Mapped[int] = mapped_column()
    txn_date: Mapped[date] = mapped_column(Date)
    narration: Mapped[str] = mapped_column(Text)
    debit: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=0)
    credit: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=0)
    balance: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    category: Mapped[str] = mapped_column(String(64), default="uncategorized")
    category_source: Mapped[str] = mapped_column(String(8), default="rule")  # rule | user
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    purpose: Mapped[str] = mapped_column(String(20), default="unknown")
    status: Mapped[str] = mapped_column(String(24), default="ok")
    match_group: Mapped[str | None] = mapped_column(String(36), nullable=True)
    financial_year: Mapped[str] = mapped_column(String(9), default="2026-27")


class AuditEvent(Base):
    __tablename__ = "audit_events"
    id: Mapped[int] = mapped_column(primary_key=True)
    workspace_id: Mapped[int | None] = mapped_column(ForeignKey("workspaces.id"), nullable=True)
    action: Mapped[str] = mapped_column(String(80))
    detail: Mapped[str] = mapped_column(Text)
    at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
