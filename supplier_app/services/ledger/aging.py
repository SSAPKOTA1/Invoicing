"""Aging buckets by days overdue."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date

AGING_BUCKETS: tuple[str, ...] = ("not_due", "1-30", "31-60", "61-90", "90+")


def aging_bucket(due_date: date | None, as_of: date) -> str:
    """Bucket for an open item: not due, or 1-30 / 31-60 / 61-90 / 90+ days overdue."""
    if due_date is None:
        return "not_due"
    overdue = (as_of - due_date).days
    if overdue <= 0:
        return "not_due"
    if overdue <= 30:
        return "1-30"
    if overdue <= 60:
        return "31-60"
    if overdue <= 90:
        return "61-90"
    return "90+"


def aging_totals(items: Iterable[tuple[date | None, int]], as_of: date) -> dict[str, int]:
    """Sum positive open balances per bucket (always all buckets, in order)."""
    totals = dict.fromkeys(AGING_BUCKETS, 0)
    for due, balance in items:
        if balance > 0:
            totals[aging_bucket(due, as_of)] += balance
    return totals
