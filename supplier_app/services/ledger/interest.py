"""Late-payment interest (Verzugszinsen): base rate + margin, actual/365, on open principal only."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal

from supplier_app.errors import LedgerError


@dataclass(frozen=True)
class RatePoint:
    """Base rate (percent p.a.) valid from a date."""

    valid_from: date
    base_rate: Decimal


@dataclass(frozen=True)
class InterestSegment:
    start: date  # first day (inclusive)
    end: date  # last day (inclusive)
    days: int
    principal_cents: int
    annual_rate: Decimal
    amount: Decimal  # unrounded, in cents


@dataclass(frozen=True)
class InterestResult:
    total_cents: int
    segments: list[InterestSegment]

    @property
    def days(self) -> int:
        return sum(s.days for s in self.segments)


def base_rate_on(day: date, rates: Sequence[RatePoint]) -> Decimal:
    """Base rate valid on ``day``; before the first known date the first rate is used."""
    if not rates:
        raise LedgerError("Es ist kein Basiszinssatz hinterlegt (Einstellungen > Zinssätze).")
    ordered = sorted(rates, key=lambda r: r.valid_from)
    current = ordered[0].base_rate
    for point in ordered:
        if point.valid_from <= day:
            current = point.base_rate
        else:
            break
    return current


def annual_rate(day: date, rates: Sequence[RatePoint], margin_pp: Decimal) -> Decimal:
    return base_rate_on(day, rates) + margin_pp


def calculate_interest(
    principal_cents: int,
    due_date: date,
    until: date,
    rates: Sequence[RatePoint],
    margin_pp: Decimal,
    principal_payments: Sequence[tuple[date, int]] = (),
) -> InterestResult:
    """Interest for every day ``d`` with ``due_date < d <= until``.

    The principal of day ``d`` is the original principal minus payments dated before ``d``.
    The sum is rounded once (ROUND_HALF_UP) to cents. Only the principal bears interest.
    """
    segments: list[InterestSegment] = []
    total = Decimal(0)
    payments = sorted((d, a) for d, a in principal_payments if a > 0)
    day = due_date + timedelta(days=1)
    seg_start: date | None = None
    seg_principal = 0
    seg_rate = Decimal(0)
    seg_days = 0

    def flush(last_day: date) -> None:
        nonlocal total
        if seg_start is None or seg_days == 0:
            return
        amount = Decimal(seg_principal) * seg_rate / Decimal(100) * seg_days / Decimal(365)
        total += amount
        segments.append(InterestSegment(seg_start, last_day, seg_days, seg_principal, seg_rate, amount))

    while day <= until:
        paid_before = sum(a for d, a in payments if d < day)
        principal = max(0, principal_cents - paid_before)
        rate = annual_rate(day, rates, margin_pp)
        if principal <= 0:
            flush(day - timedelta(days=1))
            seg_start, seg_days = None, 0
            break
        if seg_start is not None and (principal != seg_principal or rate != seg_rate):
            flush(day - timedelta(days=1))
            seg_start, seg_days = None, 0
        if seg_start is None:
            seg_start, seg_principal, seg_rate = day, principal, rate
        seg_days += 1
        day += timedelta(days=1)
    else:
        flush(until)
    return InterestResult(int(total.quantize(Decimal(1), rounding=ROUND_HALF_UP)), segments)
