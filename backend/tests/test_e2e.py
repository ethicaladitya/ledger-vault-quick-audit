from app.models import Workspace, Transaction
from app.services.ingestion import import_path
from app.services.reconciliation import reconcile


def test_card_settlement_is_neutral_and_idempotent(db, tmp_path):
    ws = Workspace(name="test"); db.add(ws); db.commit()
    bank = tmp_path / "bank.csv"; bank.write_text("date,narration,debit,credit\n2026-04-10,CARD PAYMENT HDFC,35000,\n")
    card = tmp_path / "card.csv"; card.write_text("date,narration,debit,credit\n2026-04-11,CARD PAYMENT RECEIVED,,35000\n2026-04-03,UPI SWIGGY,1200,\n")
    assert import_path(db, bank, "HDFC Bank", "bank", ws.id)[0]["transactions"] == 1
    assert reconcile(db, ws.id)["confirmed"] == 0
    import_path(db, card, "HDFC Card", "card", ws.id)
    assert reconcile(db, ws.id)["confirmed"] == 1
    rows = db.query(Transaction).all()
    assert len(rows) == 3
    assert sum(r.status == "confirmed_settlement" for r in rows) == 2
    assert next(r for r in rows if "SWIGGY" in r.narration).category == "dining"
    assert import_path(db, card, "HDFC Card", "card", ws.id)[0]["duplicate"] is True
    assert db.query(Transaction).count() == 3
    assert reconcile(db, ws.id)["confirmed"] == 1  # re-running is stable
