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
    "investment_redemption": ("Investment sale / redemption", "investment", "Capital gains — use the broker/AMC capital-gains statement, not the bank credit"),
    "tax_refund": ("Income-tax refund", "adjustment", "Not income, but interest on the refund (sec 244A) is taxable — see AIS"),
    "refund_reversal": ("Refund / reversal / cashback", "adjustment", "Usually not income; reduces the related expense"),
    "cash_deposit": ("Cash deposit", "review", "Cash deposits ≥ ₹10 lakh/FY are reported to the IT dept (SFT) — keep source evidence"),
    "tax_payment": ("Income tax / TDS paid", "tax", "Claim as advance / self-assessment tax — match with 26AS challans"),
    "gst_payment": ("GST paid", "tax", "GST paid via challan — reconcile with GSTR-3B; not an income-tax deduction by itself"),
    "investment": ("Investment (MF, stocks, PPF, NPS, FD)", "investment", "Possible 80C / 80CCD, and capital-gains cost basis"),
    "insurance": ("Insurance premium", "deduction_hint", "Life → possible 80C; health → possible 80D (old regime)"),
    "loan_emi": ("Loan EMI", "deduction_hint", "Home loan: interest 24(b), principal 80C — need lender certificate"),
    "rent": ("Rent paid", "deduction_hint", "Possible HRA / 80GG — keep rent receipts, landlord PAN if > ₹1 lakh/yr"),
    "education": ("Education / tuition fees", "deduction_hint", "Tuition fees for children → possible 80C"),
    "donation": ("Donation", "deduction_hint", "Possible 80G — needs receipt with trust PAN/80G number"),
    "medical": ("Medical / pharmacy", "expense", "Preventive health check-up → possible 80D"),
    "card_settlement": ("Credit card bill payment", "neutral", "Not an expense — the card purchases are counted instead"),
    "own_transfer": ("Transfer between own accounts", "neutral", "Not income or expense"),
    "cash_withdrawal": ("Cash withdrawal (ATM / UPI cash)", "expense", "Cash withdrawals > ₹1 crore/yr attract TDS u/s 194N"),
    "utilities": ("Utilities, phone & internet", "expense", ""),
    "dining": ("Food & dining", "expense", ""),
    "groceries": ("Groceries", "expense", ""),
    "shopping": ("Shopping", "expense", ""),
    "travel": ("Travel & transport", "expense", ""),
    "fuel": ("Fuel", "expense", ""),
    "entertainment": ("Entertainment & subscriptions", "expense", ""),
    "bank_charges": ("Bank / card charges", "expense", ""),
    "card_purchase": ("Card purchase (other merchant)", "expense", ""),
    "software": ("Software & cloud services", "expense", "Business expense if used for work — keep invoices (GST input credit if registered)"),
    "advertising": ("Advertising & marketing", "expense", "Business expense — keep ad invoices"),
    "professional_services": ("Professional & contractor fees", "expense", "Business expense — TDS u/s 194J may apply above thresholds"),
    "office": ("Office, coworking & stationery", "expense", "Business expense — keep invoices"),
    "courier": ("Courier & logistics", "expense", "Business expense — keep invoices"),
    "bill_payment": ("Bill payment via BBPS / BillPay", "review", "Often a credit-card bill — pick 'Credit card bill payment' if so, otherwise Utilities"),
    "auto_debit": ("Auto-debit (NACH / ECS / standing instruction)", "review", "Usually an EMI, SIP or insurance premium — pick the right one"),
    "upi_transfer": ("UPI payment / receipt (unidentified)", "review", "Identify the counter-party"),
    "bank_transfer": ("NEFT / IMPS / RTGS (unidentified)", "review", "Identify the counter-party"),
    "uncategorized": ("Uncategorised", "review", "Needs a category"),
}
NEUTRAL = {"card_settlement", "own_transfer"}
REVIEW = {c for c, (_, group, _) in CATEGORIES.items() if group == "review"}

D, C, A = "debit", "credit", "any"
# Bump when rules change: rows categorised by rules (not by the user) are re-classified on start-up.
RULES_VERSION = 4

# Narration codes: HDFC ATW (own ATM) / NWD, EAW (other ATM), ICICI VPS/IPS (debit card), BIL (bill pay),
# INF (linked-account transfer), MMT (IMPS), EBA (ICICI Direct), NFS (shared ATM network), ICCW (UPI cash
# withdrawal), ACH/NACH/ECS (mandated credits and debits; "ACH C-" credits from companies are dividends),
# Dreamplug Paytech = CRED.
DIV = r"(?<![a-z])(?:fnl|final|fin|int|interim|spl|special|\d{4})?\s*div(?:idend)?(?![a-z])"
RULES = [
    (r"\b(self|own a/?c|own account|sweep|to fd|from fd|trf to own)\b|^inf/", "own_transfer", A),
    (r"credit ?card|card ?payment|cc ?payment|cc bill|card bill|\bcc ?[0-9x]{4,}|si-tad|si-mad|\bcred\b|cred club|dreamplug|ccbbps|cc ?bbps|bbps.*(card|\bcc\b)|autopay.*card|card.*autopay", "card_settlement", D),
    (r"\b(salary|sal cr|sal for|payroll)\b", "salary", C),
    (r"tax ?ref|it ?refund|refund.*income ?tax|income ?tax.*refund|itdtax|cbdt|\btin ?ref", "tax_refund", C),
    (r"refund|reversal|reversed|revrsl|\brvsl\b|cashback|cash back|cancel|upiret|iccw ref|\brev\b|\brtn\b|return", "refund_reversal", C),
    (r"mutual ?fund|\bmf\b|redemption|redeem|zerodha|groww|upstox|kuvera|\bcams\b|kfintech|nse clearing|indian clearing|\biccl\b|bse ltd", "investment_redemption", C),
    (DIV, "dividend", C),
    (r"interest|\bint\.? ?(pd|paid|cr|credit)\b|\bsb int\b|\bint on\b", "interest_income", C),
    (r"^ach c\b|\bach c-|\bach cr\b|\bnach cr\b|\becs cr\b|\bnach c\b", "dividend", C),
    (r"razorpay|cashfree|\bpayu\b|stripe|paypal|instamojo|ccavenue|settlement|upwork|fiverr|invoice|\binv ?no\b|gst ?refund", "business_receipt", C),
    (r"\brent\b", "rental_income", C),
    (r"cash dep|by cash|cash deposit|\bcdm\b", "cash_deposit", C),
    (r"\bgst\b.*(challan|pmt|payment|cpin)|gst ?challan|\bcpin\b|\bgstn\b|gst portal", "gst_payment", D),
    (r"\btds\b|advance tax|self assessment|income ?tax|oltas|cbdt|challan ?280|tin ?nsdl|e-?pay tax", "tax_payment", D),
    (r"\baws\b|amazon web services|google ?cloud|gsuite|g suite|google ?workspace|microsoft|msft|azure|office ?365|adobe|zoho|tally|github|gitlab|atlassian|\bjira\b|notion|figma|canva|slack|\bzoom\b|openai|chatgpt|anthropic|claude\.ai|digitalocean|linode|vercel|netlify|heroku|cloudflare|godaddy|hostinger|namecheap|bigrock|freshworks|hubspot|mailchimp|dropbox|1password", "software", D),
    (r"facebk|facebook ?ads|fb ?ads|meta ?(ads|platforms)|google ?ads|adwords|linkedin ?ads|instagram ads|twitter ads", "advertising", D),
    (r"delhivery|blue ?dart|dtdc|shiprocket|ecom express|xpressbees|\bporter\b|borzo|india post|speed post", "courier", D),
    (r"wework|awfis|91springboard|innov8|cowork|stationery|office ?supplies|printing|xerox", "office", D),
    (r"consult|professional fee|legal|advocate|chartered accountant|\bca fees?\b|audit fee|upwork|fiverr|freelanc|contractor|retainer", "professional_services", D),
    (r"\bsip\b|mutual ?fund|\bmf\b|zerodha|groww|upstox|kuvera|coin by|\bppf\b|\bnps\b|fixed deposit|\bfd\b|\brd\b|bse ltd|bse limited|nse clearing|indian clearing|\biccl\b|smallcase|paytm money|\bcams\b|kfintech|^eba/", "investment", D),
    (r"insurance|\blic\b|premium|policy ?bazaar|star health|hdfc ergo|icici lombard|niva bupa|care health|acko|digit insur", "insurance", D),
    (r"\bemi\b|\bloan\b|bajaj fin|home ?loan|housing fin", "loan_emi", D),
    (r"\brent\b|nobroker|nestaway", "rent", D),
    (r"school|college|university|tuition|academy", "education", D),
    (r"donation|charity|pm ?cares|\bngo\b", "donation", D),
    (r"\batm\b|cash ?wdl|cash withdrawal|\bnwd\b|\beaw\b|\bawb\b|\batw\b|\bcwd\b|upi ?cash|iccw|\bnfs\b", "cash_withdrawal", D),
    (r"pharma|apollo|medplus|hospital|clinic|\b1mg\b|netmeds|diagnostic|health ?care|practo|chemist|medical", "medical", D),
    (r"electricity|bescom|msedcl|mseb|tata power|adani (elec|energy)|torrent power|water bill|gas bill|mahanagar gas|indane|broadband|airtel|\bjio\b|vodafone|\bvi\b|bsnl|act fibernet|recharge|\bdth\b|tata ?play", "utilities", D),
    (r"swiggy|bundl|zomato|restaurant|\bcafe\b|eatclub|domino|mcdonald|starbucks|\bkfc\b|pizza|burger|chinese|fast ?fo|biryani|dhaba|bakery|sweets|haldiram|chaayos|dine|food|kitchen", "dining", D),
    (r"bigbasket|blinkit|zepto|grofers|dmart|instamart|jiomart|more retail|reliance fresh|nature'?s basket|supermarket|kirana|grocer", "groceries", D),
    (r"movie|cinema|pvr|inox|cinepolis|bookmyshow|netflix|spotify|hotstar|prime video|youtube|zee5|sonyliv|apple\.com|google play|gaming|steam", "entertainment", D),
    (r"amazon|flipkart|myntra|ajio|nykaa|meesho|tata ?cliq|croma|reliance digital|decathlon|ikea|lifestyle|westside|zudio", "shopping", D),
    (r"\buber\b|\bola\b|rapido|irctc|makemytrip|goibibo|indigo|air ?india|vistara|akasa|cleartrip|redbus|fastag|ixigo|metro|hotel|\boyo\b|airbnb|lounge|dreamfolks|airport|parking|toll|auto serv|service cent|car wash|tyre|motors", "travel", D),
    (r"fuel|petrol|diesel|iocl|hpcl|bpcl|indian oil|\bshell\b|filling station|\bfilli?n?g?\b|\bfi$", "fuel", D),
    (r"charges?|\bchrg|\bfee\b|annual fee|late fee|finance charge|sms alert|\bamc\b|gst on|\bigst\b|\bcgst\b|\bsgst\b|penalty", "bank_charges", D),
    (r"bbps|bill ?pay|billdesk|^bil/", "bill_payment", D),
    (r"^ach d\b|\bach d-|\bnach d|\becs d|\bnach dr\b|standing instruction|\bsi\b", "auto_debit", D),
    (r"^pos\b|\bpos[- ]|\bvps\b|\bips\b|\becom\b|visa pos|debit card|\bmps\b|rupay", "card_purchase", D),
    (r"\bupi\b|^upi", "upi_transfer", A),
    (r"\b(neft|imps|rtgs|ift|fund transfer|trf|mmt)\b", "bank_transfer", A),
]
_COMPILED = [(re.compile(p, re.I), cat, side) for p, cat, side in RULES]
_CARD_PAYMENT_CREDIT = re.compile(r"payment|thank you|received|recd|autopay|bbps|neft|imps|upi", re.I)


GENERIC_TOKENS = {"pos", "visa", "master", "rupay", "upi", "ach", "nach", "ecs", "neft", "imps", "rtgs", "mmt", "ift", "c", "d", "cr", "dr",
                  "to", "by", "from", "ref", "trf", "transfer", "payment", "pay", "paid", "the", "www", "com", "in", "ltd", "limited",
                  "pvt", "private", "india", "vps", "ips", "bil", "onl", "inf", "mb", "ib", "p2a", "p2m", "okaxis", "okhdfcbank",
                  "oksbi", "okicici", "ybl", "paytm", "apl", "ibl", "axl"}


def merchant_key(narration: str) -> str:
    """A stable key for 'the same counter-party': drops codes, card numbers, references and dates.

    "ACH C- REC LIMITED-835325" -> "rec"; "POS 416021XXXXXX9685 THE FERN HOTEL A" -> "fern hotel".
    """
    tokens = re.split(r"[^a-z0-9]+", narration.lower())
    words = [t for t in tokens if t and not any(ch.isdigit() for ch in t) and "xxx" not in t and t not in GENERIC_TOKENS and len(t) > 1]
    return " ".join(words[:3])


def classify(narration: str, is_debit: bool = True, account_kind: str = "bank", user_rules: dict[str, str] | None = None) -> str:
    if user_rules:
        learned = user_rules.get(merchant_key(narration))
        if learned:
            return learned
    # On a card statement, a credit that looks like a payment is the other leg of the bank's bill payment.
    if account_kind == "card" and not is_debit:
        if _CARD_PAYMENT_CREDIT.search(narration) and not re.search(r"refund|reversal|cashback", narration, re.I):
            return "card_settlement"
    side = D if is_debit else C
    for pattern, category, rule_side in _COMPILED:
        if rule_side in (A, side) and pattern.search(narration):
            return category
    return "uncategorized"
