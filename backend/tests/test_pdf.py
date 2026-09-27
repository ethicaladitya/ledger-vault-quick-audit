from datetime import date
from decimal import Decimal
import pytest
from app.services.passwords import Hints, candidates
from app.services.pdf import unlock, read_pdf, detect, parse_pdf, account_name, NeedsPassword
from tests.pdf_fixtures import card_statement, bank_statement, table_statement, encrypt
from tests.conftest import signup


def parse(data, kind=None):
    content = read_pdf(data)
    info = detect(content.text)
    warnings = []
    return info, parse_pdf(content, kind or info["kind"], warnings), warnings


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
    assert read_pdf(unlock(locked, Hints(name="Priya Sharma", dob="05/12/1990"))).text.startswith("HDFC Bank")
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


def test_icici_tables_are_not_glued_together():
    from tests.pdf_fixtures import icici_card_statement
    info, rows, _ = parse(icici_card_statement())
    assert info == {"kind": "card", "institution": "ICICI Bank", "last4": "45"}
    assert account_name(info, "x") == "ICICI Bank Credit Card ••45"
    got = [(r["date"].isoformat(), r["narration"], r["debit"], r["credit"]) for r in rows]
    assert got == [
        ("2025-09-05", "BBPS Payment received", 0, Decimal("12000.00")),
        ("2025-09-07", "AMAZON PAY INDIA BANGALORE IN", Decimal("2499.00"), 0),
        ("2025-09-09", "SWIGGY BANGALORE IN", Decimal("640.50"), 0),
        ("2025-09-12", "IRCTC NEW DELHI IN", Decimal("1845.00"), 0),     # page 2, table without a header
        ("2025-09-15", "REFUND FLIPKART", 0, Decimal("499.00")),
    ]
    assert len({r["source_row"] for r in rows}) == len(rows)


def test_hdfc_new_layout_with_time_and_plus_credits():
    from tests.pdf_fixtures import hdfc_new_card_statement
    info, rows, _ = parse(hdfc_new_card_statement())
    assert info["kind"] == "card" and info["institution"] == "HDFC Bank"
    got = [(r["narration"], r["debit"], r["credit"]) for r in rows]
    assert got == [
        ("ZOMATO GURGAON", Decimal("1240.00"), 0),
        ("NETFLIX.COM MUMBAI", Decimal("649.00"), 0),
        ("PAYMENT RECEIVED - NETBANKING", 0, Decimal("25000.00")),
        ("UBER INDIA SYSTEMS BANGALORE", Decimal("312.40"), 0),
        ("REVERSAL ZOMATO", 0, Decimal("240.00")),
    ]


def test_failed_pdf_reports_diagnostics(client):
    from tests.conftest import signup
    from tests.pdf_fixtures import _text_pdf
    h = signup(client)
    junk = _text_pdf(["Some Bank", "Welcome to your statement"] + ["Nothing to see here, no transactions at all"] * 5)
    res = client.post("/imports/upload", headers=h, data={"account_name": "", "kind": "auto"},
                      files=[("files", ("x.pdf", junk, "application/pdf"))]).json()["files"][0]
    assert "Diagnostics:" in res["error"] and "page(s)" in res["error"]


def test_tata_neu_hdfc_with_pi_dots():
    from tests.pdf_fixtures import tata_neu_hdfc_statement
    info, rows, _ = parse(tata_neu_hdfc_statement())
    assert info["kind"] == "card" and info["institution"] == "HDFC Bank" and info["last4"] == "45"
    got = [(r["date"].isoformat(), r["narration"], r["debit"], r["credit"]) for r in rows]
    assert got == [
        ("2025-12-02", "UPI-SURESHKUMARMEHAR", Decimal("10.00"), 0),
        ("2025-12-02", "UPI-SURESHKUMARMEHAR", Decimal("20.00"), 0),
        ("2025-12-02", "UPI-TUSHAR KANOJIYA SO RAJES", Decimal("256.00"), 0),
        ("2025-12-02", "TataRechargesMumbai", Decimal("358.90"), 0),
        ("2025-12-02", "TataRechargesMumbai", 0, Decimal("358.90")),
        ("2025-12-03", "UPI-SHAH KIRANA", Decimal("45.00"), 0),
        ("2025-12-05", "PAYMENT RECEIVED NETBANKING", 0, Decimal("12500.00")),
    ]


def test_clean_line_keeps_markers():
    from app.services.pdf import clean_line
    assert clean_line("02/12/2025| 20:48 UPI-X ₹ 10.00 l") == "02/12/2025 20:48 UPI-X 10.00"
    assert clean_line("02/12/2025 SALARY 1,000.00 Cr") == "02/12/2025 SALARY 1,000.00 Cr"
    assert clean_line("02/12/2025 REFUND 240.00 C") == "02/12/2025 REFUND 240.00 C"
    assert clean_line("02/12/2025 X (cid:3)10.00(cid:7)") == "02/12/2025 X 10.00"
    assert clean_line("02/12/2025 X 10.00l") == "02/12/2025 X 10.00"
    assert clean_line("02/12/2025 X 10.00Cr") == "02/12/2025 X 10.00Cr"


def test_card_emi_on_tax_paid_by_card_counts_once(client):
    from tests.conftest import signup
    from tests.pdf_fixtures import _text_pdf
    from app.services.pdf import clean_line
    assert clean_line("13/03/2026| 00:00 EMI CBDTGURGAON ₹ 50,425.00 +") == "13/03/2026 00:00 EMI CBDTGURGAON 50,425.00 Cr"
    h = signup(client)
    stmt = _text_pdf([
        "Tata Neu Infinity HDFC Bank Credit Card Statement",
        "Credit Card No. 4854XXXXXXXXXX45   Total Amount Due   Minimum Amount Due   Credit Limit",
        "DATE & TIME   TRANSACTION DESCRIPTION   Base NeuCoins*   AMOUNT   PI",
        "13/03/2026| 11:02   CBDTGURGAON - 1344                    Rs. 50,425.00 l",
        "13/03/2026| 00:00   EMI CBDTGURGAON                       Rs. 50,425.00 +",
        "15/03/2026| 00:00   EMI CBDTGURGAON                       Rs. 9,076.00",
        "15/03/2026| 00:00   EMI PROCESSING FEE CBDTGURGAON        Rs. 199.00",
        "16/03/2026| 20:10   SWIGGY BANGALORE                      Rs. 450.00 l",
    ])
    r = client.post("/imports/upload", headers=h, data={"account_name": "", "kind": "auto"},
                    files=[("files", ("4854XXXXXXXXXX45_19-03-2026_964.pdf", stmt, "application/pdf"))]).json()
    assert r["files"][0]["transactions"] == 5, r
    by = {(t["narration"], t["debit"], t["credit"]): t for t in client.get("/transactions", headers=h).json()["items"]}
    assert by[("CBDTGURGAON - 1344", "50425.00", "0.00")]["category"] == "tax_payment"
    assert by[("EMI CBDTGURGAON", "0.00", "50425.00")]["category"] == "card_emi"       # conversion credit, read from the trailing "+"
    assert by[("EMI CBDTGURGAON", "9076.00", "0.00")]["category"] == "card_emi"        # instalment
    assert by[("EMI PROCESSING FEE CBDTGURGAON", "199.00", "0.00")]["category"] == "bank_charges"
    rep = client.get("/report", headers=h).json()
    tax = next(c for c in rep["categories"] if c["category"] == "tax_payment")
    assert tax["debit"] == "50425.00" and tax["count"] == 1
    assert rep["totals"]["outflow"] == "51074.00"    # tax 50,425 + fee 199 + swiggy 450; EMI rows not spending again
    assert all(t["status"] == "ok" for t in client.get("/transactions?category=card_emi", headers=h).json()["items"])


def test_hdfc_rupee_glyph_credits_and_descriptions_above_the_date_line():
    from tests.pdf_fixtures import hdfc_wrapped_card_statement
    info, rows, _ = parse(hdfc_wrapped_card_statement())
    assert info["kind"] == "card"
    got = [(r["narration"], r["debit"], r["credit"]) for r in rows]
    assert got == [
        ("SWIGGY BANGALORE", Decimal("450.00"), 0),     # the next row's first line is not glued on
        ("BPPY CC PAYMENT DP016014200917ohu7V (Ref# ST260160083000010244551)", 0, Decimal("25000.00")),
        ("AMAZON PAY INDIA BANGALORE", Decimal("1299.00"), 0),
        ("UBER INDIA SYSTEMS BANGALORE", Decimal("312.40"), 0),
        ("REFUND AMAZON PAY", 0, Decimal("1299.00")),
    ]
