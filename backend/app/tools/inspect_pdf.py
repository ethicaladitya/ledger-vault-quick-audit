"""Show a statement PDF's layout with personal data masked, and what the parser makes of it.

Use it when a statement imports with "Couldn't find any transactions": the masked output shows the
line/table structure (dates, amounts, Cr/Dr markers, column headers) without revealing names,
merchants, card numbers or amounts, so it can be shared to add support for that layout.

    python -m app.tools.inspect_pdf statement.pdf [--password PW] [--lines 80] [--unmasked]

On the server:  docker compose cp statement.pdf api:/tmp/s.pdf
                docker compose exec api python -m app.tools.inspect_pdf /tmp/s.pdf --password PW
"""
import argparse, re, sys

# Words that describe layout rather than people or merchants; kept as-is.
KEEP = {w.lower() for w in """date dates time txn transaction transactions details description narration particulars amount amounts
    cr dr credit debit balance opening closing total due minimum payment payments received statement card number
    reward rewards points domestic international value ref reference no page of inr rs purchase purchases fee charges gst igst
    cgst sgst interest limit available cash previous new summary account type billing period from to and the""".split()}


def mask(text: str) -> str:
    text = re.sub(r"\d", "9", text)
    def word(m):
        w = m.group(0)
        if w.lower() in KEEP or len(w) <= 2:
            return w
        return w[0].upper() + "x" * (len(w) - 1) if w[0].isupper() else "x" * len(w)
    return re.sub(r"[A-Za-z]+", word, text)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("pdf")
    ap.add_argument("--password", default="")
    ap.add_argument("--lines", type=int, default=80, help="text lines to show (default 80)")
    ap.add_argument("--unmasked", action="store_true", help="show real text (do not share this output)")
    args = ap.parse_args(argv)
    from app.services.passwords import Hints
    from app.services.pdf import unlock, read_pdf, detect, parse_pdf, NeedsPassword
    data = open(args.pdf, "rb").read()
    try:
        plain = unlock(data, Hints(passwords=[args.password] if args.password else []))
    except NeedsPassword:
        sys.exit("The PDF is password-protected: pass --password")
    text, tables = read_pdf(plain)
    show = (lambda s: s) if args.unmasked else mask
    info = detect(text)
    print("== Detection ==")
    print(f"kind={info['kind']}  institution={info['institution']}  last4={'found' if info['last4'] else 'not found'}")
    print(f"\n== Text: first {args.lines} non-empty lines{' (MASKED)' if not args.unmasked else ''} ==")
    lines = [l for l in text.splitlines() if l.strip()]
    for i, line in enumerate(lines[: args.lines], 1):
        print(f"{i:3} | {show(line)}")
    print(f"\n== Tables: {len(tables)} rows found by the table extractor ==")
    for row in tables[:15]:
        print("   | " + " | ".join(show(str(c or "")).replace("\n", " ⏎ ") for c in row))
    warnings: list[str] = []
    rows = parse_pdf(text, tables, info["kind"] or "bank", warnings)
    print(f"\n== Parser result: {len(rows)} transaction(s) ==")
    for r in rows[:10]:
        print(f"   {r['date']}  debit={'yes' if r['debit'] else 'no '}  credit={'yes' if r['credit'] else 'no '}  {show(r['narration'])[:60]}")
    for w in warnings:
        print("   warning:", w)


if __name__ == "__main__":
    main()
