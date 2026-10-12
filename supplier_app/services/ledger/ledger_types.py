"""Value types of the pure ledger engine (no database, no Qt)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from supplier_app.models.enums import AllocationComponent, InvoiceStatus, LedgerEntryType


@dataclass(frozen=True)
class LedgerLine:
    """One signed ledger entry as seen by the engine.

    ``category`` is the economic type: equal to ``entry_type`` except for reversals, where it is
    the type of the reversed entry.
    """

    entry_id: int | None
    entry_date: date
    invoice_id: int | None
    entry_type: LedgerEntryType
    category: LedgerEntryType
    amount_cents: int
    notice_id: int | None = None
    payment_id: int | None = None
    reverses_id: int | None = None
    supplier_id: int = 0


@dataclass(frozen=True)
class AllocationRow:
    """Part of a payment applied to one component of an invoice."""

    payment_date: date
    component: AllocationComponent
    amount_cents: int


@dataclass(frozen=True)
class InvoiceBalance:
    """Derived state of one invoice. Never stored as an editable field."""

    invoiced_cents: int
    credits_cents: int
    fees_cents: int
    interest_cents: int
    flat_fee_cents: int
    collection_cents: int
    adjustments_cents: int
    write_offs_cents: int
    paid_cents: int
    balance_cents: int
    open_costs_cents: int
    open_interest_cents: int
    open_principal_cents: int
    status: InvoiceStatus

    @property
    def charges_cents(self) -> int:
        """Fees + interest + flat fee + collection costs."""
        return self.fees_cents + self.interest_cents + self.flat_fee_cents + self.collection_cents

    @property
    def costs_cents(self) -> int:
        """Charges that count as 'costs' in the statutory allocation order."""
        return self.fees_cents + self.flat_fee_cents + self.collection_cents

    @property
    def credit_balance_cents(self) -> int:
        """Overpayment shown as credit."""
        return max(0, -self.balance_cents)

    @property
    def open_cents(self) -> int:
        """Amount still owed (never negative)."""
        return max(0, self.balance_cents)


@dataclass(frozen=True)
class RunningRow:
    line: LedgerLine
    balance_cents: int
