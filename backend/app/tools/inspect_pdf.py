"""Show a statement PDF's layout with personal data masked, and what the parser makes of it.

Use it when a statement imports with "Couldn't find any transactions": the masked output shows the
line/table structure (dates, amounts, Cr/Dr markers, column headers) without revealing names,
merchants, card numbers or amounts, so it can be shared to add support for that layout.

    python -m app.tools.inspect_pdf statement.pdf [--name "Full Name" --dob YYYY-MM-DD --pan ABCDE1234F] [--password PW]

On the server:  docker compose cp statement.pdf api:/tmp/s.pdf
                docker compose exec api python -m app.tools.inspect_pdf /tmp/s.pdf --name "Full Name" --dob 1990-12-05 --pan ABCDE1234F
"""
import argparse, re, sys

from app.services.masking import mask, layout_sample


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("pdf")
    ap.add_argument("--password", default="", help="the PDF password, if you know it")
    ap.add_argument("--name", default="", help="your name as on statements (tries the usual bank password patterns)")
    ap.add_argument("--dob", default="", help="date of birth, e.g. 1990-12-05 or 05/12/1990")
    ap.add_argument("--pan", default="")
    ap.add_argument("--extras", default="", help="card last 4 digits / customer IDs, comma separated")
    ap.add_argument("--lines", type=int, default=80, help="text lines to show (default 80)")
    ap.add_argument("--unmasked", action="store_true", help="show real text (do not share this output)")
    ap.add_argument("--all-rows", action="store_true", help="list every parsed row, not just the first 10")
    args = ap.parse_args(argv)
    from app.services.passwords import Hints
    from app.services.pdf import unlock, read_pdf, detect, parse_pdf, NeedsPassword
    data = open(args.pdf, "rb").read()
    try:
        hints = Hints(name=args.name, dob=args.dob, pan=args.pan, extras=[e for e in re.split(r"[,\s]+", args.extras) if e],
                      passwords=[args.password] if args.password else [])
        plain = unlock(data, hints)
    except NeedsPassword:
        sys.exit("Could not open the PDF: none of the password patterns worked. Check --name/--dob/--pan or pass --password.")
    print("== Unlock ==\n" + ("opened (no password needed)" if plain is data else "opened with a password built from your details"))
    content = read_pdf(plain)
    text, tables = content.text, [row for t in content.tables for row in t]
    show = (lambda s: s) if args.unmasked else mask
    info = detect(text)
    print("== Detection ==")
    print(f"kind={info['kind']}  institution={info['institution']}  last4={'found' if info['last4'] else 'not found'}")
    print(f"\n== Text: first {args.lines} non-empty lines{' (MASKED)' if not args.unmasked else ''} ==")
    lines = [l for l in text.splitlines() if l.strip()]
    for i, line in enumerate(lines[: args.lines], 1):
        print(f"{i:3} | {show(line)}")
    from app.services.pdf import DATE
    print("\n== Lines starting with a date (MASKED, with the line after each) ==")
    for line in layout_sample(text, DATE, limit=30):
        print("   " + line)
    print(f"\n== Tables: {len(tables)} rows found by the table extractor ==")
    for row in tables[:15]:
        print("   | " + " | ".join(show(str(c or "")).replace("\n", " ⏎ ") for c in row))
    warnings: list[str] = []
    diag: dict = {}
    rows = parse_pdf(content, info["kind"] or "bank", warnings, diag)
    print(f"\n== Parser result: {len(rows)} transaction(s) ==")
    print("   found per method: " + ", ".join(f"{k}={v}" for k, v in diag.items()))
    for r in rows if args.all_rows else rows[:10]:
        print(f"   {show(r['date'].isoformat())}  debit={'yes' if r['debit'] else 'no '}  credit={'yes' if r['credit'] else 'no '}  {show(r['narration'])[:60]}")
    for w in warnings:
        print("   warning:", w)


if __name__ == "__main__":
    main()
