"""Labelled reference numbers (Bearbeitungsnummer, Aktenzeichen, Vorgangsnummer ...)."""

from __future__ import annotations

import re

from supplier_app.models.enums import ReferenceType
from supplier_app.util.normalize import normalize_reference

from .interfaces import ReferenceExtractor
from .result_types import ExtractedReference, FieldValue
from .rules import REFERENCE_LABELS, tolerant

_CUT_RE = re.compile(r"\s{2,}|\s[·|•]\s|\s-\s|\s(?:vom|from|dated|bei|und|and)\s|[,;(]")
_HAS_DIGIT = re.compile(r"\d")


class LabelledReferenceExtractor(ReferenceExtractor):
    """Finds ``<label>: <value>`` pairs; user keywords per reference type extend the built-in labels."""

    def __init__(self, extra_keywords: dict[str, list[str]] | None = None) -> None:
        labels: dict[ReferenceType, list[str]] = {t: list(v) for t, v in REFERENCE_LABELS.items()}
        for key, words in (extra_keywords or {}).items():
            try:
                ref_type = ReferenceType(key)
            except ValueError:
                continue
            labels.setdefault(ref_type, []).extend(re.escape(w.strip()) for w in words if w.strip())
        self._patterns: list[tuple[ReferenceType, re.Pattern[str]]] = []
        for ref_type, alternatives in labels.items():
            if not alternatives:
                continue
            body = "|".join(f"(?:{tolerant(a)})" for a in alternatives)
            self._patterns.append((ref_type, re.compile(
                rf"(?<![a-zäöüß])(?:{body})(?![a-zäöüß])[ \t]*[:#.]?[ \t]*(?P<rest>[^\n]*)", re.I)))

    @staticmethod
    def _clean_value(rest: str) -> str | None:
        rest = rest.strip()
        m = _CUT_RE.search(rest)
        value = rest[: m.start()] if m else rest
        value = value.strip(" .:;")
        if not value or not _HAS_DIGIT.search(value) or len(value) > 32:
            return None
        parts = value.split()
        if len(parts) >= 2 and parts[0].isalpha() and len(parts[0]) <= 3 and _HAS_DIGIT.search(parts[1]):
            value = f"{parts[0]} {parts[1]}"  # e.g. 'AZ 55/24'
        elif len(parts) >= 2:
            digit_parts = [p for p in parts if _HAS_DIGIT.search(p)]
            if not digit_parts:
                return None
            value = digit_parts[0]
        if re.fullmatch(r"\d{1,2}\.\d{1,2}\.\d{2,4}", value) or re.fullmatch(r"\d+,\d{2}", value):
            return None
        return value

    def extract(self, text: str) -> list[ExtractedReference]:
        found: list[ExtractedReference] = []
        seen: set[tuple[ReferenceType, str]] = set()
        for ref_type, rx in self._patterns:
            for m in rx.finditer(text):
                value = self._clean_value(m.group("rest"))
                if value is None:
                    continue
                norm = normalize_reference(value)
                if len(norm) < 3 or (ref_type, norm) in seen:
                    continue
                seen.add((ref_type, norm))
                start = m.start("rest") + (m.group("rest").find(value) if value in m.group("rest") else 0)
                found.append(ExtractedReference(
                    ref_type, FieldValue(value, 0.9, (start, start + len(value)), value)))
        return found
