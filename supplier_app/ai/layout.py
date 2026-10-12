"""Label/value pairs from table layouts: a header row over a value row, and stacked label/value columns.

PDF text layers and OCR often turn ``Rechnungsnummer: 1234`` into two aligned rows or two blocks of lines::

    Rechnungsnummer   Rechnungsdatum        Rechnungsnummer
    R-2024-77         12.03.2024            Rechnungsdatum
                                            R-2024-77
                                            12.03.2024
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_CELL_SPLIT = re.compile(r"\t+|\s{2,}|\s\|\s")
_GENERIC_LABEL = re.compile(r"^[^\W\d_][^\d]{1,38}?\s*:?$")
_HAS_DIGIT = re.compile(r"\d")


@dataclass(frozen=True)
class Pair:
    label: str
    value: str
    start: int  # span of the value in the text
    end: int


def _cells(line: str, base: int) -> list[tuple[str, int, int]]:
    out = []
    pos = 0
    for part in _CELL_SPLIT.split(line):
        idx = line.find(part, pos) if part else pos
        if part.strip():
            lead = len(part) - len(part.lstrip())
            out.append((part.strip(), base + idx + lead, base + idx + lead + len(part.strip())))
        pos = idx + len(part)
    return out


def header_value_pairs(text: str) -> list[Pair]:
    """All (label cell, value cell) pairs of header rows followed by a row of values, and of stacked blocks."""
    lines: list[tuple[int, str]] = []
    pos = 0
    for raw in text.split("\n"):
        lines.append((pos, raw))
        pos += len(raw) + 1
    pairs: list[Pair] = []
    n = len(lines)
    for i, (base, line) in enumerate(lines):
        stripped = line.strip()
        if not stripped:
            continue
        cells = _cells(line, base)
        if len(cells) >= 2 and not any(_HAS_DIGIT.search(c[0]) for c in cells):
            j = i + 1
            while j < n and not lines[j][1].strip():
                j += 1
            if j < n:
                vcells = _cells(lines[j][1], lines[j][0])
                if len(vcells) == len(cells) and any(_HAS_DIGIT.search(c[0]) for c in vcells):
                    pairs.extend(Pair(lc[0], vc[0], vc[1], vc[2]) for lc, vc in zip(cells, vcells, strict=True))
    # alternating: "Rechnungsnummer" / "RE-2024-881" / "Rechnungsdatum" / "15.03.2024" (PDF text layers put each cell on a line)
    for i in range(n - 1):
        b1, l1 = lines[i]
        s1 = l1.strip()
        if not s1 or _HAS_DIGIT.search(s1) or not _GENERIC_LABEL.match(s1):
            continue
        j = i + 1
        while j < n and not lines[j][1].strip():
            j += 1
        if j >= n:
            continue
        b2, l2 = lines[j]
        s2 = l2.strip()
        if _HAS_DIGIT.search(s2) and len(s2) <= 40 and not _CELL_SPLIT.search(s2):
            start = b2 + l2.find(s2)
            pairs.append(Pair(s1.rstrip(":").strip(), s2, start, start + len(s2)))
    # stacked: k label-like lines, then k value lines
    i = 0
    while i < n:
        base, line = lines[i]
        if not line.strip() or _HAS_DIGIT.search(line) or not _GENERIC_LABEL.match(line.strip()):
            i += 1
            continue
        run = [i]
        j = i + 1
        while j < n:
            b2, l2 = lines[j]
            if not l2.strip():
                j += 1
                continue
            if not _HAS_DIGIT.search(l2) and _GENERIC_LABEL.match(l2.strip()):
                run.append(j)
                j += 1
                continue
            break
        if len(run) >= 2:
            values = []
            k = j
            while k < n and len(values) < len(run):
                b3, l3 = lines[k]
                if l3.strip() and _HAS_DIGIT.search(l3):
                    values.append((b3, l3))
                elif l3.strip():
                    break
                k += 1
            if values:
                # the title above the labels ("Rechnung") is part of the run: align labels and values from the end
                for li, (vb, vl) in zip(run[len(run) - len(values):], values, strict=True):
                    v = vl.strip()
                    start = vb + vl.find(v)
                    pairs.append(Pair(lines[li][1].strip().rstrip(":").strip(), v, start, start + len(v)))
        i = max(j, i + 1)
    return pairs
