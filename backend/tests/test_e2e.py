from pathlib import Path
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.database import Base
from app.models import Workspace, Transaction
from app.services.ingestion import import_csv
from app.services.reconciliation import reconcile

def test_card_settlement_is_neutral_and_idempotent(tmp_path):
    engine=create_engine("sqlite://"); Base.metadata.create_all(engine); db=sessionmaker(bind=engine)(); db.add(Workspace(name="test")); db.commit()
    bank=tmp_path/"bank.csv"; bank.write_text("date,narration,debit,credit\n2026-04-10,CARD PAYMENT HDFC,35000,\n")
    card=tmp_path/"card.csv"; card.write_text("date,narration,debit,credit\n2026-04-11,CARD PAYMENT RECEIVED,,35000\n2026-04-03,UPI SWIGGY,1200,\n")
    assert import_csv(db,bank,"HDFC Bank","bank")["transactions"]==1
    assert reconcile(db)["confirmed"]==0
    import_csv(db,card,"HDFC Card","card"); assert reconcile(db)["confirmed"]==1
    rows=db.query(Transaction).all(); assert len(rows)==3
    assert [r for r in rows if r.status=="confirmed_settlement"]
    assert import_csv(db,card,"HDFC Card","card")["duplicate"] is True
    assert db.query(Transaction).count()==3
