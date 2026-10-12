"""Net / VAT / gross of an invoice: label-driven candidates, table layouts and a consistency check.

The extraction does not trust a single label. It collects every amount with a recognisable label (``Netto``, ``MwSt``,
``Brutto``, ``Summe``, ``Total``, ``Montant HT`` ...), also from table headers ("Netto  MwSt  Brutto" over a row of
numbers), summary rows ("Gesamt 100,00 19,00 119,00") and stacked label/value columns, and then picks the combination
that satisfies ``net + vat = gross``. Missing values are derived from the others and flagged as derived.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from itertools import product

from supplier_app.errors import ValidationError
from supplier_app.util.money import parse_amount

from .result_types import FieldValue
from .vocab import AMOUNT_RE, VAT_RATES, ExtraVocab, classify_amount_label

_CELL_SPLIT = re.compile(r"\t+|\s{2,}|\s\|\s")
_MAX_OPTIONS = 6
_ONLY_AMOUNT = re.compile(r"[\s€$£*|:.\-–]*(?:EUR|CHF|GBP|USD)?[\s€$£]*#[\s€$£*|]*(?:EUR|CHF|GBP|USD)?\s*")


@dataclass
class Cand:
    kind: str  # net | vat | gross
    cents: int
    span: tuple[int, int]
    raw: str
    strength: float
    line: int
    rate: str | None = None
    combined: bool = False


@dataclass
class InvoiceAmounts:
    net: FieldValue | None = None
    vat: FieldValue | None = None
    gross: FieldValue | None = None
    rate: str | None = None
    derived: set[str] = field(default_factory=set)
    consistent: bool = False


def _amounts_in(line: str, base: int) -> list[tuple[int, int, int, str]]:
    out = []
    for m in AMOUNT_RE.finditer(line):
        try:
            cents = abs(parse_amount(m.group(1)))
        except ValidationError:
            continue
        out.append((base + m.start(1), base + m.end(1), cents, m.group(1)))
    return out


def vat_fits(net: int, vat: int, rate: float) -> bool:
    return abs(round(net * rate / 100) - vat) <= max(2, round(net * 0.0005))


def plausible_rate(net: int, vat: int) -> float | None:
    if net <= 0 or vat < 0:
        return None
    for r in VAT_RATES:
        if vat_fits(net, vat, r):
            return r
    return None


def _fmt_rate(rate: float) -> str:
    return str(int(rate)) if float(rate).is_integer() else str(rate)


class _Collector:
    def __init__(self, text: str, extra: ExtraVocab | None = None) -> None:
        self.text = text
        self.extra = extra
        self.cands: list[Cand] = []
        self.lines: list[tuple[int, str]] = []
        pos = 0
        for raw in text.split("\n"):
            self.lines.append((pos, raw))
            pos += len(raw) + 1

    def add(self, kind: str, amount: tuple[int, int, int, str], strength: float, line: int, rate: str | None = None,
            combined: bool = False) -> None:
        s, e, cents, raw = amount
        self.cands.append(Cand(kind, cents, (s, e), raw, strength, line, rate, combined))

    # -- line based ---------------------------------------------------------------------------------------------
    def scan(self) -> None:
        pending_labels: list[tuple[int, str, float, str | None]] = []  # label-only lines waiting for amounts below
        for idx, (base, line) in enumerate(self.lines):
            stripped = line.strip()
            if not stripped:
                continue
            amounts = _amounts_in(line, base)
            if not amounts:
                if self._header_row(idx, stripped):
                    pending_labels = []
                    continue
                lab = classify_amount_label(stripped, self.extra)
                if lab:
                    pending_labels.append((idx, *lab))
                    continue
                pending_labels = []
                continue
            first_start = amounts[0][0] - base
            label = line[:first_start]
            if not label.strip(" \t:.€$£*-–|") or len(label.strip()) <= 1:
                # a row of bare amounts: belongs to the labels above (stacked columns) or to a header row
                if pending_labels and len(amounts) >= 1:
                    self._pair_stacked(pending_labels, idx, amounts)
                    pending_labels = []
                    continue
                continue
            pending_labels = []
            lab = classify_amount_label(label, self.extra)
            if lab is None:
                continue
            self._labelled_line(idx, lab, amounts)
        # labels at the very end are ignored (no amounts followed)

    def _pair_stacked(self, labels: list[tuple[int, str, float, str | None]], idx: int,
                      first_row: tuple[int, int, int, str] | list) -> None:
        """Label-only lines followed by lines that contain only amounts (PDF text layers of tables)."""
        amounts: list[tuple[int, int, int, str]] = []
        j = idx
        while j < len(self.lines):
            base, line = self.lines[j]
            if not line.strip():
                j += 1
                continue
            found = _amounts_in(line, base)
            if len(found) != 1 or not _ONLY_AMOUNT.fullmatch(line.replace(found[0][3], "#", 1)):
                break
            amounts.append(found[0])
            j += 1
        if len(amounts) < len(labels):
            # a single row of several amounts under a row of labels (rare): map in order
            row = first_row if isinstance(first_row, list) else [first_row]
            if len(row) == len(labels):
                amounts = list(row)
            else:
                return
        for (lidx, kind, strength, rate), amount in zip(labels, amounts, strict=False):
            self.add(kind, amount, min(strength, 2.5), lidx, rate)

    def _labelled_line(self, idx: int, lab: tuple[str, float, str | None], amounts: list) -> None:
        kind, strength, rate = lab
        if len(amounts) == 1:
            self.add(kind, amounts[0], strength, idx, rate)
            return
        vals = [a[2] for a in amounts]
        # Gesamt 100,00 19,00 119,00  /  Summe netto MwSt brutto in one row
        for i in range(len(amounts) - 2):
            a, b, c = vals[i : i + 3]
            if a + b == c and plausible_rate(a, b) is not None:
                self.add("net", amounts[i], 3.0, idx, None, True)
                self.add("vat", amounts[i + 1], 3.0, idx, _fmt_rate(plausible_rate(a, b) or 0), True)
                self.add("gross", amounts[i + 2], 3.0, idx, None, True)
                return
        for i in range(len(amounts) - 1):
            a, b = vals[i : i + 2]
            if kind in ("gross", "net") and b > a and plausible_rate(a, b - a) not in (None, 0.0):
                self.add("net", amounts[i], 2.5, idx, None, True)
                self.add("gross", amounts[i + 1], 2.5, idx, None, True)
                return
            if kind == "vat" and plausible_rate(a, b) not in (None, 0.0):
                self.add("net", amounts[i], 2.5, idx, rate, True)
                self.add("vat", amounts[i + 1], 3.0, idx, rate, True)
                return
        self.add(kind, amounts[-1] if kind == "gross" else amounts[0], strength * 0.8, idx, rate)

    # -- table header over a row of numbers -------------------------------------------------------------------------
    def _header_row(self, idx: int, stripped: str) -> bool:
        cells = [c for c in _CELL_SPLIT.split(stripped) if c.strip()]
        if len(cells) < 2:
            return False
        labelled = []
        for pos, cell in enumerate(cells):
            lab = classify_amount_label(cell, self.extra)
            labelled.append((pos, lab))
        kinds = [lab[0] for _p, lab in labelled if lab]
        if len(set(kinds)) < 2:
            return False
        nxt = idx + 1
        while nxt < len(self.lines) and not self.lines[nxt][1].strip():
            nxt += 1
        if nxt >= len(self.lines):
            return False
        base, line = self.lines[nxt]
        amounts = _amounts_in(line, base)
        if len(amounts) == len(cells):
            mapping = [(lab, amounts[pos]) for pos, lab in labelled if lab]
        elif len(amounts) == len(kinds):
            mapping = list(zip([lab for _p, lab in labelled if lab], amounts, strict=True))
        else:
            return False
        for lab, amount in mapping:
            self.add(lab[0], amount, 2.5, idx, lab[2])
        return True


def _sum_option(cands: list[Cand], kind: str) -> Cand | None:
    distinct: dict[int, Cand] = {}
    for c in cands:
        distinct.setdefault(c.line, c)
    chosen = list(distinct.values())
    if len(chosen) < 2:
        return None
    first = chosen[0]
    return Cand(kind, sum(c.cents for c in chosen), first.span, first.raw, min(c.strength for c in chosen) - 0.5,
                max(c.line for c in chosen), first.rate, combined=True)


def _dedupe(cands: list[Cand]) -> list[Cand]:
    seen: set[tuple[str, int]] = set()
    out = []
    for c in cands:
        key = (c.kind, c.cents)
        if key not in seen:
            seen.add(key)
            out.append(c)
    return out


def _score(g: Cand | None, n: Cand | None, v: Cand | None) -> float:
    score = sum(x.strength for x in (g, n, v) if x)
    score -= sum(1.0 for x in (g, n, v) if x and x.combined and x.strength < 3.0)
    if g and n and v:
        if abs(n.cents + v.cents - g.cents) <= 1:
            score += 100
    elif g and n and g.cents > n.cents and plausible_rate(n.cents, g.cents - n.cents) is not None:
        score += 2
    elif n and v and plausible_rate(n.cents, v.cents) is not None:
        score += 2
    elif g and v and g.cents > v.cents and plausible_rate(g.cents - v.cents, v.cents) is not None:
        score += 2
    if g:
        score += g.line * 0.001
    return score


def _triple(text_amounts: list[tuple[int, int, int, str]]) -> tuple[int, int, int] | None:
    """Last (net, vat, gross) in the document order with net + vat = gross and a plausible VAT rate."""
    best = None
    for c in range(len(text_amounts)):
        for b in range(max(0, c - 12), c):
            for a in range(max(0, c - 12), c):
                if a == b:
                    continue
                na, vb, gc = text_amounts[a][2], text_amounts[b][2], text_amounts[c][2]
                if na > 0 and vb > 0 and abs(na + vb - gc) <= 1 and plausible_rate(na, vb) not in (None, 0.0):
                    best = (a, b, c)
    return best


def extract_invoice_amounts(text: str, extra: ExtraVocab | None = None) -> InvoiceAmounts:
    col = _Collector(text, extra)
    col.scan()
    cands = _dedupe(col.cands)
    by = {k: [c for c in cands if c.kind == k] for k in ("net", "vat", "gross")}
    options: dict[str, list[Cand | None]] = {}
    for kind in ("net", "vat", "gross"):
        ranked = sorted(by[kind], key=lambda c: (-c.strength, -c.line))[:_MAX_OPTIONS]
        extra = _sum_option(by[kind], kind) if kind in ("net", "vat") else None
        options[kind] = [*ranked, *([extra] if extra else []), None]
    best, best_score = (None, None, None), -1e9
    for g, n, v in product(options["gross"], options["net"], options["vat"]):
        sc = _score(g, n, v)
        if sc > best_score:
            best, best_score = (g, n, v), sc
    g, n, v = best
    res = InvoiceAmounts()
    consistent = bool(g and n and v and abs(n.cents + v.cents - g.cents) <= 1)

    if not consistent:
        # the text may contain a consistent net/vat/gross triple that no label announced
        all_amounts = _amounts_in(text, 0)
        tri = _triple(all_amounts)
        if tri is not None:
            a, b, c = (all_amounts[i] for i in tri)
            gross_ok = g is None or abs(g.cents - c[2]) <= 1 or not (n and v)
            if gross_ok:
                n = Cand("net", a[2], (a[0], a[1]), a[3], 2.0, 0)
                v = Cand("vat", b[2], (b[0], b[1]), b[3], 2.0, 0, _fmt_rate(plausible_rate(a[2], b[2]) or 0))
                g = Cand("gross", c[2], (c[0], c[1]), c[3], 2.0, 0)
                consistent = True

    def fv(c: Cand, conf: float) -> FieldValue:
        return FieldValue(c.cents, conf, c.span, c.raw)

    conf = 0.92 if consistent else 0.6
    if g:
        res.gross = fv(g, conf if g.strength >= 2 else min(conf, 0.78))
    if n:
        res.net = fv(n, conf if n.strength >= 2 else min(conf, 0.78))
    if v:
        res.vat = fv(v, conf)
    # derive what is missing
    if g and n and not v and g.cents >= n.cents:
        diff = g.cents - n.cents
        res.vat = FieldValue(diff, 0.7 if plausible_rate(n.cents, diff) is not None else 0.45, g.span, g.raw)
        res.derived.add("vat")
    elif g and v and not n and g.cents >= v.cents:
        net = g.cents - v.cents
        res.net = FieldValue(net, 0.7 if plausible_rate(net, v.cents) is not None else 0.45, g.span, g.raw)
        res.derived.add("net")
    elif n and v and not g:
        res.gross = FieldValue(n.cents + v.cents, 0.7, v.span, v.raw)
        res.derived.add("gross")
    elif g and not n and not v:
        rate = next((float(c.rate) for c in by["vat"] if c.rate), None)
        if rate is None:
            m = re.search(r"(\d{1,2}(?:[.,]\d+)?)\s*%\s*(?:mwst|ust|vat|mehrwertsteuer|umsatzsteuer|tva|iva|btw)|"
                          r"(?:mwst|ust|vat|mehrwertsteuer|umsatzsteuer|tva|iva|btw)[^\n\d]{0,12}(\d{1,2}(?:[.,]\d+)?)\s*%",
                          text, re.I)
            if m:
                rate = float((m.group(1) or m.group(2)).replace(",", "."))
        if rate is not None and rate in VAT_RATES:
            net = round(g.cents / (1 + rate / 100))
            res.net = FieldValue(net, 0.55, g.span, g.raw)
            res.vat = FieldValue(g.cents - net, 0.55, g.span, g.raw)
            res.derived.update({"net", "vat"})
    res.consistent = bool(res.net and res.vat and res.gross and abs(res.net.value + res.vat.value - res.gross.value) <= 1)
    # VAT rate: printed in the VAT label, else derived from the amounts
    if v and v.rate:
        res.rate = v.rate
    elif res.net and res.vat and res.net.value > 0:
        r = plausible_rate(res.net.value, res.vat.value)
        res.rate = _fmt_rate(r) if r is not None else None
    return res
