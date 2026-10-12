"""Labelled reference numbers (Kundennummer, Vertragsnummer, Aktenzeichen, Schreibennummer ...).

A reference is a label and a value. Documents print them in four layouts, all handled here:

* inline            ``Kundennummer: 12345``
* two on one line   ``Kundennummer: 12345      Vertragsnummer: V-77``
* value below       ``Kundennummer:`` / ``12345``
* header over value ``Kundennummer   Vertragsnummer`` / ``12345   V-77``

The value ends at the next label (so ``Kundennummer 12345 Rechnungsnummer R-1`` is read correctly) and must look like a
reference (it contains a digit, is not a date or an amount).
"""

from __future__ import annotations

import re

from supplier_app.models.enums import ReferenceType
from supplier_app.util.normalize import normalize_reference

from .interfaces import ReferenceExtractor
from .layout import header_value_pairs
from .result_types import ExtractedReference, FieldValue
from .rules import INVOICE_NUMBER_LABELS, REFERENCE_LABELS, tolerant

_HAS_DIGIT = re.compile(r"\d")
_DATE = re.compile(r"\d{1,2}\.\d{1,2}\.\d{2,4}")
_AMOUNT = re.compile(r"\d{1,3}(?:\.\d{3})*,\d{2}|\d+,\d{2}")
#: words that end a value: separators, "vom <date>", conjunctions
_STOP = re.compile(r"\s{2,}|\t|\s[·|•]\s|\s(?:vom|from|dated|bei|und|and|für|zum|zur|per)\s|[;(]|\s-\s")
_COURT = re.compile(r"(?<![\w])\d{1,3}\s?[A-Za-zÄÖÜ]{1,3}\s?\d{1,5}/\d{2,4}(?![\w/])")  # 12 C 345/24, 100 Js 4711/23
_TOKEN = re.compile(
    r"(?<![\w])(?P<v>(?:(?!(?:vom|von|am|bis|ab|per|nr|no|an)\b)[A-Za-zÄÖÜäöü]{1,4}[ \-/]?)?\d[\w\-/.]*"  # AZ 123, V-77, R2024
    r"|(?![A-Za-zÄÖÜäöü]+(?:\s|$))[A-Za-zÄÖÜäöü][\w\-/.]*\d[\w\-/.]*)"  # INK-NEW-9, ABC-DEF-123
)
_FILLER = re.compile(r"^[ \t]*(?:[A-Za-zÄÖÜäöüß.]+[ \t]+){0,3}?[A-Za-zÄÖÜäöüß.]*[ \t]*[:#][ \t]*")
_OTHER_LABELS = [r"rechnungs\s?-?\s?datum", r"belegdatum", r"datum", r"seite", r"fällig(?:keit)?", r"zahlbar", r"betrag", r"summe"]


class LabelledReferenceExtractor(ReferenceExtractor):
    """Finds ``<label> <value>`` pairs; user keywords per reference type extend the built-in labels."""

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
            if alternatives:
                body = "|".join(f"(?:{tolerant(a)})" for a in alternatives)
                self._patterns.append((ref_type, re.compile(rf"(?<![a-zäöüß])(?:{body})(?![a-zäöüß])", re.I)))
        # labels of values that are not references: they end a value as well
        foreign = "|".join(f"(?:{tolerant(a)})" for a in [*INVOICE_NUMBER_LABELS, *_OTHER_LABELS])
        self._foreign = re.compile(rf"(?<![a-zäöüß])(?:{foreign})(?![a-zäöüß])", re.I)
        prefix = r"(?:ihre|ihr|unsere|unser|die|der|das|your|our)?\s*"
        self._exact = {t: re.compile(rf"^{prefix}(?:{'|'.join(f'(?:{tolerant(a)})' for a in alts)})\.?$", re.I)
                       for t, alts in labels.items() if alts}

    # -- value ------------------------------------------------------------------------------------------------
    @staticmethod
    def _clean_value(rest: str) -> str | None:
        rest = rest.strip(" \t:#.-")
        if not rest:
            return None
        filler = _FILLER.match(rest)  # "beim Gläubiger: 4711" -> "4711"
        if filler and filler.end() < len(rest):
            rest = rest[filler.end():]
        cut = _STOP.search(rest)
        value = rest[: cut.start()] if cut else rest
        value = value.strip(" .:;,")
        if not value or len(value) > 60:
            return None
        court = _COURT.search(value)
        if court is not None and court.start() <= 3:
            return court.group(0)
        m = _TOKEN.search(value)
        if m is None or re.match(r",\d{2}(?!\d)", value[m.end():]):  # no token, or the integer part of an amount
            return None
        token = m.group("v").strip(" .,;:-/")
        # a number printed in groups: "12 345 678"
        tail = value[m.end():]
        if token.isdigit():
            groups = re.match(r"((?:[ ]\d{1,4}){1,3})(?![\d.,/-])", tail)
            if groups and not _DATE.search(token + groups.group(1)):
                token = f"{token}{groups.group(1)}"
        if not _HAS_DIGIT.search(token) or _DATE.search(token) or _AMOUNT.fullmatch(token) or len(token) > 32:
            return None
        return token

    def _value_below(self, lines: list[str], i: int) -> tuple[str, int] | None:
        """The value of a label that stands alone on its line: first cell of the next non-empty line."""
        for j in range(i + 1, min(len(lines), i + 3)):
            nxt = lines[j].strip()
            if not nxt:
                continue
            first = re.split(r"\s{2,}|\t|\s[·|•]\s", nxt)[0]
            if self._foreign.search(first) or any(rx.search(first) for _t, rx in self._patterns):
                return None  # the next line is a label itself
            value = self._clean_value(first)
            return (value, j) if value else None
        return None

    # -- main ------------------------------------------------------------------------------------------------
    def extract(self, text: str) -> list[ExtractedReference]:
        found: list[ExtractedReference] = []
        seen: set[tuple[ReferenceType, str]] = set()

        def add(ref_type: ReferenceType, value: str, start: int) -> None:
            norm = normalize_reference(value)
            if len(norm) < 3 or (ref_type, norm) in seen:
                return
            seen.add((ref_type, norm))
            found.append(ExtractedReference(ref_type, FieldValue(value, 0.9, (start, start + len(value)), value)))

        lines = text.split("\n")
        offsets: list[int] = []
        pos = 0
        for ln in lines:
            offsets.append(pos)
            pos += len(ln) + 1
        for i, line in enumerate(lines):
            hits: list[tuple[int, int, ReferenceType]] = []
            for ref_type, rx in self._patterns:
                hits += [(m.start(), m.end(), ref_type) for m in rx.finditer(line)]
            hits.sort(key=lambda h: (h[0], -(h[1] - h[0])))
            clean: list[tuple[int, int, ReferenceType]] = []
            for h in hits:  # overlapping labels ("Vertragskonto" / "Konto"): keep the first, longest
                if clean and h[0] < clean[-1][1]:
                    continue
                if clean and not line[clean[-1][1]:h[0]].strip(" \t:#.-"):
                    continue  # "Aktenzeichen: AZ 61-1090": the second label is the beginning of the value
                clean.append(h)
            foreign = [m.start() for m in self._foreign.finditer(line)]
            for idx, (s, e, ref_type) in enumerate(clean):
                limit = min([clean[idx + 1][0] if idx + 1 < len(clean) else len(line), *[f for f in foreign if f >= e]])
                rest = line[e:limit]
                value = self._clean_value(rest)
                if value is not None:
                    add(ref_type, value, offsets[i] + e + max(0, rest.find(value)))
                elif not rest.strip(" \t:#.-") and len(clean) == 1 and not line[:s].strip(" \t"):
                    below = self._value_below(lines, i)
                    if below is not None:
                        add(ref_type, below[0], offsets[below[1]] + max(0, lines[below[1]].find(below[0])))
        # header row over a value row ("Kundennummer   Vertragsnummer" / "12345   V-77")
        for pair in header_value_pairs(text):
            label = pair.label.strip().rstrip(":").strip()
            for ref_type, rx in self._exact.items():
                if rx.match(label):
                    value = self._clean_value(pair.value)
                    if value:
                        add(ref_type, value, pair.start)
                    break
        return found
