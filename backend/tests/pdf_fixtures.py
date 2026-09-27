"""Synthetic statement PDFs shaped like Indian bank/card e-statements (no real data)."""
import io
import pikepdf
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph
from reportlab.lib.styles import getSampleStyleSheet


def _text_pdf(lines: list[str]) -> bytes:
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    y = 800
    for line in lines:
        if y < 60:
            c.showPage(); y = 800
        c.setFont("Helvetica", 9)
        c.drawString(40, y, line)
        y -= 14
    c.save()
    return buf.getvalue()


def card_statement() -> bytes:
    return _text_pdf([
        "HDFC Bank Credit Card Statement",
        "Name : PRIYA SHARMA     Card No : 4386 XXXX XXXX 9876",
        "Statement Date 20/04/2025   Payment Due Date 10/05/2025",
        "Total Amount Due 3,639.00   Minimum Amount Due 200.00   Credit Limit 2,00,000.00",
        "Domestic Transactions",
        "Date Transaction Description Reward Points Amount (in Rs.)",
        "02/04/2025 AMAZON PAY INDIA PRIVATE LIMITED 30 2,999.00",
        "BANGALORE",
        "04/04/2025 ZOMATO BANGALORE 6 640.00",
        "06/04/2025 PAYMENT RECEIVED - THANK YOU 12,340.00 Cr",
        "Page 1 of 1",
    ])


def bank_statement() -> bytes:
    return _text_pdf([
        "State Bank of India",
        "Account Statement from 1 Apr 2025 to 30 Apr 2025",
        "Account Name : Ms. PRIYA SHARMA   Account No : XXXXXXX4521   IFSC : SBIN0001234",
        "Txn Date Value Date Description Ref No Debit Credit Balance",
        "Opening Balance 50,000.00",
        "01 Apr 2025 01 Apr 2025 BY TRANSFER-NEFT ACME PVT LTD SALARY 85,000.00 1,35,000.00",
        "05 Apr 2025 05 Apr 2025 TO TRANSFER-HDFC CC PAYMENT 12,340.00 1,22,660.00",
        "07 Apr 2025 07 Apr 2025 ATM WDL SBI ATM ANDHERI 5,000.00 1,17,660.00",
        "15 Apr 2025 15 Apr 2025 BY TRANSFER-UPI REFUND FLIPKART 1,499.00 1,19,159.00",
        "Closing Balance 1,19,159.00",
    ])


def table_statement() -> bytes:
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4)
    data = [["S No.", "Transaction Date", "Transaction Remarks", "Withdrawal Amount (INR )", "Deposit Amount (INR )", "Balance (INR )"],
            ["1", "03/05/2025", "UPI/SWIGGY/Payment", "450.00", "", "9,550.00"],
            ["2", "10/05/2025", "LIC OF INDIA PREMIUM", "2,000.00", "", "7,550.00"],
            ["3", "31/05/2025", "INT PD 01-03-25 TO 31-05-25", "", "120.00", "7,670.00"]]
    t = Table(data)
    t.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.5, colors.black), ("FONTSIZE", (0, 0), (-1, -1), 7)]))
    doc.build([Paragraph("ICICI Bank - Detailed Statement - Account Number XXXXXXXX7788", getSampleStyleSheet()["Normal"]), t])
    return buf.getvalue()


def encrypt(data: bytes, password: str) -> bytes:
    out = io.BytesIO()
    with pikepdf.open(io.BytesIO(data)) as pdf:
        pdf.save(out, encryption=pikepdf.Encryption(user=password, owner=password + "-owner", R=6))
    return out.getvalue()
