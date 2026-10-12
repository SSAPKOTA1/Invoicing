"""Normalisation helpers for references, names and IBANs."""

from __future__ import annotations

import re
import unicodedata

_NON_ALNUM = re.compile(r"[^0-9A-Z]")
_UMLAUTS = str.maketrans({"ä": "ae", "ö": "oe", "ü": "ue", "Ä": "Ae", "Ö": "Oe", "Ü": "Ue", "ß": "ss"})


def _ascii(value: str) -> str:
    """Transliterate German umlauts (ü -> ue) and strip other accents."""
    return unicodedata.normalize("NFKD", value.translate(_UMLAUTS)).encode("ascii", "ignore").decode("ascii")


def normalize_reference(value: str) -> str:
    """Upper-case, strip spaces, dashes, slashes, dots (``RE-2024/001 -> RE2024001``)."""
    return _NON_ALNUM.sub("", _ascii(value).upper())


def normalize_iban(value: str) -> str:
    return re.sub(r"\s+", "", value).upper()


_LEGAL_FORMS = re.compile(
    r"\b(gmbh|ug|ag|kg|ohg|gbr|e\.?\s?k\.?|mbh|co|und|u|&|inc|ltd|llc|se|kgaa|e\.?\s?v\.?)\b", re.I
)


def normalize_name(value: str) -> str:
    """Casefolded name without legal forms and punctuation, for fuzzy matching."""
    folded = _ascii(value).lower()
    folded = folded.replace("&", " ")
    folded = _LEGAL_FORMS.sub(" ", folded)
    return re.sub(r"[^a-z0-9]+", " ", folded).strip()


def valid_iban(iban: str) -> bool:
    """ISO 13616 mod-97 checksum."""
    s = normalize_iban(iban)
    if not re.fullmatch(r"[A-Z]{2}\d{2}[A-Z0-9]{10,30}", s):
        return False
    rearranged = s[4:] + s[:4]
    digits = "".join(str(int(ch, 36)) for ch in rearranged)
    return int(digits) % 97 == 1


def valid_vat_id(vat: str) -> bool:
    """Format check for EU VAT IDs (German ones exactly DE + 9 digits)."""
    s = re.sub(r"\s+", "", vat).upper()
    if s.startswith("DE"):
        return bool(re.fullmatch(r"DE\d{9}", s))
    return bool(re.fullmatch(r"[A-Z]{2}[A-Z0-9]{2,12}", s))
