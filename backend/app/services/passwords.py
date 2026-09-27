"""Candidate passwords for statement PDFs, built from the owner's own details.

Indian banks protect statements with predictable formulas, for example
HDFC/Axis/ICICI cards: first four letters of the name + DDMM of birth
(ADIT0512), AIS/TIS: PAN in lower case + DDMMYYYY, SBI Card: DDMMYYYY + last
four card digits. Details are used only for the current request and are
never stored or logged.
"""
import re
from dataclasses import dataclass, field
from datetime import date, datetime


@dataclass
class Hints:
    name: str = ""
    dob: str = ""  # any common format; ISO from <input type=date>
    pan: str = ""
    extras: list[str] = field(default_factory=list)  # card last-4s, customer IDs, mobile numbers
    passwords: list[str] = field(default_factory=list)  # passwords the user already knows

    @property
    def empty(self) -> bool:
        return not (self.name or self.dob or self.pan or self.extras or self.passwords)


def _parse_dob(value: str) -> date | None:
    value = value.strip()
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y", "%d%m%Y"):
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            pass
    return None


def _cases(s: str) -> list[str]:
    return list(dict.fromkeys([s.upper(), s.lower(), s.capitalize()]))


def candidates(h: Hints) -> list[str]:
    out: list[str] = [""]  # many PDFs only carry an owner password and open with an empty one
    out += [p for p in h.passwords if p]

    words = re.findall(r"[A-Za-z]+", h.name)
    names: list[str] = []
    if words:
        names.append(words[0][:4])                    # first name
        names.append("".join(words)[:4])              # name without spaces (short first names)
        if len(words) > 1:
            names.append(words[-1][:4])               # surname
    names = [n for n in dict.fromkeys(names) if len(n) >= 3]

    dob = _parse_dob(h.dob) if h.dob else None
    dates: list[str] = []
    if dob:
        dd, mm, yyyy = f"{dob.day:02d}", f"{dob.month:02d}", f"{dob.year}"
        dates = [dd + mm, dd + mm + yyyy, dd + mm + yyyy[2:], mm + dd, yyyy + mm + dd]
        dates = list(dict.fromkeys(dates))
    pan = re.sub(r"\W", "", h.pan).upper()
    extras = [re.sub(r"\s", "", e) for e in h.extras if e.strip()]
    last4s = [e[-4:] for e in extras if e.isdigit() and len(e) >= 4]

    for n in names:
        for c in _cases(n):
            out += [c + d for d in dates]
            out += [c + e for e in last4s]
    for d in dates:
        out.append(d)
        out += [d + e for e in last4s] + [e + d for e in last4s]
    if pan:
        out += [pan, pan.lower()]
        out += [pan.lower() + d for d in dates] + [pan + d for d in dates]
    out += extras
    if dob:
        out += [e + dob.strftime("%d%m") for e in extras]
    return list(dict.fromkeys(out))
