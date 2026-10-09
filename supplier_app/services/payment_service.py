"""Payments: allocation preview, booking, reversal, application of unassigned credit."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date

from supplier_app.errors import LedgerError, NotFoundError, ValidationError
from supplier_app.models.entities import DocumentReference, Payment, PaymentAllocation
from supplier_app.models.enums import (
    AllocationComponent,
    AllocationRule,
    EntityKind,
    InvoiceStatus,
    LedgerEntryType,
    PaymentMethod,
    ReferenceType,
)
from supplier_app.repositories.interfaces import Repositories
from supplier_app.services.base import ServiceBase, today
from supplier_app.services.case_service import CaseService
from supplier_app.services.ledger import (
    Allocation,
    AllocationResult,
    InvoiceBalance,
    OpenItem,
    allocate_payment,
    derive_status,
)
from supplier_app.services.ledger_service import LedgerService
from supplier_app.services.settings_service import SettingsService
from supplier_app.util.normalize import normalize_iban, normalize_reference

ManualAllocation = Sequence[tuple[int, AllocationComponent, int]]


@dataclass(frozen=True)
class PreviewRow:
    invoice_id: int
    invoice_number: str
    balance_before_cents: int
    applied_cents: int
    balance_after_cents: int
    status_after: InvoiceStatus


@dataclass(frozen=True)
class PaymentPreview:
    result: AllocationResult
    rows: list[PreviewRow]

    @property
    def unallocated_cents(self) -> int:
        return self.result.unallocated_cents


@dataclass(frozen=True)
class UnappliedPayment:
    payment: Payment
    entry_id: int
    amount_cents: int  # positive credit still unassigned


class PaymentService(ServiceBase):
    def __init__(self, repos: Repositories, ledger: LedgerService, cases: CaseService, settings: SettingsService) -> None:
        super().__init__(repos)
        self.ledger = ledger
        self.cases = cases
        self.settings = settings

    # -- allocation ------------------------------------------------------------
    def _open_items(self, supplier_id: int, invoice_ids: Sequence[int]) -> list[OpenItem]:
        items: list[OpenItem] = []
        for invoice_id in dict.fromkeys(invoice_ids):
            invoice = self.repos.invoices.get(invoice_id)
            if invoice is None or invoice.supplier_id != supplier_id:
                raise ValidationError("Die Rechnung gehört nicht zu diesem Lieferanten.")
            if invoice.status == InvoiceStatus.CANCELLED:
                raise ValidationError(f"Rechnung {invoice.invoice_number} ist storniert.")
            items.append(self.ledger.open_item(invoice_id))
        return items

    def preview(
        self, supplier_id: int, amount_cents: int, invoice_ids: Sequence[int], rule: AllocationRule | None = None,
        manual: ManualAllocation | None = None,
    ) -> PaymentPreview:
        items = self._open_items(supplier_id, invoice_ids)
        result = allocate_payment(amount_cents, items, rule or self.settings.allocation_rule, manual)
        applied = result.by_invoice()
        rows: list[PreviewRow] = []
        for item in items:
            invoice = self.repos.invoices.get(item.invoice_id)
            assert invoice is not None
            bal: InvoiceBalance = self.ledger.invoice_balance(item.invoice_id)
            use = applied.get(item.invoice_id, 0)
            after = bal.balance_cents - use
            manual_flag = invoice.status if invoice.status == InvoiceStatus.DISPUTED else None
            rows.append(PreviewRow(item.invoice_id, invoice.invoice_number, bal.balance_cents, use, after,
                                   derive_status(after, bal.paid_cents + use, manual_flag)))
        return PaymentPreview(result, rows)

    # -- booking ----------------------------------------------------------------
    def record_payment(
        self,
        supplier_id: int,
        payment_date: date,
        amount_cents: int,
        invoice_ids: Sequence[int] = (),
        *,
        rule: AllocationRule | None = None,
        manual: ManualAllocation | None = None,
        method: PaymentMethod = PaymentMethod.BANK_TRANSFER,
        bank_reference: str = "",
        iban: str = "",
        notes: str = "",
        document_id: int | None = None,
    ) -> Payment:
        """Book a payment, distribute it over the invoices; the rest stays as credit on account."""
        if self.repos.parties.get(supplier_id) is None:
            raise NotFoundError("Lieferant nicht gefunden.")
        if amount_cents <= 0:
            raise ValidationError("Der Zahlungsbetrag muss größer als 0 sein.")
        items = self._open_items(supplier_id, invoice_ids)
        result = allocate_payment(amount_cents, items, rule or self.settings.allocation_rule, manual) if items else \
            AllocationResult([], amount_cents)
        with self.repos.transaction():
            payment = self.repos.payments.add(Payment(
                supplier_id=supplier_id, payment_date=payment_date, amount_cents=amount_cents, method=method,
                bank_reference=bank_reference.strip(), iban=normalize_iban(iban) if iban else "", notes=notes,
                document_id=document_id))
            assert payment.id is not None
            self._book_allocations(payment, result.allocations, result.unallocated_cents, payment_date)
            if bank_reference.strip():
                norm = normalize_reference(bank_reference)
                if norm:
                    for invoice_id in result.by_invoice():
                        self.repos.references.add(DocumentReference(
                            EntityKind.INVOICE.value, invoice_id, ReferenceType.PAYMENT_REFERENCE,
                            bank_reference.strip(), norm))
            self._audit("create", "payment", payment.id, f"{amount_cents}")
        return payment

    def _book_allocations(
        self, payment: Payment, allocations: Sequence[Allocation], unallocated: int, entry_date: date
    ) -> None:
        assert payment.id is not None
        per_invoice: dict[int, int] = defaultdict(int)
        for a in allocations:
            self.repos.payments.add_allocation(PaymentAllocation(payment.id, a.invoice_id, a.component, a.amount_cents))
            per_invoice[a.invoice_id] += a.amount_cents
        for invoice_id, total in per_invoice.items():
            self.ledger.post(
                entry_date=entry_date, supplier_id=payment.supplier_id, entry_type=LedgerEntryType.PAYMENT,
                amount_cents=-total, invoice_id=invoice_id, payment_id=payment.id,
                comment=f"Zahlung {payment.bank_reference}".strip(), document_id=payment.document_id)
        if unallocated > 0:
            self.ledger.post(
                entry_date=entry_date, supplier_id=payment.supplier_id, entry_type=LedgerEntryType.PAYMENT,
                amount_cents=-unallocated, invoice_id=None, payment_id=payment.id,
                comment="Guthaben (keiner Rechnung zugeordnet)", document_id=payment.document_id)
        for invoice_id in per_invoice:
            self.ledger.refresh_status(invoice_id)
            self.cases.sync_with_invoice(invoice_id)

    # -- reversal ----------------------------------------------------------------
    def reverse_payment(self, payment_id: int, reason: str = "", on: date | None = None) -> None:
        """Cancel a payment by reversal entries (and negative allocation rows)."""
        payment = self.repos.payments.get(payment_id)
        if payment is None:
            raise NotFoundError("Zahlung nicht gefunden.")
        entries = self.repos.ledger.list(payment_id=payment_id)
        reversed_ids = {e.reverses_entry_id for e in entries if e.reverses_entry_id}
        active = [e for e in entries if e.entry_type == LedgerEntryType.PAYMENT and e.id not in reversed_ids]
        if not active:
            raise LedgerError("Diese Zahlung wurde bereits storniert.")
        sums: dict[tuple[int, AllocationComponent], int] = defaultdict(int)
        for a in self.repos.payments.allocations(payment_id=payment_id):
            sums[(a.invoice_id, a.component)] += a.amount_cents
        with self.repos.transaction():
            for entry in active:
                assert entry.id is not None
                self.ledger.reverse_entry(entry.id, reason or "Zahlung storniert", on, allow_payment=True)
            for (invoice_id, component), total in sums.items():
                if total != 0:
                    self.repos.payments.add_allocation(PaymentAllocation(payment_id, invoice_id, component, -total))
            self._audit("reverse", "payment", payment_id, reason)
            for invoice_id in {i for (i, _c) in sums}:
                self.ledger.refresh_status(invoice_id)
                self.cases.sync_with_invoice(invoice_id)

    # -- unassigned credit -----------------------------------------------------
    def unapplied_payments(self, supplier_id: int | None = None) -> list[UnappliedPayment]:
        entries = self.repos.ledger.list(supplier_id=supplier_id)
        reversed_ids = {e.reverses_entry_id for e in entries if e.reverses_entry_id}
        out: list[UnappliedPayment] = []
        for e in entries:
            if (e.entry_type == LedgerEntryType.PAYMENT and e.invoice_id is None and e.payment_id is not None
                    and e.id not in reversed_ids):
                payment = self.repos.payments.get(e.payment_id)
                assert payment is not None and e.id is not None
                out.append(UnappliedPayment(payment, e.id, -e.amount_cents))
        return out

    def apply_credit(
        self, payment_id: int, invoice_ids: Sequence[int], rule: AllocationRule | None = None,
        manual: ManualAllocation | None = None, on: date | None = None,
    ) -> PaymentPreview:
        """Assign the unassigned part of a payment to invoices later."""
        payment = self.repos.payments.get(payment_id)
        if payment is None:
            raise NotFoundError("Zahlung nicht gefunden.")
        pending = [u for u in self.unapplied_payments(payment.supplier_id) if u.payment.id == payment_id]
        if not pending:
            raise LedgerError("Für diese Zahlung gibt es kein nicht zugeordnetes Guthaben.")
        credit = pending[0]
        preview = self.preview(payment.supplier_id, credit.amount_cents, invoice_ids, rule, manual)
        with self.repos.transaction():
            self.ledger.reverse_entry(credit.entry_id, "Guthaben zugeordnet", on, allow_payment=True)
            self._book_allocations(payment, preview.result.allocations, preview.result.unallocated_cents,
                                   max(on or today(), payment.payment_date))
            self._audit("apply_credit", "payment", payment_id)
        return preview

    def list(self, supplier_id: int | None = None) -> list[Payment]:
        return self.repos.payments.list(supplier_id=supplier_id)
