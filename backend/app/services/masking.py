"""Mask statement text so its layout can be shared without personal data.

Digits become 9, words become Xxxx, except layout words (Date, Amount, Cr, Dr, ...),
so dates, amounts, markers and column order stay visible.
"""
import re

KEEP = {w.lower() for w in """date dates time txn transaction transactions details description narration particulars amount amounts
    cr dr credit debit balance opening closing total due minimum payment payments received statement card number
    reward rewards points domestic international value ref reference no page of inr rs purchase purchases fee charges gst igst
    cgst sgst interest limit available cash previous new summary account type billing period from to and the
    jan feb mar apr may jun jul aug sep sept oct nov dec usd eur gbp emi""".split()}


def mask(text: str) -> str:
    text = re.sub(r"(\(cid:\d+\))+", "[icons]", text)  # glyphs without text, e.g. phone/email icons
    text = re.sub(r"\d", "9", text)

    def word(m):
        w = m.group(0)
        if w.lower() in KEEP or len(w) <= 2:
            return w
        return w[0].upper() + "x" * (len(w) - 1) if w[0].isupper() else "x" * len(w)
    return re.sub(r"[A-Za-z]+", word, text)


def layout_sample(text: str, date_pattern: str, limit: int = 25) -> list[str]:
    """Masked lines that start with a date, each with the line after it (amounts sometimes wrap)."""
    lines = [l for l in text.splitlines() if l.strip()]
    out = []
    for i, line in enumerate(lines):
        if re.match(rf"\s*{date_pattern}", line.strip(), re.I):
            out.append(mask(line))
            if i + 1 < len(lines):
                out.append("    next: " + mask(lines[i + 1]))
            if len(out) >= limit * 2:
                break
    return out
