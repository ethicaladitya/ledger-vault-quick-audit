import io
from datetime import date, datetime
from decimal import Decimal
from openpyxl import Workbook
from app.services.ingestion import parse_statement, dec, parse_date, financial_year
from app.services.rules import classify

HDFC_CSV = """HDFC BANK Ltd.,,,,,,
Account No :,XXXXXXXX1234,,,,,
Statement From : 01/04/2025 To : 31/03/2026,,,,,,
,,,,,,
Date,Narration,Chq./Ref.No.,Value Dt,Withdrawal Amt.,Deposit Amt.,Closing Balance
********,********,********,********,********,********,********
01/04/25,SALARY APR 2025 ACME PVT LTD,0000123,01/04/25,,"85,000.00","1,20,000.00"
03/04/25,UPI-SWIGGY-swiggy@icici-SWIGGY,0000124,03/04/25,450.00,,"1,19,550.00"
05/04/25,CC 0000XXXXXXXX9876 AUTOPAY SI-TAD,0000125,05/04/25,"12,340.00",,"1,07,210.00"
,,,,,,
STATEMENT SUMMARY :-,,,,,,
Opening Balance,Dr Count,Cr Count,Debits,Credits,Closing Bal,
"35,000.00",2,1,"12,790.00","85,000.00","1,07,210.00",
"""

KOTAK_CSV = """Sl. No.,Transaction Date,Description,Chq / Ref No.,Amount,Dr / Cr,Balance
1,02-04-2025,IMPS/P2A/SELF TRANSFER,123,"10,000.00",DR,"50,000.00"
2,07-04-2025,Int.Pd:01-01-2025 to 31-03-2025,,"1,234.00",CR,"51,234.00"
3,10-04-2025,"NEFT CR-RAMESH",,"2,50,000.00",CR,"3,01,234.00"
"""


def test_hdfc_style_csv_with_preamble_and_footer():
    rows, warnings = parse_statement("hdfc.csv", HDFC_CSV.encode(), "bank")
    assert [r["date"] for r in rows] == [date(2025, 4, 1), date(2025, 4, 3), date(2025, 4, 5)]
    assert rows[0]["credit"] == Decimal("85000.00") and rows[0]["balance"] == Decimal("120000.00")
    assert rows[2]["debit"] == Decimal("12340.00")
    assert any("Skipped" in w for w in warnings)


def test_amount_with_dr_cr_column():
    rows, _ = parse_statement("kotak.csv", KOTAK_CSV.encode(), "bank")
    assert rows[0]["debit"] == Decimal("10000.00") and rows[0]["credit"] == 0
    assert rows[1]["credit"] == Decimal("1234.00")
    assert rows[2]["credit"] == Decimal("250000.00")


def test_icici_style_xlsx_with_multiline_narration():
    wb = Workbook(); ws = wb.active
    ws.append(["DETAILED STATEMENT"]); ws.append([])
    ws.append(["S No.", "Value Date", "Transaction Date", "Cheque Number", "Transaction Remarks", "Withdrawal Amount (INR )", "Deposit Amount (INR )", "Balance (INR )"])
    ws.append([1, datetime(2025, 5, 2), datetime(2025, 5, 1), None, "UPI/5123/AMAZON PAY", 1999.0, 0, 5000.0])
    ws.append([None, None, None, None, "/Payment from Ph", None, None, None])
    ws.append([2, "04/05/2025", "04/05/2025", None, "ATM CASH WDL", 2000, None, 3000])
    buf = io.BytesIO(); wb.save(buf)
    rows, _ = parse_statement("icici.xlsx", buf.getvalue(), "bank")
    assert rows[0]["date"] == date(2025, 5, 1)  # transaction date preferred over value date
    assert rows[0]["narration"] == "UPI/5123/AMAZON PAY /Payment from Ph"
    assert rows[1]["debit"] == Decimal("2000.00")


def test_card_amount_suffix():
    csv = "Date,Transaction Details,Amount (in Rs.)\n12/04/2025,ZOMATO BANGALORE,\"1,250.00 Dr\"\n15/04/2025,PAYMENT RECEIVED - THANK YOU,\"20,000.00 Cr\"\n"
    rows, _ = parse_statement("card.csv", csv.encode(), "card")
    assert rows[0]["debit"] == Decimal("1250.00")
    assert rows[1]["credit"] == Decimal("20000.00")


def test_helpers():
    assert dec("1,23,456.78") == Decimal("123456.78")
    assert dec("(500)") == Decimal("-500.00")
    assert parse_date("15-Apr-2025") == date(2025, 4, 15)
    assert parse_date("15/04/2025 10:22:01") == date(2025, 4, 15)
    assert parse_date("********") is None
    assert financial_year(date(2025, 3, 31)) == "2024-25"
    assert financial_year(date(2025, 4, 1)) == "2025-26"


def test_rules():
    assert classify("UPI-RAMESH KUMAR-ramesh@okaxis", True) == "upi_transfer"
    assert classify("UPI-SWIGGY-swiggy@icici", True) == "dining"
    assert classify("SALARY APR 2025", False) == "salary"
    assert classify("SALARY APR 2025", True) != "salary"
    assert classify("CC 0000XXXX9876 AUTOPAY SI-TAD", True) == "card_settlement"
    assert classify("PAYMENT RECEIVED - THANK YOU", False, "card") == "card_settlement"
    assert classify("Int.Pd:01-01-2025 to 31-03-2025", False) == "interest_income"
    assert classify("LIC OF INDIA PREMIUM", True) == "insurance"
    assert classify("IMPS/P2A/SELF TRANSFER", True) == "own_transfer"
