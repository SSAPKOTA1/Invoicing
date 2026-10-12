"""Date helpers (German format dd.mm.yyyy; ISO in the database)."""

from __future__ import annotations

import re
from datetime import date, datetime

from supplier_app.errors import ValidationError

_DE_RE = re.compile(r"^\s*(\d{1,2})\.(\d{1,2})\.(\d{4}|\d{2})\s*$")
_ISO_RE = re.compile(r"^\s*(\d{4})-(\d{2})-(\d{2})\s*$")

_MONTHS_DE = {
    "januar": 1, "jänner": 1, "februar": 2, "märz": 3, "maerz": 3, "april": 4, "mai": 5, "juni": 6,
    "juli": 7, "august": 8, "september": 9, "oktober": 10, "november": 11, "dezember": 12,
}


def format_date(value: date | None) -> str:
    """``date(2026,12,31) -> '31.12.2026'``; ``None`` -> ``''``."""
    return value.strftime("%d.%m.%Y") if value else ""


def to_iso(value: date | None) -> str | None:
    return value.isoformat() if value else None


def from_iso(text: str | None) -> date | None:
    if not text:
        return None
    return date.fromisoformat(text[:10])


def parse_date(text: str) -> date:
    """Parse ``dd.mm.yyyy``, ``dd.mm.yy`` or ISO ``yyyy-mm-dd``."""
    m = _DE_RE.match(text)
    try:
        if m:
            day, month, year = int(m[1]), int(m[2]), int(m[3])
            if year < 100:
                year += 2000
            return date(year, month, day)
        m = _ISO_RE.match(text)
        if m:
            return date(int(m[1]), int(m[2]), int(m[3]))
    except ValueError as exc:
        raise ValidationError(f"Ungültiges Datum: '{text}'") from exc
    raise ValidationError(f"Ungültiges Datum: '{text}'")


def parse_long_date(text: str) -> date | None:
    """Parse '5. März 2024' style dates; ``None`` when not recognised."""
    m = re.match(r"^\s*(\d{1,2})\.?\s+([A-Za-zäöüÄÖÜ]+)\s+(\d{4})\s*$", text)
    if not m:
        return None
    month = _MONTHS_DE.get(m[2].lower())
    if not month:
        return None
    try:
        return date(int(m[3]), month, int(m[1]))
    except ValueError:
        return None


#: month names and abbreviations in German, English, French, Italian, Spanish and Dutch (lower case, accents kept)
MONTH_WORDS: dict[str, int] = {}
for _month, _names in enumerate((
    "januar jänner jan january janvier gennaio enero januari",
    "februar feb february février fevrier febbraio febrero februari",
    "märz maerz mär mrz mar march mars marzo maart",
    "april apr avril aprile abril",
    "mai may mei maggio mayo",
    "juni jun june juin giugno junio",
    "juli jul july juillet luglio julio",
    "august aug août aout agosto augustus",
    "september sep sept settembre septiembre setiembre",
    "oktober okt oct october octobre ottobre octubre",
    "november nov novembre noviembre",
    "dezember dez dec december décembre decembre dicembre diciembre",
), start=1):
    for _name in _names.split():
        MONTH_WORDS[_name] = _month

_NUMERIC_RE = re.compile(r"^\s*(\d{1,2})\s?[./-]\s?(\d{1,2})\s?[./-]\s?(\d{4}|\d{2})\s*$")
_YMD_RE = re.compile(r"^\s*(\d{4})\s?[./-]\s?(\d{1,2})\s?[./-]\s?(\d{1,2})\s*$")
_DMY_TEXT_RE = re.compile(r"^\s*(\d{1,2})(?:st|nd|rd|th|\.|er)?\s+(?:de\s+)?([^\W\d_]+)\.?,?\s+(?:de\s+)?(\d{4}|\d{2})\s*$", re.I)
_MDY_TEXT_RE = re.compile(r"^\s*([^\W\d_]+)\.?\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(\d{4})\s*$", re.I)


def _year(value: int) -> int:
    return value + 2000 if value < 100 else value


def parse_any_date(text: str) -> date | None:
    """Parse the date notations found on invoices: ``15.03.2024``, ``15/03/24``, ``15-03-2024``, ``2024/03/15``,
    ``03/15/2024`` (month first only when the day cannot be a month), ``15 März 2024``, ``March 15, 2024``,
    ``15 mars 2024``. Returns ``None`` when the text is not a plausible date."""
    try:
        m = _NUMERIC_RE.match(text)
        if m:
            first, second, year = int(m[1]), int(m[2]), _year(int(m[3]))
            if second > 12 >= first:  # 03/15/2024 -> US notation
                return date(year, first, second)
            return date(year, second, first)
        m = _YMD_RE.match(text)
        if m:
            return date(int(m[1]), int(m[2]), int(m[3]))
        m = _DMY_TEXT_RE.match(text)
        if m and m[2].lower() in MONTH_WORDS:
            return date(_year(int(m[3])), MONTH_WORDS[m[2].lower()], int(m[1]))
        m = _MDY_TEXT_RE.match(text)
        if m and m[1].lower() in MONTH_WORDS:
            return date(int(m[3]), MONTH_WORDS[m[1].lower()], int(m[2]))
    except ValueError:
        return None
    return None


def now_iso() -> str:
    return datetime.now().replace(microsecond=0).isoformat(sep=" ")


def today() -> date:
    return date.today()
