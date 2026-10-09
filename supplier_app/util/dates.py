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


def now_iso() -> str:
    return datetime.now().replace(microsecond=0).isoformat(sep=" ")


def today() -> date:
    return date.today()
