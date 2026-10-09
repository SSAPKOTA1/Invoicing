"""DTOs of the dashboard (read-only views of ledger data)."""

from __future__ import annotations

import calendar
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any


@dataclass(frozen=True)
class DrillTarget:
    """What a click on a card / chart segment / row opens: a filtered list."""

    kind: str  # see DashboardService.drilldown
    param: str = ""
    label: str = ""


@dataclass(frozen=True)
class DashboardFilter:
    date_from: date
    date_to: date
    as_of: date
    supplier_id: int | None = None
    period: str = "month"

    @staticmethod
    def for_period(period: str, today: date, supplier_id: int | None = None, as_of: date | None = None,
                   custom: tuple[date, date] | None = None) -> DashboardFilter:
        if period == "custom" and custom:
            start, end = custom
        elif period == "year":
            start, end = date(today.year, 1, 1), date(today.year, 12, 31)
        elif period == "quarter":
            q0 = 3 * ((today.month - 1) // 3) + 1
            start = date(today.year, q0, 1)
            end_month = q0 + 2
            end = date(today.year, end_month, calendar.monthrange(today.year, end_month)[1])
        else:
            period = "month"
            start = date(today.year, today.month, 1)
            end = date(today.year, today.month, calendar.monthrange(today.year, today.month)[1])
        return DashboardFilter(start, end, as_of if as_of is not None else today, supplier_id, period)

    def previous(self) -> DashboardFilter:
        """The period of the same length directly before this one."""
        length = (self.date_to - self.date_from).days + 1
        end = self.date_from - timedelta(days=1)
        start = end - timedelta(days=length - 1)
        if self.period in ("month", "quarter", "year"):
            if self.period == "month":
                start = date(end.year, end.month, 1)
            elif self.period == "quarter":
                q0 = 3 * ((end.month - 1) // 3) + 1
                start = date(end.year, q0, 1)
            else:
                start = date(end.year, 1, 1)
        return DashboardFilter(start, end, end, self.supplier_id, self.period)


@dataclass
class Kpi:
    key: str
    value: int  # cents for money KPIs, count otherwise
    is_money: bool
    previous: int | None = None
    drill: DrillTarget | None = None
    higher_is_worse: bool = True

    @property
    def change(self) -> int | None:
        return None if self.previous is None else self.value - self.previous


@dataclass
class AttentionItem:
    title: str
    subtitle: str = ""
    severity: str = "info"  # info | warn | critical
    target: DrillTarget | None = None
    open_kind: str = ""  # 'invoice' | 'document' | 'case' | 'supplier'
    open_id: int | None = None
    days_left: int | None = None


@dataclass
class ActivityItem:
    when: str
    text: str
    open_kind: str = ""
    open_id: int | None = None


@dataclass
class DashboardData:
    filter: DashboardFilter
    kpis: dict[str, Kpi] = field(default_factory=dict)
    aging: dict[str, int] = field(default_factory=dict)
    top_suppliers: list[tuple[int, str, int]] = field(default_factory=list)
    trend: list[tuple[str, int, int, int]] = field(default_factory=list)  # month, invoiced, paid, balance
    dunning_levels: dict[int, int] = field(default_factory=dict)
    charges_by_type: dict[str, int] = field(default_factory=dict)
    forecast: list[tuple[str, int]] = field(default_factory=list)
    attention: dict[str, list[AttentionItem]] = field(default_factory=dict)
    activity: list[ActivityItem] = field(default_factory=list)
    empty: bool = False


@dataclass
class DrillRow:
    cells: list[str]
    amount_cents: int = 0
    open_kind: str = ""
    open_id: int | None = None
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class DrillResult:
    title: str
    columns: list[str]
    rows: list[DrillRow]
    total_cents: int | None  # None for count lists
    count: int
