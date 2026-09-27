"""Masked layout report for every statement PDF in a folder, to share when adding a bank/card layout.

    python -m app.tools.inspect_folder ~/statements --out masked-layouts.txt

Asks once for the details your statement passwords are built from (typing is hidden, nothing is saved),
then runs the masked inspector (see inspect_pdf.py) on each PDF. File names are not written to the
report, since they often contain card numbers or dates; each file is numbered instead and the
number -> name mapping is printed only to your screen. Check the report before sharing it.
"""
import argparse, contextlib, getpass, io
from pathlib import Path

from app.tools import inspect_pdf


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("folder")
    ap.add_argument("--out", default="masked-layouts.txt")
    ap.add_argument("--lines", type=int, default=150, help="masked text lines per file (default 150)")
    args = ap.parse_args(argv)
    pdfs = sorted(p for p in Path(args.folder).expanduser().rglob("*") if p.suffix.lower() == ".pdf")
    if not pdfs:
        raise SystemExit(f"No PDFs found in {args.folder}")
    print(f"{len(pdfs)} PDF(s) found. Press Enter to skip any question.")
    name = input("Name as on statements: ").strip()
    dob = getpass.getpass("Date of birth, e.g. 1990-12-05 (hidden): ").strip()
    pan = getpass.getpass("PAN (hidden): ").strip()
    extras = getpass.getpass("Card last-4 digits / customer IDs, comma separated (hidden): ").strip()
    password = getpass.getpass("A statement password to also try (hidden): ").strip()
    hint_args = ["--name", name, "--dob", dob, "--pan", pan, "--extras", extras, "--password", password, "--lines", str(args.lines), "--all-rows"]
    report = []
    for i, pdf in enumerate(pdfs, 1):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            try:
                inspect_pdf.main([str(pdf)] + hint_args)
            except SystemExit as e:
                print(f"skipped: {e}")
            except Exception as e:  # a broken file must not stop the rest
                print(f"failed: {type(e).__name__}")
        report.append(f"\n\n######## FILE {i} ########\n{buf.getvalue()}")
        print(f"  file {i}: {pdf.name}")
    Path(args.out).write_text("".join(report))
    print(f"\nMasked report written to {Path(args.out).resolve()}")


if __name__ == "__main__":
    main()
