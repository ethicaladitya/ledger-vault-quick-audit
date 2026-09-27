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
