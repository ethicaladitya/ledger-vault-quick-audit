"""CRED card-bill payments: they never name the card, so they are matched by amount, by CRED's few-rupee
coins, or to the total due of an uploaded statement."""
from decimal import Decimal
from app.services.pdf import statement_due
from tests.conftest import signup
from tests.test_api import upload
from tests.pdf_fixtures import _text_pdf

CRED = "UPI/DR/51234/CRED/cred.club@axisb/Payment"


def card_pdf(last_day="28"):
    return _text_pdf([
        "HDFC Bank Credit Card Statement   Card No: 6529 XXXX XXXX 1047",
        "Previous Balance 5,000.00   Total Amount Due 3,850.00   Minimum Amount Due 200.00   Credit Limit 1,00,000.00",
        "Date Transaction Description Amount",
        "03/09/2025 SWIGGY BANGALORE 450.00",
        f"{last_day}/09/2025 AMAZON PAY INDIA 3,400.00",
        "05/09/2025 PAYMENT RECEIVED NETBANKING 5,000.00 Cr",
    ])


def upload_pdf(client, h, name, data):
    r = client.post("/imports/upload", headers=h, data={"account_name": "", "kind": "auto"}, files=[("files", (name, data, "application/pdf"))])
    assert r.status_code == 200, r.text
    return r.json()


def test_statement_due_is_the_amount_the_balances_prove():
    text = "Previous Balance 5,000.00  Total Amount Due 3,850.00  Minimum Amount Due 200.00\n"
    row = lambda d, c: {"debit": Decimal(d), "credit": Decimal(c)}
    assert statement_due(text, [row("450", "0"), row("3400", "0"), row("0", "5000")]) == Decimal("3850.00")
    assert statement_due(text, [row("450", "0")]) is None   # doesn't add up: no due is proven


def test_cred_coins_make_the_card_receive_a_few_rupees_more(client):
    h = signup(client)
    upload(client, h, [("bank.csv", f"date,narration,debit,credit\n2025-09-05,{CRED},4997,\n")], "HDFC Savings")
    upload(client, h, [("card.csv", "date,narration,debit,credit\n2025-09-01,SWIGGY,4997,\n2025-09-05,PAYMENT RECEIVED,,5000\n")], "HDFC Regalia", "card")
    rec = client.get("/reconciliation", headers=h).json()
    assert len(rec["matched"]) == 1 and not rec["open"]
    # A large gap is not a CRED coin: ₹60 off stays unmatched.
    upload(client, h, [("bank2.csv", f"date,narration,debit,credit\n2025-10-05,{CRED},4940,\n")], "HDFC Savings")
    upload(client, h, [("card2.csv", "date,narration,debit,credit\n2025-10-05,PAYMENT RECEIVED,,5000\n")], "HDFC Regalia", "card")
    assert len(client.get("/reconciliation", headers=h).json()["matched"]) == 1


def test_payment_of_an_uploaded_statements_total_due_is_explained(client):
    h = signup(client)
    upload_pdf(client, h, "hdfc-sep.pdf", card_pdf())
    # Paid on 12 Oct via CRED; its credit would be on the October statement, which isn't uploaded.
    res = upload(client, h, [("bank.csv", f"date,narration,debit,credit\n2025-10-12,{CRED},3850,\n")], "HDFC Savings")
    assert res["reconciliation"]["statement_paid"] == 1
    tx = next(t for t in client.get("/transactions", headers=h).json()["items"] if t["narration"] == CRED)
    assert tx["status"] == "statement_paid"
    rep = client.get("/report", headers=h).json()
    assert not rep["cards"]["missing_statements"]                                   # nothing reported missing
    assert rep["cards"]["statement_paid_total"] == "3850.00"
    assert Decimal(rep["cards"]["total_paid"]) == Decimal("5000.00") + Decimal("3850.00")  # counted once for AIS
    pair = client.get("/reconciliation", headers=h).json()["matched"][0]
    assert pair[1]["statement"] is True and "3850" in pair[1]["narration"]
    assert not client.get("/books", headers=h).json()["gaps"]
    # Too late to be this statement's bill (> 35 days after it): not explained.
    upload(client, h, [("bank2.csv", f"date,narration,debit,credit\n2025-12-20,{CRED},3850,\n")], "HDFC Savings")
    late = next(t for t in client.get("/transactions", headers=h).json()["items"] if t["date"] == "2025-12-20")
    assert late["status"] == "unmatched"


def test_reuploading_an_older_statement_records_its_total_due(client):
    h = signup(client)
    pdf = card_pdf()
    upload_pdf(client, h, "hdfc-sep.pdf", pdf)
    upload(client, h, [("bank.csv", f"date,narration,debit,credit\n2025-10-12,{CRED},3850,\n")], "HDFC Savings")
    from app.database import SessionLocal
    from app.models import SourceDocument
    with SessionLocal() as db:   # as if imported before total dues were kept
        for d in db.query(SourceDocument):
            d.total_due = None
        db.commit()
    upload(client, h, [("bank-again.csv", "date,narration,debit,credit\n2025-10-13,UPI-RAMESH,10,\n")], "HDFC Savings")  # re-reconcile
    assert next(t for t in client.get("/transactions", headers=h).json()["items"] if t["narration"] == CRED)["status"] == "unmatched"
    res = upload_pdf(client, h, "hdfc-sep.pdf", pdf)
    f = res["files"][0]
    assert f["duplicate"] is True and "total amount due is now recorded" in f["message"]
    assert client.get("/transactions?q=RAMESH", headers=h).json()["total"] == 1      # rows untouched
    assert next(t for t in client.get("/transactions", headers=h).json()["items"] if t["narration"] == CRED)["status"] == "statement_paid"
