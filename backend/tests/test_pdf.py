from datetime import date
from decimal import Decimal
import pytest
from app.services.passwords import Hints, candidates
from app.services.pdf import unlock, read_pdf, detect, parse_pdf, account_name, NeedsPassword
from tests.pdf_fixtures import card_statement, bank_statement, table_statement, encrypt
from tests.conftest import signup


def parse(data, kind=None):
    text, tables = read_pdf(data)
    info = detect(text)
    warnings = []
    return info, parse_pdf(text, tables, kind or info["kind"], warnings), warnings


def test_card_pdf_detected_and_parsed():
    info, rows, _ = parse(card_statement())
    assert info == {"kind": "card", "institution": "HDFC Bank", "last4": "9876"}
    assert account_name(info, "x") == "HDFC Bank Credit Card ••9876"
    assert [(r["date"], r["debit"], r["credit"]) for r in rows] == [
        (date(2025, 4, 2), Decimal("2999.00"), 0), (date(2025, 4, 4), Decimal("640.00"), 0), (date(2025, 4, 6), 0, Decimal("12340.00"))]
    assert rows[0]["narration"] == "AMAZON PAY INDIA PRIVATE LIMITED BANGALORE"  # points column dropped, wrapped line joined
    assert rows[1]["narration"] == "ZOMATO BANGALORE"


def test_bank_pdf_uses_running_balance_for_direction():
    info, rows, warnings = parse(bank_statement())
    assert info["kind"] == "bank" and info["institution"] == "SBI" and info["last4"] == "4521"
    assert [(r["debit"], r["credit"]) for r in rows] == [
        (0, Decimal("85000.00")), (Decimal("12340.00"), 0), (Decimal("5000.00"), 0), (0, Decimal("1499.00"))]
    assert rows[-1]["balance"] == Decimal("119159.00")
    assert not any("running balance" in w for w in warnings)


def test_table_pdf_uses_header_mapping():
    info, rows, _ = parse(table_statement())
    assert info["institution"] == "ICICI Bank"
    assert [(r["debit"], r["credit"]) for r in rows] == [(Decimal("450.00"), 0), (Decimal("2000.00"), 0), (0, Decimal("120.00"))]


def test_password_patterns():
    c = candidates(Hints(name="Priya Sharma", dob="1990-12-05", pan="abcde1234f", extras=["9876"]))
    for expected in ["PRIY0512", "priy0512", "Priy0512", "abcde1234f05121990", "05121990", "051219909876", "ABCDE1234F"]:
        assert expected in c
    locked = encrypt(card_statement(), "PRIY0512")
    with pytest.raises(NeedsPassword):
        unlock(locked, Hints())
    with pytest.raises(NeedsPassword):
        unlock(locked, Hints(name="Someone Else", dob="1990-12-05"))
    assert read_pdf(unlock(locked, Hints(name="Priya Sharma", dob="05/12/1990")))[0].startswith("HDFC Bank")
    assert unlock(locked, Hints(passwords=["PRIY0512"]))


def upload(client, h, files, **form):
    r = client.post("/imports/upload", headers=h, data=form, files=[("files", (n, d, "application/pdf")) for n, d in files])
    assert r.status_code == 200, r.text
    return r.json()


def test_upload_mixed_pdfs_auto_detects_accounts_and_unlocks(client):
    h = signup(client)
    locked = encrypt(card_statement(), "PRIY0512")
    res = upload(client, h, [("card.pdf", locked), ("sbi.pdf", bank_statement())])
    card, bank = res["files"]
    assert card["needs_password"] is True
    assert bank["account"] == "SBI Account ••4521" and bank["kind"] == "bank" and bank["transactions"] == 4

    # Retrying with the owner's details unlocks it; the bill payment then matches across accounts.
    res = upload(client, h, [("card.pdf", locked)], name="Priya Sharma", dob="1990-12-05")
    assert res["files"][0]["account"] == "HDFC Bank Credit Card ••9876" and res["files"][0]["kind"] == "card"
    assert res["reconciliation"]["confirmed"] == 1
    accounts = {a["name"]: a["kind"] for a in client.get("/accounts", headers=h).json()}
    assert accounts == {"SBI Account ••4521": "bank", "HDFC Bank Credit Card ••9876": "card"}
    # Nothing about the password hints is persisted.
    from app.models import AuditEvent, SourceDocument
    from app.database import SessionLocal
    with SessionLocal() as db:
        blob = " ".join(e.detail for e in db.query(AuditEvent)) + " ".join((d.warnings or "") + d.filename for d in db.query(SourceDocument))
    assert "1990" not in blob and "Priya" not in blob and "PRIY" not in blob


def test_explicit_password_and_named_account(client):
    h = signup(client)
    locked = encrypt(bank_statement(), "s3cret-pw")
    res = upload(client, h, [("stmt.pdf", locked)], password="s3cret-pw", account_name="Joint savings", kind="bank")
    assert res["files"][0]["account"] == "Joint savings" and res["files"][0]["transactions"] == 4
