import re
RULES = [(r"\b(salary|payroll)\b", "salary"), (r"\b(interest|int\. paid)\b", "bank_interest"), (r"\b(card payment|cc payment|credit card)\b", "card_settlement"), (r"\b(upi|swiggy|zomato|restaurant)\b", "dining"), (r"\b(fuel|iocl|hpcl)\b", "fuel"), (r"\b(sip|mutual fund|zerodha)\b", "investment_purchase"), (r"\b(refund|reversal)\b", "refund_reversal"), (r"\b(neft|imps|rtgs).*(self|own)\b", "own_transfer")]
def classify(narration: str) -> str:
    for pattern, category in RULES:
        if re.search(pattern, narration, re.I): return category
    return "uncategorized"
