"""Balances, status derivation and running balances."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date

from supplier_app.models.enums import AllocationComponent, InvoiceStatus
from supplier_app.models.enums import LedgerEntryType as T

from .types import AllocationRow, InvoiceBalance, LedgerLine, RunningRow


def derive_status(balance_cents: int, paid_cents: int, manual: InvoiceStatus | None) -> InvoiceStatus:
    """open -> partially paid -> paid, unless the user marked the invoice disputed or cancelled."""
    if manual in (InvoiceStatus.DISPUTED, InvoiceStatus.CANCELLED):
        return manual
    if balance_cents <= 0:
        return InvoiceStatus.PAID
    return InvoiceStatus.PARTIALLY_PAID if paid_cents > 0 else InvoiceStatus.OPEN


def _empty_status(manual: InvoiceStatus | None) -> InvoiceStatus:
    return manual if manual in (InvoiceStatus.DISPUTED, InvoiceStatus.CANCELLED) else InvoiceStatus.OPEN


def balance_from_sums(
    sums: Mapping[T, int],
    allocations: Mapping[AllocationComponent, int],
    manual: InvoiceStatus | None = None,
) -> InvoiceBalance:
    """Build an :class:`InvoiceBalance` from per-category sums (used by SQL aggregate paths).

    ``sums`` maps the economic entry category to the signed sum of all entries in that category
    (reversals already contained in their original category).
    """
    invoiced = sums.get(T.INVOICE, 0)
    credits = -sums.get(T.CREDIT_NOTE, 0)
    fees = sums.get(T.DUNNING_FEE, 0)
    interest = sums.get(T.LATE_INTEREST, 0)
    flat = sums.get(T.LATE_PAYMENT_FLAT_FEE, 0)
    collection = sums.get(T.COLLECTION_COST, 0)
    adjustments = sums.get(T.ADJUSTMENT, 0)
    write_offs = -sums.get(T.WRITE_OFF, 0)
    paid = -sums.get(T.PAYMENT, 0)
    balance = invoiced - credits + fees + interest + flat + collection + adjustments - write_offs - paid
    open_costs = fees + flat + collection - allocations.get(AllocationComponent.COSTS, 0)
    open_interest = interest - allocations.get(AllocationComponent.INTEREST, 0)
    open_principal = (
        invoiced - credits + adjustments - write_offs - allocations.get(AllocationComponent.PRINCIPAL, 0)
    )
    return InvoiceBalance(
        invoiced_cents=invoiced, credits_cents=credits, fees_cents=fees, interest_cents=interest,
        flat_fee_cents=flat, collection_cents=collection, adjustments_cents=adjustments,
        write_offs_cents=write_offs, paid_cents=paid, balance_cents=balance, open_costs_cents=open_costs,
        open_interest_cents=open_interest, open_principal_cents=open_principal,
        status=derive_status(balance, paid, manual) if any(sums.values()) else _empty_status(manual),
    )


def summarize_invoice(
    lines: Sequence[LedgerLine],
    allocations: Sequence[AllocationRow],
    manual_status: InvoiceStatus | None = None,
    as_of: date | None = None,
) -> InvoiceBalance:
    """Derive the balance of one invoice from its ledger lines (optionally as of a date)."""
    sums: dict[T, int] = {}
    for line in lines:
        if as_of is not None and line.entry_date > as_of:
            continue
        sums[line.category] = sums.get(line.category, 0) + line.amount_cents
    alloc: dict[AllocationComponent, int] = {}
    for row in allocations:
        if as_of is not None and row.payment_date > as_of:
            continue
        alloc[row.component] = alloc.get(row.component, 0) + row.amount_cents
    return balance_from_sums(sums, alloc, manual_status)


def running_balance(lines: Sequence[LedgerLine], opening_cents: int = 0) -> list[RunningRow]:
    """Chronological rows (date, then id) with the cumulative balance after each entry."""
    ordered = sorted(lines, key=lambda x: (x.entry_date, x.entry_id if x.entry_id is not None else 1 << 60))
    rows: list[RunningRow] = []
    total = opening_cents
    for line in ordered:
        total += line.amount_cents
        rows.append(RunningRow(line, total))
    return rows
