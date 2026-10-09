"""Invoices, credit notes, cancellations, write-offs and manual adjustments."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date, timedelta
from decimal import Decimal

from supplier_app.errors import LedgerError, NotFoundError, ValidationError
from supplier_app.models.entities import DocumentReference, Invoice
from supplier_app.models.enums import EntityKind, InvoiceStatus, LedgerEntryType, PartyRole, ReferenceType
from supplier_app.repositories.interfaces import Repositories
from supplier_app.services.base import ServiceBase, today
from supplier_app.services.case_service import CaseService
from supplier_app.services.ledger_service import LedgerService
from supplier_app.services.settings_service import SettingsService
from supplier_app.util.money import format_cents, percent_of
from supplier_app.util.normalize import normalize_reference


def compute_amounts(
    gross_cents: int | None, net_cents: int | None, vat_cents: int | None, vat_rate: Decimal
) -> tuple[int, int, int]:
    """Complete (net, vat, gross); validates net + VAT = gross within 1 cent."""
    if gross_cents is None and net_cents is None:
        raise ValidationError("Bitte Brutto- oder Nettobetrag angeben.")
    if gross_cents is None:
        assert net_cents is not None
        vat = vat_cents if vat_cents is not None else percent_of(net_cents, vat_rate)
        return net_cents, vat, net_cents + vat
    if net_cents is None:
        if vat_cents is not None:
            return gross_cents - vat_cents, vat_cents, gross_cents
        net = int((Decimal(gross_cents) / (1 + vat_rate / 100)).quantize(Decimal(1), rounding="ROUND_HALF_UP"))
        return net, gross_cents - net, gross_cents
    vat = vat_cents if vat_cents is not None else gross_cents - net_cents
    if abs(net_cents + vat - gross_cents) > 1:
        raise ValidationError(
            f"Netto ({format_cents(net_cents)}) + MwSt ({format_cents(vat)}) ergibt nicht Brutto "
            f"({format_cents(gross_cents)})."
        )
    return net_cents, vat, gross_cents


class InvoiceService(ServiceBase):
    def __init__(self, repos: Repositories, ledger: LedgerService, cases: CaseService, settings: SettingsService) -> None:
        super().__init__(repos)
        self.ledger = ledger
        self.cases = cases
        self.settings = settings

    def get(self, invoice_id: int) -> Invoice:
        invoice = self.repos.invoices.get(invoice_id)
        if invoice is None:
            raise NotFoundError("Rechnung nicht gefunden.")
        return invoice

    def add_reference(self, owner_kind: EntityKind, owner_id: int, ref_type: ReferenceType, raw: str) -> bool:
        norm = normalize_reference(raw)
        if not norm:
            return False
        return self.repos.references.add(DocumentReference(owner_kind.value, owner_id, ref_type, raw.strip(), norm)) is not None

    def create_invoice(
        self,
        supplier_id: int,
        invoice_number: str,
        invoice_date: date,
        *,
        gross_cents: int | None = None,
        net_cents: int | None = None,
        vat_cents: int | None = None,
        vat_rate: Decimal = Decimal("19"),
        due_date: date | None = None,
        currency: str = "EUR",
        notes: str = "",
        category_id: int | None = None,
        document_id: int | None = None,
        references: Sequence[tuple[ReferenceType, str]] = (),
    ) -> Invoice:
        """Create an invoice and book the INVOICE ledger entry."""
        supplier = self.repos.parties.get(supplier_id)
        if supplier is None or supplier.role == PartyRole.COLLECTION_AGENCY:
            raise ValidationError("Bitte einen gültigen Lieferanten wählen.")
        if not invoice_number.strip():
            raise ValidationError("Bitte eine Rechnungsnummer angeben.")
        net, vat, gross = compute_amounts(gross_cents, net_cents, vat_cents, vat_rate)
        if gross <= 0:
            raise ValidationError("Der Rechnungsbetrag muss größer als 0 sein.")
        due = due_date or invoice_date + timedelta(days=self.settings.default_payment_days)
        if due < invoice_date:
            raise ValidationError("Das Fälligkeitsdatum liegt vor dem Rechnungsdatum.")
        with self.repos.transaction():
            invoice = self.repos.invoices.add(Invoice(
                supplier_id=supplier_id, invoice_number=invoice_number.strip(), invoice_date=invoice_date,
                due_date=due, net_cents=net, vat_rate=vat_rate, vat_cents=vat, gross_cents=gross,
                currency=currency.upper(), notes=notes, category_id=category_id))
            assert invoice.id is not None
            self.ledger.post(
                entry_date=invoice_date, supplier_id=supplier_id, entry_type=LedgerEntryType.INVOICE,
                amount_cents=gross, invoice_id=invoice.id, document_id=document_id,
                comment=f"Rechnung {invoice.invoice_number}")
            self.add_reference(EntityKind.INVOICE, invoice.id, ReferenceType.INVOICE_NUMBER, invoice.invoice_number)
            for ref_type, raw in references:
                self.add_reference(EntityKind.INVOICE, invoice.id, ref_type, raw)
            self._audit("create", "invoice", invoice.id, invoice.invoice_number)
        return invoice

    def update_details(
        self, invoice_id: int, *, due_date: date | None = None, notes: str | None = None,
        category_id: int | None = None,
    ) -> Invoice:
        """Only non-monetary fields can change after booking (amounts need a reversal)."""
        invoice = self.get(invoice_id)
        if due_date is not None:
            if due_date < invoice.invoice_date:
                raise ValidationError("Das Fälligkeitsdatum liegt vor dem Rechnungsdatum.")
            invoice.due_date = due_date
        if notes is not None:
            invoice.notes = notes
        if category_id is not None:
            invoice.category_id = category_id
        self.repos.invoices.update(invoice)
        self._audit("update", "invoice", invoice_id)
        return invoice

    def credit_note(self, invoice_id: int, amount_cents: int, on: date, comment: str = "",
                    document_id: int | None = None) -> None:
        invoice = self.get(invoice_id)
        if amount_cents <= 0:
            raise ValidationError("Der Gutschriftsbetrag muss größer als 0 sein.")
        with self.repos.transaction():
            self.ledger.post(entry_date=on, supplier_id=invoice.supplier_id, entry_type=LedgerEntryType.CREDIT_NOTE,
                             amount_cents=-amount_cents, invoice_id=invoice_id, document_id=document_id,
                             comment=comment or "Gutschrift")
            self._after_change(invoice_id)

    def write_off(self, invoice_id: int, amount_cents: int, on: date, comment: str = "") -> None:
        invoice = self.get(invoice_id)
        open_cents = self.ledger.invoice_balance(invoice_id).balance_cents
        if amount_cents <= 0 or amount_cents > open_cents:
            raise ValidationError("Der Ausbuchungsbetrag muss zwischen 0 und dem offenen Betrag liegen.")
        with self.repos.transaction():
            self.ledger.post(entry_date=on, supplier_id=invoice.supplier_id, entry_type=LedgerEntryType.WRITE_OFF,
                             amount_cents=-amount_cents, invoice_id=invoice_id, comment=comment or "Ausbuchung")
            self._after_change(invoice_id)

    def adjustment(self, invoice_id: int, signed_cents: int, on: date, comment: str) -> None:
        invoice = self.get(invoice_id)
        if signed_cents == 0:
            raise ValidationError("Der Korrekturbetrag darf nicht 0 sein.")
        if not comment.strip():
            raise ValidationError("Bitte eine Begründung für die Korrektur angeben.")
        with self.repos.transaction():
            self.ledger.post(entry_date=on, supplier_id=invoice.supplier_id, entry_type=LedgerEntryType.ADJUSTMENT,
                             amount_cents=signed_cents, invoice_id=invoice_id, comment=comment)
            self._after_change(invoice_id)

    def set_disputed(self, invoice_id: int, disputed: bool) -> InvoiceStatus:
        invoice = self.get(invoice_id)
        if invoice.status == InvoiceStatus.CANCELLED:
            raise LedgerError("Eine stornierte Rechnung kann nicht strittig sein.")
        with self.repos.transaction():
            self.repos.invoices.set_status(invoice_id, InvoiceStatus.DISPUTED if disputed else InvoiceStatus.OPEN)
            status = self.ledger.refresh_status(invoice_id)
            self.cases.sync_with_invoice(invoice_id)
            self._audit("disputed" if disputed else "undisputed", "invoice", invoice_id)
        return status

    def cancel_invoice(self, invoice_id: int, reason: str = "") -> None:
        """Reverse every active entry of the invoice and mark it cancelled."""
        invoice = self.get(invoice_id)
        entries = self.repos.ledger.list(invoice_id=invoice_id)
        reversed_ids = {e.reverses_entry_id for e in entries if e.reverses_entry_id}
        active = [e for e in entries if e.entry_type != LedgerEntryType.REVERSAL and e.id not in reversed_ids]
        if any(e.category_type == LedgerEntryType.PAYMENT for e in active):
            raise LedgerError("Die Rechnung hat Zahlungen. Bitte zuerst die Zahlungen stornieren.")
        with self.repos.transaction():
            for entry in active:
                assert entry.id is not None
                self.ledger.reverse_entry(entry.id, reason or "Rechnung storniert", today())
            self.repos.invoices.set_status(invoice_id, InvoiceStatus.CANCELLED)
            self.cases.sync_with_invoice(invoice_id)
            self._audit("cancel", "invoice", invoice_id, reason)
        _ = invoice

    def _after_change(self, invoice_id: int) -> None:
        self.ledger.refresh_status(invoice_id)
        self.cases.sync_with_invoice(invoice_id)

    def list(self, supplier_id: int | None = None, status: InvoiceStatus | None = None) -> list[Invoice]:
        return self.repos.invoices.list(supplier_id=supplier_id, status=status)
