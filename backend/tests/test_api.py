import io, zipfile
from tests.conftest import signup
from tests.test_parsers import HDFC_CSV

BANK = "date,narration,debit,credit\n2025-04-10,CREDIT CARD PAYMENT,35000,\n2025-04-12,UPI-RAMESH,500,\n"
CARD = "date,narration,debit,credit\n2025-04-11,PAYMENT RECEIVED THANK YOU,,35000\n2025-04-03,SWIGGY,1200,\n"


def upload(client, headers, files, account, kind="bank"):
    r = client.post("/imports/upload", headers=headers, data={"account_name": account, "kind": kind},
                    files=[("files", (name, content.encode() if isinstance(content, str) else content, "text/csv")) for name, content in files])
    assert r.status_code == 200, r.text
    return r.json()


def test_upload_review_report_and_export(client):
    h = signup(client)
    res = upload(client, h, [("bank.csv", BANK)], "HDFC Savings")
    assert res["files"][0]["transactions"] == 2
    res = upload(client, h, [("card.csv", CARD)], "HDFC Regalia", "card")
    assert res["reconciliation"]["confirmed"] == 1

    assert client.get("/years", headers=h).json()[0]["financial_year"] == "2025-26"
    dash = client.get("/dashboard?fy=2025-26", headers=h).json()
    assert dash["expenses"] == "1700.00"  # 500 UPI + 1200 card purchase; the 35,000 bill payment is neutral
    assert dash["neutral"] == "35000.00"
    assert dash["exceptions"] == 1

    review = client.get("/transactions?status=exceptions", headers=h).json()
    assert review["total"] == 1
    tx = review["items"][0]
    r = client.patch(f"/transactions/{tx['id']}", headers=h, json={"category": "rent", "note": "Flat rent to landlord"})
    assert r.status_code == 200 and r.json()["status"] == "ok"
    assert client.get("/dashboard", headers=h).json()["exceptions"] == 0

    rec = client.get("/reconciliation", headers=h).json()
    assert len(rec["matched"]) == 1 and not rec["open"]
    report = client.get("/report?fy=2025-26", headers=h).json()
    assert any(c["category"] == "rent" for c in report["categories"])
    x = client.get("/export.xlsx?fy=2025-26", headers=h)
    assert x.status_code == 200 and x.content[:2] == b"PK"


def test_zip_duplicate_overlap_and_delete(client):
    h = signup(client)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("statements/hdfc.csv", HDFC_CSV)
        z.writestr("__MACOSX/._hdfc.csv", "junk")
    res = upload(client, h, [("fy.zip", buf.getvalue())], "HDFC Savings")
    assert res["files"][0]["transactions"] == 3
    assert upload(client, h, [("again.csv", HDFC_CSV)], "HDFC Savings")["files"][0]["duplicate"] is True
    # A different file covering an overlapping period only adds the new row.
    overlap = HDFC_CSV.replace("STATEMENT SUMMARY", "06/04/25,NEW ROW,1,06/04/25,99.00,,1.00\nSTATEMENT SUMMARY")
    assert upload(client, h, [("overlap.csv", overlap)], "HDFC Savings")["files"][0]["transactions"] == 1
    docs = client.get("/documents", headers=h).json()
    assert len(docs) == 2
    assert client.delete(f"/documents/{docs[0]['id']}", headers=h).json()["removed"] == 1
    assert client.get("/transactions", headers=h).json()["total"] == 3


def test_bad_files_report_errors(client):
    h = signup(client)
    res = upload(client, h, [("statement.pdf", b"%PDF-1.4"), ("junk.csv", "hello,world\n1,2\n")], "X")
    assert "PDF" in res["files"][0]["error"]
    assert "header" in res["files"][1]["error"]


def test_workspaces_are_isolated(client):
    a = signup(client, "a@example.com")
    b = signup(client, "b@example.com")
    upload(client, a, [("bank.csv", BANK)], "A bank")
    # Same file in another workspace is not treated as a duplicate and stays private.
    assert upload(client, b, [("bank.csv", BANK)], "B bank")["files"][0]["transactions"] == 2
    tx_a = client.get("/transactions", headers=a).json()["items"]
    assert all(t["account"] == "A bank" for t in tx_a)
    assert client.patch(f"/transactions/{tx_a[0]['id']}", headers=b, json={"note": "x"}).status_code == 404
    doc_a = client.get("/documents", headers=a).json()[0]["id"]
    assert client.delete(f"/documents/{doc_a}", headers=b).status_code == 404
    for path in ["/transactions", "/reconciliation", "/report", "/dashboard", "/documents", "/export.xlsx"]:
        assert client.get(path).status_code == 401


def test_registration_closes_after_first_user(client, monkeypatch):
    from app import main
    monkeypatch.setattr(main, "ALLOW_REGISTRATION", False)
    assert client.get("/auth/config").json()["registration_open"] is True
    signup(client)
    assert client.get("/auth/config").json()["registration_open"] is False
    r = client.post("/auth/register", json={"email": "intruder@example.com", "password": "correct-horse-battery", "full_name": "Nope"})
    assert r.status_code == 403


def test_login_rate_limit(client):
    signup(client, "rl@example.com")
    for _ in range(10):
        assert client.post("/auth/login", json={"email": "rl@example.com", "password": "wrong-password"}).status_code == 401
    assert client.post("/auth/login", json={"email": "rl@example.com", "password": "correct-horse-battery"}).status_code == 429


DIVIDENDS = """date,narration,debit,credit
2025-06-21,ACH C- LARSEN AND TOUBRO LI-25213838,,34
2025-07-28,ACH C- HCL 2ND INTDIV25 26-601092,,24
2025-08-01,NEFT CR-GOATLIFE FARMS,,500
2025-08-02,NEFT CR-GOATLIFE FARMS REF 2,,700
2025-09-01,POS 416021XXXXXX9685 GOATLIFE,300,
"""


def test_dividends_and_learning_from_corrections(client):
    h = signup(client)
    upload(client, h, [("idfc.csv", DIVIDENDS)], "IDFC Savings")
    items = client.get("/transactions", headers=h).json()["items"]
    by = {t["narration"]: t for t in items}
    assert by["ACH C- LARSEN AND TOUBRO LI-25213838"]["category"] == "dividend"
    assert by["ACH C- HCL 2ND INTDIV25 26-601092"]["category"] == "dividend"
    first = by["NEFT CR-GOATLIFE FARMS"]
    r = client.patch(f"/transactions/{first['id']}", headers=h, json={"category": "business_receipt"}).json()
    assert r["similar"] == {"key": "goatlife farms", "count": 1, "field": "category", "value": "business_receipt"}  # debit-side POS row isn't "similar"
    r = client.patch(f"/transactions/{first['id']}", headers=h, json={"category": "business_receipt", "apply_similar": True}).json()
    assert r["applied"] == 1
    # Remembered for the next upload.
    upload(client, h, [("idfc2.csv", "date,narration,debit,credit\n2025-10-01,NEFT CR-GOATLIFE FARMS X,,900\n")], "IDFC Savings")
    newest = client.get("/transactions?limit=1", headers=h).json()["items"][0]
    assert newest["category"] == "business_receipt" and newest["status"] == "ok"


def test_rules_upgrade_keeps_user_choices(client, db):
    from app.models import AppMeta, Transaction
    from app import migrate
    h = signup(client)
    upload(client, h, [("idfc.csv", DIVIDENDS)], "IDFC Savings")
    rows = db.query(Transaction).order_by(Transaction.id).all()
    rows[0].category = "uncategorized"          # as an old rule set would have left it
    rows[1].category, rows[1].category_source = "rent", "user"  # the user's explicit choice
    db.get(AppMeta, "rules_version").value = "0"
    db.commit()
    migrate.reclassify_if_rules_changed()
    db.expire_all()
    assert db.get(Transaction, rows[0].id).category == "dividend"
    assert db.get(Transaction, rows[1].id).category == "rent"


def test_review_and_confirm_after_upload(client):
    h = signup(client)
    res = upload(client, h, [("idfc.csv", DIVIDENDS)], "IDFC Savings")
    doc = res["files"][0]["document_id"]
    review = client.get(f"/imports/review?docs={doc}", headers=h).json()
    assert review["statements"][0]["account"] == "IDFC Savings" and review["statements"][0]["transactions"] == 5
    groups = review["groups"]
    assert groups[0]["needs_review"] is True  # undecided groups come first
    goat_in = next(g for g in groups if g["key"] == "goatlife farms")
    assert goat_in["count"] == 2 and goat_in["direction"] == "in"
    payload = [{"tx_ids": g["tx_ids"], "category": "business_receipt" if g is goat_in else g["category"],
                "remember_key": g["key"] if g is goat_in else None} for g in groups]
    r = client.post("/imports/confirm", headers=h, json={"groups": payload}).json()
    assert r["updated"] == 5 and r["remembered"] == 1
    assert client.get("/dashboard", headers=h).json()["exceptions"] == 0
    # Rename and re-type the detected account.
    acc = review["statements"][0]["account_id"]
    assert client.patch(f"/accounts/{acc}", headers=h, json={"name": "IDFC FIRST Savings", "kind": "bank"}).json()["name"] == "IDFC FIRST Savings"
    other = signup(client, "other@example.com")
    assert client.get(f"/imports/review?docs={doc}", headers=other).json() == {"statements": [], "groups": []}
    assert client.patch(f"/accounts/{acc}", headers=other, json={"name": "x"}).status_code == 404


def test_report_per_account(client):
    from openpyxl import load_workbook
    h = signup(client)
    upload(client, h, [("bank.csv", BANK)], "HDFC Savings")
    upload(client, h, [("card.csv", CARD)], "HDFC Regalia", "card")
    full = client.get("/report", headers=h).json()
    accounts = {a["account"]: a for a in full["accounts"]}
    assert accounts["HDFC Savings"]["outflow"] == "500.00" and accounts["HDFC Savings"]["neutral"] == "35000.00"
    assert accounts["HDFC Regalia"]["outflow"] == "1200.00" and accounts["HDFC Regalia"]["kind"] == "card"
    assert full["totals"]["outflow"] == "1700.00"  # overall report unchanged
    card_id = accounts["HDFC Regalia"]["account_id"]
    one = client.get(f"/report?account_id={card_id}", headers=h).json()
    assert one["totals"]["outflow"] == "1200.00" and {c["category"] for c in one["categories"]} == {"dining", "card_settlement"}
    wb = load_workbook(io.BytesIO(client.get("/export.xlsx", headers=h).content))
    assert wb.sheetnames == ["Summary", "Books", "By account", "Credit cards", "Flags", "Transactions"]
    x = client.get(f"/export.xlsx?account_id={card_id}", headers=h)
    assert "HDFC-Regalia" in x.headers["content-disposition"]
    assert load_workbook(io.BytesIO(x.content))["Transactions"].max_row == 3  # header + 2 card rows
    other = signup(client, "other2@example.com")
    assert client.get(f"/report?account_id={card_id}", headers=other).json()["totals"]["outflow"] == "0"


def test_same_statement_in_another_format_is_not_double_counted(client):
    from openpyxl import Workbook
    h = signup(client)
    csv = "date,narration,debit,credit\n2025-04-01,SALARY APR ACME,,85000\n2025-04-03,UPI-SWIGGY-swiggy@icici,450,\n2025-04-08,ATM CASH WDL,5000,\n2025-04-09,NEW ROW ONLY IN XLSX,,0\n"
    upload(client, h, [("statement.csv", csv)], "")  # auto-named from the file: "statement"
    wb = Workbook(); ws = wb.active
    ws.append(["HDFC BANK Ltd. Statement of account"]); ws.append([])
    ws.append(["Date", "Narration", "Withdrawal Amt.", "Deposit Amt.", "Closing Balance"])
    ws.append(["01/04/25", "SALARY APR ACME PVT LTD", None, 85000, 185000])   # narration differs slightly
    ws.append(["03/04/25", "UPI-SWIGGY-swiggy@icici-SWIGGY", 450, None, 184550])
    ws.append(["08/04/25", "ATM CASH WDL", 5000, None, 179550])
    ws.append(["10/04/25", "LIC OF INDIA PREMIUM", 2000, None, 177550])      # genuinely new
    buf = io.BytesIO(); wb.save(buf)
    res = upload(client, h, [("HDFC_Apr.xlsx", buf.getvalue())], "")["files"][0]
    assert res["account"] == "statement" and res["transactions"] == 1
    assert any("already imported" in w for w in res["warnings"])
    assert client.get("/transactions", headers=h).json()["total"] == 4
    assert len(client.get("/accounts", headers=h).json()) == 1
    # Same file name, different month: not a duplicate.
    may = csv.replace("2025-04", "2025-05")
    assert upload(client, h, [("statement.csv", may)], "")["files"][0]["transactions"] == 3


MIXED = """date,narration,debit,credit
2025-04-02,AMAZON WEB SERVICES AWS,4200,
2025-04-03,SWIGGY BANGALORE,600,
2025-04-04,RAZORPAY SETTLEMENT CLIENT ABC,,50000
2025-04-05,INDIAN OIL PETROL PUMP,2000,
2025-04-06,CREDIT CARD PAYMENT,10000,
2025-04-07,UPI-RAHUL-rahul@okaxis,1500,
2025-04-08,UPI-RAHUL-rahul@okaxis,700,
"""


def test_business_personal_split_and_report(client):
    from openpyxl import load_workbook
    h = signup(client)
    assert client.get("/settings", headers=h).json() == {"business_mode": False}
    assert client.patch("/settings", headers=h, json={"business_mode": True}).json()["business_mode"] is True
    upload(client, h, [("mixed.csv", MIXED)], "HDFC Savings")
    by = {t["narration"]: t for t in client.get("/transactions", headers=h).json()["items"]}
    assert by["AMAZON WEB SERVICES AWS"]["category"] == "software" and by["AMAZON WEB SERVICES AWS"]["purpose"] == "business"
    assert by["RAZORPAY SETTLEMENT CLIENT ABC"]["purpose"] == "business"
    assert by["SWIGGY BANGALORE"]["purpose"] == "personal"
    assert by["INDIAN OIL PETROL PUMP"]["purpose"] == "unknown"        # ambiguous: left for the user
    assert by["CREDIT CARD PAYMENT"]["purpose"] == "neutral"

    # Teach one UPI payee as business, applied to the similar row too.
    rahul = by["UPI-RAHUL-rahul@okaxis"]
    r = client.patch(f"/transactions/{rahul['id']}", headers=h, json={"purpose": "business"}).json()
    assert r["similar"]["field"] == "purpose" and r["similar"]["count"] == 1
    r = client.patch(f"/transactions/{rahul['id']}", headers=h, json={"purpose": "business", "apply_similar": True}).json()
    assert r["applied"] == 1

    rep = client.get("/report?purpose=business", headers=h).json()
    assert rep["totals"]["outflow"] == "6400.00" and rep["totals"]["inflow"] == "50000.00"   # AWS 4200 + Rahul 2200
    assert any("no business/personal purpose" in f["title"] for f in rep["flags"])          # petrol left out, and said so
    assert rep["purpose_split"]["unknown"]["count"] == 1
    assert client.get("/transactions?purpose=unknown", headers=h).json()["total"] == 1

    # A business account makes everything business except clearly personal items.
    acc = client.get("/accounts", headers=h).json()[0]
    assert acc["purpose"] == "mixed"
    client.patch(f"/accounts/{acc['id']}", headers=h, json={"purpose": "business"})
    by = {t["narration"]: t for t in client.get("/transactions", headers=h).json()["items"]}
    assert by["INDIAN OIL PETROL PUMP"]["purpose"] == "business" and by["SWIGGY BANGALORE"]["purpose"] == "business"
    client.patch(f"/accounts/{acc['id']}", headers=h, json={"purpose": "personal"})
    by = {t["narration"]: t for t in client.get("/transactions", headers=h).json()["items"]}
    assert by["AMAZON WEB SERVICES AWS"]["purpose"] == "business"     # business by nature, even on a personal account
    assert by["SWIGGY BANGALORE"]["purpose"] == "personal"
    assert by["UPI-RAHUL-rahul@okaxis"]["purpose"] == "business"      # the user's choice survives

    x = client.get("/export.xlsx?purpose=business", headers=h)
    assert "business-working-paper" in x.headers["content-disposition"]
    wb = load_workbook(io.BytesIO(x.content))
    assert wb["Summary"]["A1"].value.startswith("LedgerVault Business working paper")
    tx = wb["Transactions"]
    assert tx.cell(row=1, column=15).value == "Purpose" and {tx.cell(row=r, column=15).value for r in range(2, tx.max_row + 1)} == {"business"}
    # A card bill payment has no purpose to set.
    assert client.patch(f"/transactions/{by['CREDIT CARD PAYMENT']['id']}", headers=h, json={"purpose": "business"}).status_code == 400


def test_credit_card_reconciliation(client):
    from openpyxl import load_workbook
    h = signup(client)
    bank = ("date,narration,debit,credit\n2025-04-10,CREDIT CARD PAYMENT HDFC,35000,\n"
            "2025-04-20,CC PAYMENT AXIS 4455,8000,\n2025-04-21,SWIGGY,300,\n")
    card = ("date,narration,debit,credit\n2025-04-03,AMAZON,20000,\n2025-04-05,ZOMATO,1500,\n2025-04-06,AMAZON REFUND,,2000\n"
            "2025-04-11,PAYMENT RECEIVED THANK YOU,,35000\n2025-04-25,CASH PAYMENT RECEIVED,,5000\n")
    upload(client, h, [("bank.csv", bank)], "HDFC Savings")
    upload(client, h, [("card.csv", card)], "HDFC Regalia", "card")
    rep = client.get("/report", headers=h).json()
    cr = rep["cards"]
    c = cr["cards"][0]
    assert (c["purchases"], c["refunds"], c["payments"], c["matched"], c["unmatched"], c["cash_payments"]) == \
        ("21500.00", "2000.00", "40000.00", "35000.00", "5000.00", "5000.00")
    assert c["matched_count"] == 1 and c["unmatched_count"] == 1
    assert cr["unmatched_bank_total"] == "8000.00" and cr["unmatched_bank_payments"][0]["narration"] == "CC PAYMENT AXIS 4455"
    assert cr["total_paid"] == "48000.00"   # 40,000 received on the card + 8,000 paid to a card not uploaded; the matched 35,000 counted once
    assert rep["totals"]["outflow"] == "19800.00"  # purchases 21,500 + swiggy 300 - refund 2,000; payments never counted
    dash = client.get("/dashboard", headers=h).json()
    assert dash["card_payments"] == "48000.00" and dash["card_matched"] == 1 and dash["card_payment_count"] == 3
    wb = load_workbook(io.BytesIO(client.get("/export.xlsx", headers=h).content))
    assert "Credit cards" in wb.sheetnames
    cells = [str(v) for row in wb["Credit cards"].iter_rows(values_only=True) for v in row if v is not None]
    assert "CC PAYMENT AXIS 4455" in cells and 48000.0 in [v for row in wb["Credit cards"].iter_rows(values_only=True) for v in row]


def test_missing_card_statements_are_named(client):
    h = signup(client)
    bank = ("date,narration,debit,credit\n"
            "2025-04-10,CC 0000XXXXXXXX9876 AUTOPAY SI-TAD,35000,\n"      # matched to the uploaded April statement
            "2025-06-10,CC 0000XXXXXXXX9876 AUTOPAY SI-TAD,12000,\n"      # same card, June statement not uploaded
            "2025-04-20,CC PAYMENT AXIS 4455,8000,\n"                      # Axis card never uploaded
            "2025-05-20,CC PAYMENT AXIS 4455,6000,\n"
            "2025-05-02,POS 416021XXXXXX9685 DREAMPLUG PAYTEC,51000,\n")  # paid through CRED with the debit card
    card = ("date,narration,debit,credit\n2025-04-03,AMAZON,20000,\n2025-04-11,PAYMENT RECEIVED THANK YOU,,35000\n")
    upload(client, h, [("bank.csv", bank)], "HDFC Savings")
    upload(client, h, [("card.csv", card)], "HDFC Regalia ••9876", "card")
    missing = client.get("/report", headers=h).json()["cards"]["missing_statements"]
    by = {g["card"]: g for g in missing}
    assert by["Axis Bank card ••4455"]["status"] == "not_uploaded" and by["Axis Bank card ••4455"]["months"] == ["Apr 2025", "May 2025"]
    assert by["Axis Bank card ••4455"]["amount"] == "14000.00" and by["Axis Bank card ••4455"]["count"] == 2
    assert by["HDFC Regalia ••9876"]["status"] == "period_missing" and by["HDFC Regalia ••9876"]["months"] == ["Jun 2025"]
    assert by["Card not identified (paid via CRED)"]["amount"] == "51000.00"
    titles = [f["title"] for f in client.get("/dashboard", headers=h).json()["flags"]]
    assert "Axis Bank card ••4455: statement not uploaded" in titles
    assert "HDFC Regalia ••9876: statement missing for Jun 2025" in titles


def test_cred_payments_are_not_pinned_on_the_axis_card(client):
    h = signup(client)
    bank = ("date,narration,debit,credit\n"
            "2025-05-05,UPI/DR/51234/CRED/cred.club@axisb/Payment,20000,\n"
            "2025-06-05,UPI/DR/51299/CRED/cred.club@axisb/Payment,25000,\n"
            "2025-07-05,UPI/DR/51300/CRED/cred.club@axisb/Payment,30000,\n"
            "2025-04-10,CC PAYMENT AXIS 9534,5000,\n")
    card = "date,narration,debit,credit\n2025-04-02,AMAZON,5000,\n2025-04-11,PAYMENT RECEIVED THANK YOU,,5000\n"
    upload(client, h, [("bank.csv", bank)], "HDFC Savings")
    upload(client, h, [("axis.csv", card)], "Axis Bank Credit Card ••9534", "card")
    groups = client.get("/report", headers=h).json()["cards"]["missing_statements"]
    assert not any(g["card"] == "Axis Bank Credit Card ••9534" for g in groups)   # its only payment matched the uploaded statement
    cred = [g for g in groups if g["card"] == "Card not identified (paid via CRED)"]
    # One group per month, each naming the uploaded card that has no statement covering that payment.
    assert [(g["status"], g["months"], g["count"]) for g in cred] == [
        ("not_identified", ["May 2025"], 1), ("not_identified", ["Jun 2025"], 1), ("not_identified", ["Jul 2025"], 1)]
    assert sum(float(g["amount"]) for g in cred) == 75000
    assert all("Axis Bank Credit Card ••9534" in g["message"] for g in cred)


def test_report_checklist_and_heads(client):
    h = signup(client)
    bank = ("date,narration,debit,credit\n2025-04-01,SALARY APR ACME,,150000\n2025-04-05,UPI-RAMESH-ramesh@okaxis,25000,\n"
            "2025-04-10,CREDIT CARD PAYMENT,35000,\n2025-04-15,LIC OF INDIA PREMIUM,24000,\n2025-04-20,NEFT CR-UNKNOWN PARTY,,250000\n"
            "2025-06-01,SALARY JUN ACME,,150000\n")   # May statement missing between April and June
    upload(client, h, [("bank.csv", bank)], "HDFC Savings")
    rep = client.get("/report", headers=h).json()
    check = {c["key"]: c for c in rep["checklist"]}
    assert not check["statements"]["done"] and "month(s) missing" in check["statements"]["detail"]
    assert check["categories"]["count"] == 2 and check["categories"]["action"]["filter"] == "needs_review"
    assert check["matching"]["count"] == 1          # card bill with no card statement
    assert check["large_credits"]["count"] == 1
    heads = {x["key"]: x for x in rep["heads"]}
    assert heads["income"]["lines"][0] == {"category": "salary", "label": "Salary (take-home credits)", "hint": "Use gross salary and TDS from Form 16", "amount": "300000.00", "count": 2}
    assert heads["deductions"]["lines"][0]["category"] == "insurance" and heads["deductions"]["total"] == "24000.00"
    # Explaining the large credit with a category clears that item.
    big = next(t for t in client.get("/transactions", headers=h).json()["items"] if t["credit"] == "250000.00")
    client.patch(f"/transactions/{big['id']}", headers=h, json={"category": "business_receipt"})
    check = {c["key"]: c for c in client.get("/report", headers=h).json()["checklist"]}
    assert check["large_credits"]["done"] and check["categories"]["count"] == 1
