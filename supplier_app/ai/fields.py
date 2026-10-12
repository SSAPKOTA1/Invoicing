"""Regex based field extraction: dates, amounts with labels, invoice numbers, IBAN, VAT id, sender."""

from __future__ import annotations

import re
from datetime import date, timedelta

from supplier_app.errors import ValidationError
from supplier_app.models.enums import DocumentType as D
from supplier_app.models.enums import ReferenceType
from supplier_app.util.dates import parse_any_date
from supplier_app.util.money import parse_amount
from supplier_app.util.normalize import normalize_iban, normalize_reference, valid_iban, valid_vat_id

from .interfaces import FieldExtractor, ReferenceExtractor
from .invoice_amounts import extract_invoice_amounts
from .layout import header_value_pairs
from .references import LabelledReferenceExtractor
from .result_types import Classification, ExtractedFields, ExtractedReference, FieldValue
from .rules import (
    AMOUNT_LABELS,
    LEGAL_FORM_RE,
    tolerant,
)
from .vocab import (
    AMOUNT_RE,
    BARE_DATE_CELL,
    BARE_NUMBER_CELL,
    DATE_PATTERN,
    DOCUMENT_DATE_LABELS,
    DUE_DATE_LABELS,
    IMMEDIATE_TERMS,
    INVOICE_NUMBER_STRONG,
    INVOICE_NUMBER_WEAK,
    PAYMENT_DATE_LABELS,
    RELATIVE_TERMS,
    SERVICE_DATE_CONTEXT,
    SKONTO_LINE,
    ExtraVocab,
)

DATE_RE = re.compile(rf"({DATE_PATTERN})", re.I)
_SPACE_LIKE = str.maketrans({"\u00a0": " ", "\u202f": " ", "\u2009": " ", "\u2007": " ", "\u2008": " ", "\u200a": " ",
                             "\u2013": "-", "\u2212": "-"})
IBAN_RE = re.compile(r"\b([A-Z]{2}\d{2}(?:[ ]?[A-Z0-9]{4}){3,7}(?:[ ]?[A-Z0-9]{1,4})?)\b")
VAT_ID_RE = re.compile(r"\b(DE\s?\d{9}|ATU\d{8}|NL\d{9}B\d{2}|FR[A-Z0-9]{2}\s?\d{9}|IT\d{11}|PL\d{10}|BE0?\d{9,10})\b")
INVOICE_TOKEN = r"(?:[A-Za-z0-9][A-Za-z0-9\-/._]*)?\d[A-Za-z0-9\-/._]*"
_KEY_GROUP = {D.INVOICE: "invoice", D.CREDIT_NOTE: "invoice", D.BANK_STATEMENT: "payment"}
_LINE_END = re.compile(r"[^\n]*")


def _compile_labels(labels: list[str]) -> re.Pattern[str]:
    body = "|".join(f"(?:{tolerant(x)})" for x in labels)
    return re.compile(rf"(?<![a-zäöüß])(?:{body})(?![a-zäöüß])", re.I | re.M)


def _first_amount(text: str, start: int, max_gap: int = 90) -> tuple[int, int, int, str] | None:
    """First amount after ``start`` on the same line (or at the beginning of the next line)."""
    eol = text.find("\n", start)
    eol = len(text) if eol < 0 else eol
    segment = text[start:eol]
    m = AMOUNT_RE.search(segment, 0, max_gap)
    if m:
        return _amount_hit(text, start + m.start(1), start + m.end(1))
    if eol < len(text):
        nxt_end = text.find("\n", eol + 1)
        nxt_end = len(text) if nxt_end < 0 else nxt_end
        line = text[eol + 1 : nxt_end]
        m = AMOUNT_RE.match(line.lstrip())
        if m and len(line) - len(line.lstrip()) <= 12:
            off = eol + 1 + (len(line) - len(line.lstrip()))
            return _amount_hit(text, off + m.start(1), off + m.end(1))
    return None


def _amount_hit(text: str, s: int, e: int) -> tuple[int, int, int, str] | None:
    raw = text[s:e]
    try:
        return parse_amount(raw), s, e, raw
    except ValidationError:
        return None


def _parse_any_date(raw: str) -> date | None:
    return parse_any_date(raw)


def _first_date(text: str, start: int, max_gap: int = 70) -> tuple[date, int, int, str] | None:
    eol = text.find("\n", start)
    eol = len(text) if eol < 0 else eol
    segments = [(start, eol)]
    if eol < len(text):
        nxt = text.find("\n", eol + 1)
        segments.append((eol + 1, len(text) if nxt < 0 else nxt))
    for idx, (a, b) in enumerate(segments):
        for m in DATE_RE.finditer(text, a, min(b, a + max_gap + 20) if idx == 0 else b):
            parsed = _parse_any_date(m.group(1))
            if parsed:
                return parsed, m.start(1), m.end(1), m.group(1)
        if idx == 0 and text[start:eol].strip().strip(":.-") and DATE_RE.search(text[start:eol]) is None:
            # something else than a date follows on the same line: do not look at the next line
            break
    return None


class RegexFieldExtractor(FieldExtractor):
    """Deterministic extraction; every value has a confidence and a span into the source text."""

    def __init__(self, references: ReferenceExtractor | None = None, extra: ExtraVocab | None = None) -> None:
        self.references = references or LabelledReferenceExtractor()
        self.extra = extra or ExtraVocab()
        self._amount_rx = {
            group: {key: _compile_labels(lbls) for key, lbls in keys.items()} for group, keys in AMOUNT_LABELS.items()
        }
        self._date_rx = {
            "document": _compile_labels([*self.extra.patterns("document_date"), *DOCUMENT_DATE_LABELS]),
            "payment": _compile_labels(PAYMENT_DATE_LABELS),
            "due": _compile_labels([*self.extra.patterns("due_date"), *DUE_DATE_LABELS])}
        strong = "|".join(f"(?:{tolerant(x)})" for x in [*self.extra.patterns("invoice_number"), *INVOICE_NUMBER_STRONG])
        weak = "|".join(f"(?:{tolerant(x)})" for x in INVOICE_NUMBER_WEAK)
        tail = (r"(?![a-zäöüß])[ \t]*(?:(?:nr|nummer|no|number|n°|num)\.?[ \t]*)?[:#]?[ \t]*(?P<value>" + INVOICE_TOKEN + ")")
        self._invoice_rx = re.compile(rf"(?<![a-zäöüß])(?P<label>{strong}|{weak}){tail}", re.I)
        self._pairs: list = []
        self._strong_label = re.compile(rf"^(?:{strong})$", re.I)

    # -- public ---------------------------------------------------------------
    def extract(self, text: str, classification: Classification) -> ExtractedFields:
        text = text.translate(_SPACE_LIKE)  # same length: spans stay valid
        f = ExtractedFields()
        dtype = classification.doc_type
        group = _KEY_GROUP.get(dtype, "dunning" if dtype != D.OTHER and dtype != D.DELIVERY_NOTE else "invoice")
        f.references = self.references.extract(text)
        self._pairs = header_value_pairs(text)
        self._dates(text, f, dtype)
        self._amounts(text, f, group)
        self._invoice_numbers(text, f, dtype)
        self._ids(text, f)
        f.sender_name = self._sender_name(text)
        if f.amounts.get("payment_amount") is None and group == "payment":
            self._payment_fallback(text, f)
        return f

    # -- dates ----------------------------------------------------------------
    def _label_date(self, text: str, key: str) -> FieldValue | None:
        for m in self._date_rx[key].finditer(text):
            line_start = text.rfind("\n", 0, m.start()) + 1
            line_end = text.find("\n", m.end())
            line = text[line_start : len(text) if line_end < 0 else line_end]
            if key in ("due", "document") and SKONTO_LINE.search(line):
                continue  # "bei Zahlung bis 20.03. 2 % Skonto" is not the due date
            if len([c for c in re.split(r"\t+|\s{2,}", line.strip()) if c]) >= 2 and not re.search(r"\d", line):
                continue  # a header row of a table: its values are read from the cells below (see pairs)
            hit = _first_date(text, m.end())
            if hit:
                value, s, e, raw = hit
                return FieldValue(value, 0.9, (s, e), raw)
        for pair in self._pairs:  # header row / stacked columns: "Rechnungsdatum   Fällig am" over the values
            bare = key == "document" and BARE_DATE_CELL.match(pair.label.strip().rstrip(":"))
            if (bare or self._date_rx[key].search(pair.label)) and not SKONTO_LINE.search(pair.label):
                parsed = _parse_any_date(pair.value)
                if parsed is None:
                    hit = DATE_RE.search(pair.value)
                    parsed = _parse_any_date(hit.group(1)) if hit else None
                if parsed:
                    return FieldValue(parsed, 0.85, (pair.start, pair.end), pair.value)
        return None

    @staticmethod
    def _relative_due(text: str, base: date) -> FieldValue | None:
        """Payment terms in days ("30 Tage netto", "Net 30", "Zahlungsziel: 14 Tage")."""
        for rx in RELATIVE_TERMS:
            for m in rx.finditer(text):
                line_start = text.rfind("\n", 0, m.start()) + 1
                line_end = text.find("\n", m.end())
                line = text[line_start : len(text) if line_end < 0 else line_end]
                if SKONTO_LINE.search(line) and not re.search(r"netto|\bnet\b", m.group(0), re.I):
                    continue
                days = int(m.group("d"))
                if 0 < days <= 365:
                    return FieldValue(base + timedelta(days=days), 0.6, (m.start("d"), m.end("d")), m.group(0))
        return None

    def _dates(self, text: str, f: ExtractedFields, dtype: D) -> None:
        f.payment_date = self._label_date(text, "payment")
        f.document_date = self._label_date(text, "document") or (f.payment_date if dtype == D.BANK_STATEMENT else None)
        if f.document_date is None:
            head = "\n".join(text.splitlines()[:25])
            for m in DATE_RE.finditer(head):
                line_start = head.rfind("\n", 0, m.start()) + 1
                before = head[line_start : m.start()].lower()
                if re.search(r"(vom|from|dated|bis|am|per|until|before|spätestens)\s*$", before[-14:]):
                    continue
                if SERVICE_DATE_CONTEXT.search(before) or re.search(r"(fällig|zahlbar|due|échéance|scadenza|vencimiento)", before):
                    continue
                parsed = _parse_any_date(m.group(1))
                if parsed:
                    f.document_date = FieldValue(parsed, 0.5, (m.start(1), m.end(1)), m.group(1))
                    break
        due = self._label_date(text, "due")
        if due is None:
            base = f.document_date.value if f.document_date else None
            if base is not None:
                due = self._relative_due(text, base)
                if due is None and dtype in (D.INVOICE, D.CREDIT_NOTE, D.OTHER):
                    imm = IMMEDIATE_TERMS.search(text)
                    if imm:
                        due = FieldValue(base, 0.6, (imm.start(), imm.end()), imm.group(0))
        if dtype in (D.INVOICE, D.CREDIT_NOTE, D.OTHER, D.DELIVERY_NOTE):
            f.due_date = due
        else:
            f.deadline = due
        for m in re.finditer(r"(?:rechnung|invoice|facture|fattura|factura|beleg)[^\n]{0,80}?\b(?:vom|dated|from|of|du|del|de)\s+(" + DATE_RE.pattern + ")", text, re.I):
            parsed = _parse_any_date(m.group(2))
            if parsed:
                f.referenced_invoice_dates.append(FieldValue(parsed, 0.8, (m.start(2), m.end(2)), m.group(2)))

    # -- amounts --------------------------------------------------------------
    def _amounts(self, text: str, f: ExtractedFields, group: str) -> None:
        if group == "invoice":
            self._invoice_amounts(text, f)
            return
        for key, rx in self._amount_rx[group].items():
            hits: list[FieldValue] = []
            for m in rx.finditer(text):
                hit = _first_amount(text, m.end())
                if hit:
                    cents, s, e, raw = hit
                    hits.append(FieldValue(cents, 0.88, (s, e), raw))
            if not hits:
                continue
            if key == "fees":
                f.fee_items = hits
                f.amounts[key] = FieldValue(sum(h.value for h in hits), 0.85, hits[0].span, hits[0].raw)
            else:
                f.amounts[key] = hits[0]
        if group == "dunning" and "principal" not in f.amounts and "total_claimed" in f.amounts and len(f.amounts) == 1:
            f.amounts["principal"] = FieldValue(f.amounts["total_claimed"].value, 0.4, f.amounts["total_claimed"].span,
                                                f.amounts["total_claimed"].raw)

    def _invoice_amounts(self, text: str, f: ExtractedFields) -> None:
        res = extract_invoice_amounts(text, self.extra)
        for key, value in (("net", res.net), ("vat", res.vat), ("gross", res.gross)):
            if value is not None:
                f.amounts[key] = value
        f.derived = set(res.derived)
        self._vat_rate(text, f)
        if res.rate is not None and (f.vat_rate is None or res.consistent):
            try:
                f.vat_rate = FieldValue(str(float(res.rate)).rstrip("0").rstrip(".") if "." in res.rate else res.rate,
                                        0.9 if res.consistent else 0.6, f.vat_rate.span if f.vat_rate else None,
                                        res.rate)
            except ValueError:
                pass

    def _vat_rate(self, text: str, f: ExtractedFields) -> None:
        m = re.search(r"(\d{1,2}(?:[.,]\d+)?)\s*%\s*(?:mwst|ust|vat|mehrwertsteuer|umsatzsteuer)", text, re.I) or \
            re.search(r"(?:mwst|ust|vat|mehrwertsteuer|umsatzsteuer)[^\n\d]{0,12}(\d{1,2}(?:[.,]\d+)?)\s*%", text, re.I)
        if m:
            f.vat_rate = FieldValue(m.group(1).replace(",", "."), 0.85, (m.start(1), m.end(1)), m.group(1))
        cur = re.search(r"€|\bEUR\b|\bCHF\b|\bUSD\b|\bGBP\b|£|\$", text)
        if cur:
            sym = {"€": "EUR", "£": "GBP", "$": "USD"}.get(cur.group(0), cur.group(0))
            f.currency = FieldValue(sym, 0.9, (cur.start(), cur.end()), cur.group(0))

    def _payment_fallback(self, text: str, f: ExtractedFields) -> None:
        for m in AMOUNT_RE.finditer(text):
            f.amounts["payment_amount"] = FieldValue(parse_amount(m.group(1)), 0.4, (m.start(1), m.end(1)), m.group(1))
            return

    # -- invoice numbers, ids, sender -------------------------------------------
    def _invoice_numbers(self, text: str, f: ExtractedFields, dtype: D) -> None:
        seen: set[str] = set()

        def add(value: str, conf: float, span: tuple[int, int], min_len: int = 3) -> None:
            value = value.rstrip(".,;:-/")
            norm = normalize_reference(value)
            if (re.fullmatch(r"\d{1,2}\.\d{1,2}\.\d{2,4}", value) or AMOUNT_RE.fullmatch(value) or len(norm) < min_len
                    or norm in seen or DATE_RE.fullmatch(value)):
                return
            seen.add(norm)
            f.invoice_numbers.append(FieldValue(value, conf, (span[0], span[0] + len(value)), value))

        for m in self._invoice_rx.finditer(text):
            label = m.group("label")
            strong = bool(self._strong_label.match(re.sub(r"\s+", " ", label.strip())))
            value = m.group("value")
            if not strong and not re.search(r"\d", value):
                continue
            if not strong and re.fullmatch(r"(?:vom|nr|nummer|no|number|from|date|datum)", value, re.I):
                continue
            add(value, 0.92 if strong else 0.78, m.span("value"), 1 if strong else 3)
        for pair in self._pairs:  # "Rechnungsnummer   Datum" over "R-2024-77   12.03.2024"
            cell = pair.label.strip().rstrip(":").strip()
            is_strong = bool(self._strong_label.match(cell))
            if is_strong or (BARE_NUMBER_CELL.match(cell) and dtype in (D.INVOICE, D.CREDIT_NOTE)):
                tok = re.search(INVOICE_TOKEN, pair.value)
                if tok and not DATE_RE.fullmatch(pair.value.strip()):
                    add(tok.group(0), 0.9 if is_strong else 0.75, (pair.start + tok.start(), pair.start + tok.end()),
                        1 if is_strong else 3)
        for ref in f.references:
            if ref.ref_type == ReferenceType.PAYMENT_REFERENCE:
                for tok in re.findall(INVOICE_TOKEN, ref.raw):
                    norm = normalize_reference(tok)
                    if norm not in seen and len(norm) >= 4:
                        seen.add(norm)
                        f.invoice_numbers.append(FieldValue(tok, 0.5, ref.value.span, tok))
        if dtype == D.BANK_STATEMENT:
            for m in re.finditer(r"verwendungszweck\s*:?[ \t]*([^\n]*)", text, re.I):
                for tok in re.findall(INVOICE_TOKEN, m.group(1)):
                    norm = normalize_reference(tok)
                    if norm not in seen and len(norm) >= 4 and not DATE_RE.fullmatch(tok):
                        seen.add(norm)
                        f.invoice_numbers.append(FieldValue(tok.rstrip(".,;:"), 0.7, (m.start(1), m.end(1)), tok))
        f.invoice_numbers.sort(key=lambda v: -v.confidence)  # stable: text order among equals

    def _ids(self, text: str, f: ExtractedFields) -> None:
        for m in IBAN_RE.finditer(text):
            iban = normalize_iban(m.group(1))
            ok = valid_iban(iban)
            if not ok:
                # OCR often appends the next word; try the longest valid prefix
                for cut in range(len(iban), 14, -1):
                    if valid_iban(iban[:cut]):
                        iban, ok = iban[:cut], True
                        break
            if any(x.value == iban for x in f.ibans):
                continue
            f.ibans.append(FieldValue(iban, 0.95 if ok else 0.35, (m.start(1), m.end(1)), m.group(1)))
        for m in VAT_ID_RE.finditer(text):
            vid = re.sub(r"\s+", "", m.group(1))
            if not any(x.value == vid for x in f.vat_ids):
                f.vat_ids.append(FieldValue(vid, 0.9 if valid_vat_id(vid) else 0.4, (m.start(1), m.end(1)), m.group(1)))

    @staticmethod
    def _sender_name(text: str) -> FieldValue | None:
        pos = 0
        fallback: FieldValue | None = None
        for i, line in enumerate(text.splitlines()):
            stripped = line.strip()
            start = text.find(line, pos) if line else pos
            pos = start + len(line)
            if not stripped or i > 12:
                continue
            candidate = re.split(r"\s[·|•]\s", stripped)[0].strip()
            if LEGAL_FORM_RE.search(candidate) and not re.search(r"\d{3,}", candidate[:12]):
                return FieldValue(candidate, 0.7 if i < 6 else 0.5, (start, start + len(candidate)), candidate)
            if fallback is None and len(candidate) > 3 and not re.match(r"^\d", candidate):
                fallback = FieldValue(candidate, 0.3, (start, start + len(candidate)), candidate)
        return fallback


def invoice_ref(ref_type: ReferenceType, raw: str, conf: float = 0.9) -> ExtractedReference:
    """Helper for tests/builders."""
    return ExtractedReference(ref_type, FieldValue(raw, conf, None, raw))
