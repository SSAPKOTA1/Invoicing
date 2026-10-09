"""Ledger queries and postings: the only place that turns repository data into engine input."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date

from supplier_app.errors import LedgerError, NotFoundError
from supplier_app.models.entities import Invoice, LedgerEntry
from supplier_app.models.enums import AllocationComponent, InvoiceStatus, LedgerEntryType
from supplier_app.repositories.interfaces import Repositories
from supplier_app.services.base import ServiceBase, today
from supplier_app.services.ledger import (
    AllocationRow,
    InterestResult,
    InvoiceBalance,
    LedgerLine,
    NoticeReconciliation,
    OpenItem,
    RunningRow,
    aging_totals,
    balance_from_sums,
    calculate_interest,
    reconcile_notice,
    running_balance,
    summarize_invoice,
)
from supplier_app.services.ledger import NoticeClaim as EngineClaim
from supplier_app.services.settings_service import SettingsService
from supplier_app.util.dates import format_date


def to_line(e: LedgerEntry) -> LedgerLine:
    return LedgerLine(
        entry_id=e.id, entry_date=e.entry_date, invoice_id=e.invoice_id, entry_type=e.entry_type,
        category=e.category_type, amount_cents=e.amount_cents, notice_id=e.notice_id, payment_id=e.payment_id,
        reverses_id=e.reverses_entry_id, supplier_id=e.supplier_id,
    )


@dataclass(frozen=True)
class InvoiceState:
    invoice: Invoice
    balance: InvoiceBalance

    @property
    def overdue_days(self) -> int:
        if self.invoice.due_date is None or self.balance.balance_cents <= 0:
            return 0
        return max(0, (today() - self.invoice.due_date).days)


@dataclass(frozen=True)
class SupplierBalance:
    supplier_id: int
    invoices_cents: int  # sum of invoice balances (can contain overpaid invoices as negatives)
    unapplied_cents: int  # negative = credit on account not yet assigned to an invoice
    total_cents: int


@dataclass(frozen=True)
class StatementRow:
    entry: LedgerEntry
    invoice_number: str
    running_cents: int
    reversed: bool


@dataclass(frozen=True)
class SupplierStatement:
    supplier_id: int
    date_from: date | None
    date_to: date | None
    opening_cents: int
    rows: list[StatementRow]
    closing_cents: int


class LedgerService(ServiceBase):
    """Balances, statements, postings and reversals."""

    def __init__(self, repos: Repositories, settings: SettingsService) -> None:
        super().__init__(repos)
        self.settings = settings

    # -- engine input ----------------------------------------------------------
    def lines(self, **filters: object) -> list[LedgerLine]:
        return [to_line(e) for e in self.repos.ledger.list(**filters)]  # type: ignore[arg-type]

    def allocation_rows(self, invoice_id: int) -> list[AllocationRow]:
        dates: dict[int, date] = {}
        rows: list[AllocationRow] = []
        for a in self.repos.payments.allocations(invoice_id=invoice_id):
            if a.payment_id not in dates:
                payment = self.repos.payments.get(a.payment_id)
                assert payment is not None
                dates[a.payment_id] = payment.payment_date
            rows.append(AllocationRow(dates[a.payment_id], a.component, a.amount_cents))
        return rows

    def _manual_status(self, invoice: Invoice) -> InvoiceStatus | None:
        return invoice.status if invoice.status in (InvoiceStatus.DISPUTED, InvoiceStatus.CANCELLED) else None

    def invoice_balance(self, invoice_id: int, as_of: date | None = None) -> InvoiceBalance:
        invoice = self.repos.invoices.get(invoice_id)
        if invoice is None:
            raise NotFoundError("Rechnung nicht gefunden.")
        return summarize_invoice(
            self.lines(invoice_id=invoice_id), self.allocation_rows(invoice_id), self._manual_status(invoice), as_of
        )

    def invoice_states(
        self, as_of: date | None = None, supplier_id: int | None = None, invoices: list[Invoice] | None = None
    ) -> list[InvoiceState]:
        """Balances of all invoices that have entries up to ``as_of`` (set-based, fast)."""
        sums: dict[int, dict[LedgerEntryType, int]] = defaultdict(dict)
        for invoice_id, _sid, ctype, total in self.repos.ledger.sums_by_invoice(as_of=as_of, supplier_id=supplier_id):
            sums[invoice_id][LedgerEntryType(ctype)] = total
        alloc: dict[int, dict[AllocationComponent, int]] = defaultdict(dict)
        for invoice_id, comp, total in self.repos.payments.allocation_sums(as_of=as_of):
            alloc[invoice_id][AllocationComponent(comp)] = total
        states: list[InvoiceState] = []
        for invoice in invoices if invoices is not None else self.repos.invoices.list(supplier_id=supplier_id):
            assert invoice.id is not None
            if invoice.id not in sums:
                continue
            bal = balance_from_sums(sums[invoice.id], alloc.get(invoice.id, {}), self._manual_status(invoice))
            states.append(InvoiceState(invoice, bal))
        return states

    def supplier_balance(self, supplier_id: int, as_of: date | None = None) -> SupplierBalance:
        invoices = sum(s.balance.balance_cents for s in self.invoice_states(as_of, supplier_id))
        unapplied = self.repos.ledger.unapplied_by_supplier(as_of=as_of).get(supplier_id, 0)
        return SupplierBalance(supplier_id, invoices, unapplied, invoices + unapplied)

    def supplier_balances(self, as_of: date | None = None) -> dict[int, SupplierBalance]:
        per: dict[int, int] = defaultdict(int)
        for s in self.invoice_states(as_of):
            per[s.invoice.supplier_id] += s.balance.balance_cents
        unapplied = self.repos.ledger.unapplied_by_supplier(as_of=as_of)
        return {
            sid: SupplierBalance(sid, per.get(sid, 0), unapplied.get(sid, 0), per.get(sid, 0) + unapplied.get(sid, 0))
            for sid in set(per) | set(unapplied)
        }

    def supplier_statement(
        self, supplier_id: int, date_from: date | None = None, date_to: date | None = None
    ) -> SupplierStatement:
        """Kontoblatt: all entries of the period with running balance."""
        all_entries = self.repos.ledger.list(supplier_id=supplier_id, date_to=date_to)
        opening = sum(e.amount_cents for e in all_entries if date_from and e.entry_date < date_from)
        period = [e for e in all_entries if not date_from or e.entry_date >= date_from]
        numbers = {i.id: i.invoice_number for i in self.repos.invoices.list(supplier_id=supplier_id)}
        reversed_ids = {e.reverses_entry_id for e in all_entries if e.reverses_entry_id}
        by_id = {e.id: e for e in period}
        running = running_balance([to_line(e) for e in period], opening)
        rows = [
            StatementRow(by_id[r.line.entry_id], numbers.get(r.line.invoice_id, ""), r.balance_cents,
                         r.line.entry_id in reversed_ids)
            for r in running
        ]
        closing = rows[-1].running_cents if rows else opening
        return SupplierStatement(supplier_id, date_from, date_to, opening, rows, closing)

    def invoice_running(self, invoice_id: int) -> list[RunningRow]:
        return running_balance(self.lines(invoice_id=invoice_id))

    def open_item(self, invoice_id: int) -> OpenItem:
        invoice = self.repos.invoices.get(invoice_id)
        if invoice is None:
            raise NotFoundError("Rechnung nicht gefunden.")
        bal = self.invoice_balance(invoice_id)
        return OpenItem(invoice_id, invoice.due_date, invoice.invoice_date, bal.open_costs_cents,
                        bal.open_interest_cents, bal.open_principal_cents)

    def aging(self, as_of: date | None = None, supplier_id: int | None = None) -> dict[str, int]:
        day = as_of or today()
        return aging_totals(
            [(s.invoice.due_date, s.balance.balance_cents) for s in self.invoice_states(day, supplier_id)], day
        )

    def booked_charges(self, invoice_id: int) -> dict[LedgerEntryType, int]:
        out: dict[LedgerEntryType, int] = defaultdict(int)
        for line in self.lines(invoice_id=invoice_id):
            out[line.category] += line.amount_cents
        return dict(out)

    # -- postings --------------------------------------------------------------
    def post(
        self,
        *,
        entry_date: date,
        supplier_id: int,
        entry_type: LedgerEntryType,
        amount_cents: int,
        invoice_id: int | None = None,
        document_id: int | None = None,
        notice_id: int | None = None,
        payment_id: int | None = None,
        comment: str = "",
    ) -> LedgerEntry:
        if entry_type == LedgerEntryType.REVERSAL:
            raise LedgerError("Stornos werden über reverse_entry gebucht.")
        return self.repos.ledger.append(LedgerEntry(
            entry_date=entry_date, supplier_id=supplier_id, entry_type=entry_type, category_type=entry_type,
            amount_cents=amount_cents, invoice_id=invoice_id, document_id=document_id, notice_id=notice_id,
            payment_id=payment_id, comment=comment))

    def reverse_entry(
        self, entry_id: int, reason: str = "", entry_date: date | None = None, *, allow_payment: bool = False
    ) -> LedgerEntry:
        """Append a reversal; the original entry is never edited or deleted."""
        original = self.repos.ledger.get(entry_id)
        if original is None:
            raise NotFoundError("Buchung nicht gefunden.")
        if original.entry_type == LedgerEntryType.REVERSAL:
            raise LedgerError("Eine Stornobuchung kann nicht erneut storniert werden.")
        if self.repos.ledger.is_reversed(entry_id):
            raise LedgerError("Diese Buchung wurde bereits storniert.")
        if original.category_type == LedgerEntryType.PAYMENT and original.payment_id and not allow_payment:
            raise LedgerError("Zahlungen werden über 'Zahlung stornieren' rückgängig gemacht.")
        with self.repos.transaction():
            rev = self.repos.ledger.append(LedgerEntry(
                entry_date=max(entry_date or today(), original.entry_date), supplier_id=original.supplier_id,
                entry_type=LedgerEntryType.REVERSAL, category_type=original.category_type,
                amount_cents=-original.amount_cents, invoice_id=original.invoice_id,
                document_id=original.document_id, notice_id=original.notice_id, payment_id=original.payment_id,
                reverses_entry_id=original.id, comment=reason or f"Storno zu Buchung {original.id}"))
            self._audit("reverse", "ledger_entry", original.id, reason)
            if original.invoice_id:
                self.refresh_status(original.invoice_id)
        return rev

    def refresh_status(self, invoice_id: int) -> InvoiceStatus:
        """Recompute the stored status of an invoice from its entries."""
        invoice = self.repos.invoices.get(invoice_id)
        if invoice is None:
            raise NotFoundError("Rechnung nicht gefunden.")
        status = self.invoice_balance(invoice_id).status
        if status != invoice.status:
            self.repos.invoices.set_status(invoice_id, status)
        return status

    # -- derived comparisons ---------------------------------------------------
    def calculate_interest(self, invoice_id: int, until: date | None = None) -> InterestResult | None:
        """Interest the app calculates for comparison (None when the invoice has no due date)."""
        invoice = self.repos.invoices.get(invoice_id)
        if invoice is None:
            raise NotFoundError("Rechnung nicht gefunden.")
        if invoice.due_date is None:
            return None
        bal = self.invoice_balance(invoice_id)
        principal = bal.invoiced_cents - bal.credits_cents + bal.adjustments_cents - bal.write_offs_cents
        payments = [
            (r.payment_date, r.amount_cents) for r in self.allocation_rows(invoice_id)
            if r.component == AllocationComponent.PRINCIPAL
        ]
        return calculate_interest(
            principal, invoice.due_date, until or today(), self.settings.rate_points(),
            self.settings.interest_margin, payments,
        )

    def reconcile_notice(self, notice_id: int) -> NoticeReconciliation:
        notice = self.repos.notices.get(notice_id)
        if notice is None:
            raise NotFoundError("Schreiben nicht gefunden.")
        claims = [
            EngineClaim(c.invoice_id, c.principal_cents, c.fees_cents, c.interest_cents, c.flat_fee_cents,
                        c.other_costs_cents, c.total_cents)
            for c in notice.claims
        ]
        lines = {c.invoice_id: self.lines(invoice_id=c.invoice_id) for c in notice.claims}
        return reconcile_notice(notice.notice_date, claims, lines, notice.credited_cents)

    def describe_entry(self, entry: LedgerEntry) -> str:
        return f"{format_date(entry.entry_date)} {entry.entry_type.value} {entry.amount_cents}"
