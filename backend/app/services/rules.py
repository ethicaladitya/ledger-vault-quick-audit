"""Deterministic narration rules for Indian bank and card statements.

Rules are ordered: the first match wins. Each rule applies to debits, credits or
both. Categories carry a group and an ITR hint for the CA working paper; hints
are prompts for review, never a tax determination.
"""
import re

# key: (label, group, itr_hint)
CATEGORIES = {
    "salary": ("Salary", "income", "Income from salary — match with Form 16 / AIS"),
    "interest_income": ("Interest received", "income", "Other sources — savings/FD interest (80TTA/80TTB, old regime)"),
    "dividend": ("Dividend", "income", "Other sources — dividends are taxable; match with AIS"),
    "rental_income": ("Rent received", "income", "House property income"),
    "business_receipt": ("Business / professional receipt", "income", "Business or profession — confirm with CA"),
    "refund_reversal": ("Refund / reversal / cashback", "adjustment", "Usually not income; reduces the related expense"),
    "cash_deposit": ("Cash deposit", "review", "Cash deposits ≥ ₹10 lakh/FY are reported to the IT dept (SFT) — keep source evidence"),
    "tax_payment": ("Income tax / TDS paid", "tax", "Claim as advance / self-assessment tax — match with 26AS challans"),
    "investment": ("Investment (MF, stocks, PPF, NPS, FD)", "investment", "Possible 80C / 80CCD, and capital-gains cost basis"),
    "insurance": ("Insurance premium", "deduction_hint", "Life → possible 80C; health → possible 80D (old regime)"),
    "loan_emi": ("Loan EMI", "deduction_hint", "Home loan: interest 24(b), principal 80C — need lender certificate"),
    "rent": ("Rent paid", "deduction_hint", "Possible HRA / 80GG — keep rent receipts, landlord PAN if > ₹1 lakh/yr"),
    "education": ("Education / tuition fees", "deduction_hint", "Tuition fees for children → possible 80C"),
    "donation": ("Donation", "deduction_hint", "Possible 80G — needs receipt with trust PAN/80G number"),
    "medical": ("Medical / pharmacy", "expense", "Preventive health check-up → possible 80D"),
    "card_settlement": ("Credit card bill payment", "neutral", "Not an expense — the card purchases are counted instead"),
    "own_transfer": ("Transfer between own accounts", "neutral", "Not income or expense"),
    "cash_withdrawal": ("Cash withdrawal (ATM)", "expense", "Cash withdrawals > ₹1 crore/yr attract TDS u/s 194N"),
    "utilities": ("Utilities, phone & internet", "expense", ""),
    "dining": ("Food & dining", "expense", ""),
    "groceries": ("Groceries", "expense", ""),
    "shopping": ("Shopping", "expense", ""),
    "travel": ("Travel & transport", "expense", ""),
    "fuel": ("Fuel", "expense", ""),
    "bank_charges": ("Bank / card charges", "expense", ""),
    "upi_transfer": ("UPI payment / receipt (unidentified)", "review", "Identify the counter-party"),
    "bank_transfer": ("NEFT / IMPS / RTGS (unidentified)", "review", "Identify the counter-party"),
    "uncategorized": ("Uncategorised", "review", "Needs a category"),
}
NEUTRAL = {"card_settlement", "own_transfer"}
REVIEW = {c for c, (_, group, _) in CATEGORIES.items() if group == "review"}

D, C, A = "debit", "credit", "any"
RULES = [
    (r"\b(self|own a/?c|own account|sweep|to fd|from fd|trf to own)\b", "own_transfer", A),
    (r"credit ?card|card ?payment|cc ?payment|cc bill|card bill|\bcc ?[0-9x]{4,}|si-tad|si-mad|\bcred\b|cred club|bbps.*card|autopay.*card|card.*autopay", "card_settlement", D),
    (r"\b(salary|sal cr|sal for|payroll)\b", "salary", C),
    (r"\b(dividend|div)\b", "dividend", C),
    (r"interest|\bint\.? ?(pd|paid|cr|credit)\b|\bsb int\b|\bint on\b", "interest_income", C),
    (r"refund|reversal|reversed|revrsl|cashback|cash back", "refund_reversal", C),
    (r"\brent\b", "rental_income", C),
    (r"cash dep|by cash|cash deposit|\bcdm\b", "cash_deposit", C),
    (r"\btds\b|advance tax|self assessment|income ?tax|oltas|cbdt|challan ?280|tin ?nsdl|e-?pay tax", "tax_payment", D),
    (r"\bsip\b|mutual ?fund|\bmf\b|zerodha|groww|upstox|kuvera|coin by|\bppf\b|\bnps\b|fixed deposit|\bfd\b|\brd\b|bse ltd|nse clearing|indian clearing|\biccl\b|smallcase|paytm money|\bcams\b|kfintech", "investment", D),
    (r"insurance|\blic\b|premium|policy ?bazaar|star health|hdfc ergo|icici lombard|niva bupa|care health", "insurance", D),
    (r"\bemi\b|\bloan\b|bajaj fin|home ?loan|housing fin", "loan_emi", D),
    (r"\brent\b|nobroker|nestaway", "rent", D),
    (r"school|college|university|tuition|academy", "education", D),
    (r"donation|charity|pm ?cares|\bngo\b", "donation", D),
    (r"\batm\b|cash wdl|cash withdrawal|\bnwd\b|\bawb\b|atw", "cash_withdrawal", D),
    (r"pharma|apollo|medplus|hospital|clinic|\b1mg\b|netmeds|diagnostic|health ?care|practo", "medical", D),
    (r"electricity|bescom|msedcl|mseb|tata power|adani (elec|energy)|torrent power|water bill|gas bill|mahanagar gas|indane|broadband|airtel|\bjio\b|vodafone|\bvi\b|bsnl|act fibernet|recharge|\bdth\b|tata ?play", "utilities", D),
    (r"swiggy|zomato|restaurant|\bcafe\b|eatclub|domino|mcdonald|starbucks|\bkfc\b|pizza|burger", "dining", D),
    (r"bigbasket|blinkit|zepto|grofers|dmart|instamart|jiomart|more retail|reliance fresh|nature'?s basket", "groceries", D),
    (r"amazon|flipkart|myntra|ajio|nykaa|meesho|tata ?cliq|croma|reliance digital|decathlon|ikea", "shopping", D),
    (r"\buber\b|\bola\b|rapido|irctc|makemytrip|goibibo|indigo|air ?india|vistara|akasa|cleartrip|redbus|fastag|ixigo|metro", "travel", D),
    (r"fuel|petrol|diesel|iocl|hpcl|bpcl|indian oil|\bshell\b|filling station", "fuel", D),
    (r"charges?|\bchrg|\bfee\b|annual fee|late fee|finance charge|sms alert|\bamc\b|gst on|\bigst\b|\bcgst\b|\bsgst\b|penalty", "bank_charges", D),
    (r"\bupi\b", "upi_transfer", A),
    (r"\b(neft|imps|rtgs|ift|fund transfer|trf)\b", "bank_transfer", A),
]
_COMPILED = [(re.compile(p, re.I), cat, side) for p, cat, side in RULES]
_CARD_PAYMENT_CREDIT = re.compile(r"payment|thank you|received|recd|autopay|bbps|neft|imps|upi", re.I)


def classify(narration: str, is_debit: bool = True, account_kind: str = "bank") -> str:
    # On a card statement, a credit that looks like a payment is the other leg of the bank's bill payment.
    if account_kind == "card" and not is_debit:
        if _CARD_PAYMENT_CREDIT.search(narration) and not re.search(r"refund|reversal|cashback", narration, re.I):
            return "card_settlement"
    side = D if is_debit else C
    for pattern, category, rule_side in _COMPILED:
        if rule_side in (A, side) and pattern.search(narration):
            return category
    return "uncategorized"
