"""Money helpers. Money is always integer cents; floats are never used."""

from __future__ import annotations

import re
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from supplier_app.errors import ValidationError

_NUM_RE = re.compile(r"^[+-]?\d[\d.,' ]*$")


def format_cents(cents: int, *, symbol: bool = True, plus: bool = False) -> str:
    """Format cents in German style, e.g. ``123456 -> '1.234,56 €'``."""
    sign = "-" if cents < 0 else ("+" if plus and cents > 0 else "")
    euros, rest = divmod(abs(int(cents)), 100)
    text = f"{euros:,}".replace(",", ".") + f",{rest:02d}"
    return f"{sign}{text}{' €' if symbol else ''}"


def parse_amount(text: str) -> int:
    """Parse a German or English formatted amount to cents.

    Accepts ``1.234,56``, ``1234,56``, ``1,234.56``, ``1234.5``, ``12 €`` and a trailing
    minus. Raises :class:`ValidationError` when the text is not a number.
    """
    raw = text.replace("€", "").replace("EUR", "").replace(" ", " ").strip()
    negative = False
    if raw.endswith("-"):
        negative, raw = True, raw[:-1].strip()
    if raw.startswith("-"):
        negative, raw = True, raw[1:].strip()
    if raw.startswith("+"):
        raw = raw[1:].strip()
    raw = raw.replace(" ", "").replace("'", "")
    if not raw or not _NUM_RE.match(raw):
        raise ValidationError(f"Ungültiger Betrag: '{text}'")
    last_comma, last_dot = raw.rfind(","), raw.rfind(".")
    if last_comma >= 0 and last_dot >= 0:
        dec_sep = "," if last_comma > last_dot else "."
    elif last_comma >= 0:
        dec_sep = "," if raw.count(",") == 1 else ""
    elif last_dot >= 0:
        dec_sep = "." if raw.count(".") == 1 and len(raw) - last_dot - 1 in (1, 2) else ""
    else:
        dec_sep = ""
    if dec_sep:
        int_part, _, frac = raw.rpartition(dec_sep)
        int_part = int_part.replace(".", "").replace(",", "")
    else:
        int_part, frac = raw.replace(".", "").replace(",", ""), ""
    try:
        value = Decimal(f"{int_part or '0'}.{frac or '0'}")
    except InvalidOperation as exc:
        raise ValidationError(f"Ungültiger Betrag: '{text}'") from exc
    cents = int((value * 100).quantize(Decimal(1), rounding=ROUND_HALF_UP))
    return -cents if negative else cents


def to_decimal_euros(cents: int) -> Decimal:
    """Convert cents to a Decimal euro amount (for Excel export)."""
    return (Decimal(cents) / Decimal(100)).quantize(Decimal("0.01"))


def percent_of(cents: int, rate: Decimal) -> int:
    """``cents * rate / 100`` rounded half up (rate in percent)."""
    return int((Decimal(cents) * rate / Decimal(100)).quantize(Decimal(1), rounding=ROUND_HALF_UP))
