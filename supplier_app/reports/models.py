"""Report data model shared by the builders and exporters."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from supplier_app.i18n import tx


@dataclass
class ReportTable:
    """A table with display strings and raw values (cents are ints, dates are ``date``)."""

    title: str
    subtitle: str
    columns: list[str]
    rows: list[list[str]]
    raw_rows: list[list[Any]]
    money_columns: set[int] = field(default_factory=set)
    totals: list[Any] | None = None  # raw totals row aligned with columns (None = no value)
    totals_label: str = "Summe"
    extra: list[ReportTable] = field(default_factory=list)  # e.g. the aging summary of open items

    def __post_init__(self) -> None:
        self.title = tx(self.title)
        self.subtitle = tx(self.subtitle)
        self.columns = [tx(c) for c in self.columns]
        self.totals_label = tx(self.totals_label)
        self.rows = [[tx(c) if isinstance(c, str) else c for c in row] for row in self.rows]
        self.raw_rows = [[tx(c) if isinstance(c, str) else c for c in row] for row in self.raw_rows]
        if self.totals is not None:
            self.totals = [tx(t) if isinstance(t, str) else t for t in self.totals]

    def column_total(self, index: int) -> int:
        return sum(int(r[index]) for r in self.raw_rows if isinstance(r[index], int))
