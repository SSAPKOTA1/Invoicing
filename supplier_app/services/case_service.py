"""Cases (Bearbeitungsvorgänge): auto-opened with the first reminder, grouped timeline."""

from __future__ import annotations

from datetime import date

from supplier_app.errors import NotFoundError
from supplier_app.i18n import tr
from supplier_app.models.entities import Case, CaseEvent
from supplier_app.models.enums import CaseStatus, InvoiceStatus
from supplier_app.repositories.interfaces import Repositories
from supplier_app.services.base import ServiceBase, today


class CaseService(ServiceBase):
    def __init__(self, repos: Repositories) -> None:
        super().__init__(repos)

    def get(self, case_id: int) -> Case:
        case = self.repos.cases.get(case_id)
        if case is None:
            raise NotFoundError("Vorgang nicht gefunden.")
        return case

    def ensure_for_invoice(self, invoice_id: int, *, auto: bool = True, on: date | None = None) -> Case:
        """Return the case of an invoice, opening it when it does not exist yet."""
        existing = self.repos.cases.get_by_invoice(invoice_id)
        if existing is not None:
            return existing
        invoice = self.repos.invoices.get(invoice_id)
        if invoice is None:
            raise NotFoundError("Rechnung nicht gefunden.")
        supplier = self.repos.parties.get(invoice.supplier_id)
        name = supplier.name if supplier else ""
        case = self.repos.cases.add(Case(
            supplier_id=invoice.supplier_id, invoice_id=invoice_id,
            title=f"{name} – {invoice.invoice_number}", auto_opened=auto))
        assert case.id is not None
        self.add_event(case.id, "opened", tr("case.event.opened_auto") if auto else tr("case.event.opened"), on)
        self._audit("open_case", "case", case.id)
        return case

    def open_manual(self, invoice_id: int) -> Case:
        return self.ensure_for_invoice(invoice_id, auto=False)

    def add_event(self, case_id: int, kind: str, text: str, on: date | None = None) -> CaseEvent:
        return self.repos.cases.add_event(CaseEvent(case_id, on or today(), kind, text))

    def add_note(self, case_id: int, text: str) -> None:
        case = self.get(case_id)
        stamp = today().strftime("%d.%m.%Y")
        case.notes = f"{case.notes}\n[{stamp}] {text}".strip()
        self.repos.cases.update(case)
        self.add_event(case_id, "note", text)

    def set_status(self, case_id: int, status: CaseStatus) -> None:
        case = self.get(case_id)
        if case.status != status:
            case.status = status
            self.repos.cases.update(case)
            self.add_event(case_id, "status", tr("case.event.status", status=tr(f"case.{status.value}")))
            self._audit("case_status", "case", case_id, status.value)

    def sync_with_invoice(self, invoice_id: int) -> None:
        """Keep the case status aligned with the (derived) invoice status."""
        case = self.repos.cases.get_by_invoice(invoice_id)
        invoice = self.repos.invoices.get(invoice_id)
        if case is None or invoice is None or case.id is None:
            return
        if invoice.status in (InvoiceStatus.PAID, InvoiceStatus.CANCELLED):
            if case.status in (CaseStatus.OPEN, CaseStatus.WAITING, CaseStatus.IN_DISPUTE):
                self.set_status(case.id, CaseStatus.PAID)
        elif invoice.status == InvoiceStatus.DISPUTED:
            if case.status != CaseStatus.IN_DISPUTE:
                self.set_status(case.id, CaseStatus.IN_DISPUTE)
        elif case.status in (CaseStatus.PAID, CaseStatus.IN_DISPUTE):
            self.set_status(case.id, CaseStatus.OPEN)

    def list(self, supplier_id: int | None = None, status: CaseStatus | None = None) -> list[Case]:
        return self.repos.cases.list(supplier_id=supplier_id, status=status.value if status else None)

    def events(self, case_id: int) -> list[CaseEvent]:
        return self.repos.cases.events(case_id)
