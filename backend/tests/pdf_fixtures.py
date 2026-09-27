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


def icici_card_statement() -> bytes:
    """Shaped like the masked ICICI output: ruled transaction table with a ` rupee header, an EMI
    summary table below it, and the transaction table continuing on page 2 without a header."""
    from reportlab.platypus import PageBreak
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4)
    style = TableStyle([("GRID", (0, 0), (-1, -1), 0.5, colors.black), ("FONTSIZE", (0, 0), (-1, -1), 7)])
    head = ["Date", "Ser. No.", "Transaction Details", "Reward\nPoints", "Intl.#\namount", "Amount (in`)"]
    page1 = [head,
             ["05/09/2025", "11223344556", "BBPS Payment received", "0", "", "12,000.00 CR"],
             ["07/09/2025", "11223344557", "AMAZON PAY INDIA BANGALORE IN", "40", "", "2,499.00"],
             ["09/09/2025", "11223344558", "SWIGGY BANGALORE IN", "6", "", "640.50"]]
    page2 = [["12/09/2025", "11223344559", "IRCTC NEW DELHI IN", "20", "", "1,845.00"],
             ["15/09/2025", "11223344560", "REFUND FLIPKART", "0", "", "499.00 CR"]]
    emi = [["SL. No", "Transaction", "₹"], ["1", "Purchase on Sep 12, 2025", "9,999"], ["2", "Total Amount Due on statement dated Oct 01, 2025", "4,322"]]
    p = getSampleStyleSheet()["Normal"]
    t1, t2, t3 = Table(page1), Table(page2), Table(emi)
    for t in (t1, t2, t3):
        t.setStyle(style)
    doc.build([Paragraph("ICICI Bank Credit Card Statement - Card 4854XXXXXXXXXX45 - Minimum Amount due - Credit Limit", p), t1,
               PageBreak(), t2, Paragraph("EMI summary", p), t3])
    return buf.getvalue()


def hdfc_new_card_statement() -> bytes:
    """Newer HDFC-style text layout: date | time, rupee sign, '+' for credits, 'C' suffix, no ruling."""
    return _text_pdf([
        "HDFC Bank Credit Card Statement   Card No: 6529 XXXX XXXX 1047",
        "Total Amount Due  Minimum Amount Due  Credit Limit  Payment Due Date",
        "DATE & TIME          TRANSACTION DESCRIPTION              REWARDS     AMOUNT",
        "02/10/2025| 13:45    ZOMATO GURGAON                        + 12      Rs. 1,240.00",
        "05/10/2025| 09:10    NETFLIX.COM MUMBAI                    + 6       Rs. 649.00",
        "08/10/2025| 18:22    PAYMENT RECEIVED - NETBANKING                   + Rs. 25,000.00",
        "11/10/2025| 20:01    UBER INDIA SYSTEMS BANGALORE          + 3       Rs. 312.40",
        "14/10/2025| 11:11    REVERSAL ZOMATO                                 Rs. 240.00 C",
    ])
