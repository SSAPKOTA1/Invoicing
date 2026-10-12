"""Payment allocation (par. 367 BGB order by default)."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date

from supplier_app.errors import LedgerError
from supplier_app.models.enums import AllocationComponent as C
from supplier_app.models.enums import AllocationRule
from supplier_app.util.money import format_cents

_ORDER = (C.COSTS, C.INTEREST, C.PRINCIPAL)


@dataclass(frozen=True)
class OpenItem:
    """Open amounts of one invoice, split by component."""

    invoice_id: int
    due_date: date | None
    invoice_date: date
    open_costs_cents: int
    open_interest_cents: int
    open_principal_cents: int

    def open_of(self, component: C) -> int:
        value = {
            C.COSTS: self.open_costs_cents,
            C.INTEREST: self.open_interest_cents,
            C.PRINCIPAL: self.open_principal_cents,
        }[component]
        return max(0, value)

    @property
    def sort_key(self) -> tuple[date, date, int]:
        return (self.due_date or self.invoice_date, self.invoice_date, self.invoice_id)


@dataclass(frozen=True)
class Allocation:
    invoice_id: int
    component: C
    amount_cents: int


@dataclass(frozen=True)
class AllocationResult:
    allocations: list[Allocation]
    unallocated_cents: int

    def by_invoice(self) -> dict[int, int]:
        out: dict[int, int] = {}
        for a in self.allocations:
            out[a.invoice_id] = out.get(a.invoice_id, 0) + a.amount_cents
        return out


def allocate_payment(
    amount_cents: int,
    items: Sequence[OpenItem],
    rule: AllocationRule = AllocationRule.STATUTORY,
    manual: Sequence[tuple[int, C, int]] | None = None,
) -> AllocationResult:
    """Distribute ``amount_cents`` over the given open items.

    * ``STATUTORY``: all costs first, then all interest, then all principal (each stage oldest due first).
    * ``OLDEST_FIRST``: invoice by invoice (oldest due first), costs -> interest -> principal inside each.
    * ``MANUAL``: exactly the given ``(invoice_id, component, amount)`` list.

    What cannot be allocated is returned as ``unallocated_cents`` (credit on account / overpayment).
    """
    if amount_cents <= 0:
        raise LedgerError("Der Zahlungsbetrag muss größer als 0 sein.")
    ordered = sorted(items, key=lambda i: i.sort_key)
    result: list[Allocation] = []
    remaining = amount_cents

    if rule == AllocationRule.MANUAL:
        if manual is None:
            raise LedgerError("Für die manuelle Zuordnung fehlen die Beträge.")
        by_id = {i.invoice_id: i for i in items}
        used: dict[tuple[int, C], int] = {}
        for invoice_id, component, amount in manual:
            if amount < 0:
                raise LedgerError("Zugeordnete Beträge dürfen nicht negativ sein.")
            if invoice_id not in by_id:
                raise LedgerError(f"Rechnung {invoice_id} gehört nicht zu dieser Zahlung.")
            used[(invoice_id, component)] = used.get((invoice_id, component), 0) + amount
        for (invoice_id, component), amount in used.items():
            open_amount = by_id[invoice_id].open_of(component)
            if amount > open_amount:
                raise LedgerError(
                    f"Zuordnung von {format_cents(amount)} übersteigt den offenen Betrag "
                    f"({format_cents(open_amount)}) der Rechnung."
                )
            if amount > 0:
                result.append(Allocation(invoice_id, component, amount))
        total = sum(a.amount_cents for a in result)
        if total > amount_cents:
            raise LedgerError("Die zugeordneten Beträge übersteigen den Zahlungsbetrag.")
        return AllocationResult(result, amount_cents - total)

    def take(item: OpenItem, component: C) -> None:
        nonlocal remaining
        amount = min(remaining, item.open_of(component))
        if amount > 0:
            result.append(Allocation(item.invoice_id, component, amount))
            remaining -= amount

    if rule == AllocationRule.STATUTORY:
        for component in _ORDER:
            for item in ordered:
                take(item, component)
    else:
        for item in ordered:
            for component in _ORDER:
                take(item, component)
    return AllocationResult(result, remaining)
