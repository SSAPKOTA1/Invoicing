"""Invoice / case history: chronological timeline with running balance."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from supplier_app.errors import NotFoundError
from supplier_app.i18n import level_label, tr
from supplier_app.models.entities import Case, DunningNotice, Invoice
from supplier_app.models.enums import DunningLevel, LedgerEntryType
from supplier_app.repositories.interfaces import Repositories
from supplier_app.services.base import ServiceBase, today
from supplier_app.services.ledger import InvoiceBalance, NoticeReconciliation
from supplier_app.services.ledger_service import LedgerService


@dataclass
class HistoryItem:
    item_date: date
    kind: str  # 'entry' | 'notice'
    title: str
    amount_cents: int = 0
    running_cents: int | None = None
    entry_type: LedgerEntryType | None = None
    entry_id: int | None = None
    notice_id: int | None = None
    document_id: int | None = None
    level: DunningLevel | None = None
    claimed_cents: int | None = None
    expected_cents: int | None = None
    warnings: list[str] = field(default_factory=list)
    reversed: bool = False
    comment: str = ""


@dataclass
class InvoiceHistory:
    invoice: Invoice
    supplier_name: str
    balance: InvoiceBalance
    references: list[tuple[str, str]]  # (type label, raw value)
    next_deadline: date | None
    case: Case | None
    items: list[HistoryItem]
    warnings: list[str]


class HistoryService(ServiceBase):
    def __init__(self, repos: Repositories, ledger: LedgerService) -> None:
        super().__init__(repos)
        self.ledger = ledger

    def references_of(self, invoice_id: int) -> list[tuple[str, str]]:
        refs = list(self.repos.references.for_owner("invoice", invoice_id))
        case = self.repos.cases.get_by_invoice(invoice_id)
        if case and case.id:
            refs.extend(self.repos.references.for_owner("case", case.id))
        seen: set[tuple[str, str]] = set()
        out: list[tuple[str, str]] = []
        for r in refs:
            key = (r.ref_type.value, r.normalized_value)
            if key not in seen:
                seen.add(key)
                out.append((tr(f"ref.{r.ref_type.value}"), r.raw_value))
        return out

    def next_deadline(self, invoice_id: int) -> date | None:
        """Latest open deadline: newest notice deadline, else the invoice due date (if still open)."""
        invoice = self.repos.invoices.get(invoice_id)
        if invoice is None:
            return None
        if self.ledger.invoice_balance(invoice_id).balance_cents <= 0:
            return None
        notices = [n for n in self.repos.notices.list(invoice_id=invoice_id) if n.new_deadline]
        if notices:
            latest = max(notices, key=lambda n: (n.notice_date, n.id or 0))
            return latest.new_deadline
        return invoice.due_date

    def invoice_history(self, invoice_id: int) -> InvoiceHistory:
        invoice = self.repos.invoices.get(invoice_id)
        if invoice is None:
            raise NotFoundError("Rechnung nicht gefunden.")
        supplier = self.repos.parties.get(invoice.supplier_id)
        entries = self.repos.ledger.list(invoice_id=invoice_id)
        reversed_ids = {e.reverses_entry_id for e in entries if e.reverses_entry_id}
        running = {r.line.entry_id: r.balance_cents for r in self.ledger.invoice_running(invoice_id)}
        notices = self.repos.notices.list(invoice_id=invoice_id)
        recon: dict[int, NoticeReconciliation] = {n.id: self.ledger.reconcile_notice(n.id) for n in notices if n.id}
        sortable: list[tuple[tuple[date, int, int], HistoryItem]] = []
        order = {LedgerEntryType.INVOICE: 0, LedgerEntryType.CREDIT_NOTE: 3, LedgerEntryType.PAYMENT: 4}
        for e in entries:
            assert e.id is not None
            title = tr(f"entry.{e.entry_type.value}")
            if e.entry_type == LedgerEntryType.REVERSAL:
                title = f"{tr('entry.REVERSAL')} ({tr(f'entry.{e.category_type.value}')})"
            item = HistoryItem(
                e.entry_date, "entry", title, e.amount_cents, running.get(e.id), e.entry_type, e.id, e.notice_id,
                e.document_id, comment=e.comment, reversed=e.id in reversed_ids)
            sortable.append(((e.entry_date, order.get(e.entry_type, 2), e.id), item))
        for n in notices:
            assert n.id is not None
            claim = next(c for c in n.claims if c.invoice_id == invoice_id)
            rec = next(r for r in recon[n.id].per_invoice if r.invoice_id == invoice_id)
            warns = [i.message for i in recon[n.id].issues if i.invoice_id in (None, invoice_id)]
            sender = self.repos.parties.get(n.sender_party_id)
            item = HistoryItem(
                n.notice_date, "notice", f"{level_label(int(n.level))} – {sender.name if sender else '?'}",
                notice_id=n.id, document_id=n.document_id, level=n.level,
                claimed_cents=claim.total_cents or claim.principal_cents, expected_cents=rec.expected_cents,
                warnings=warns, comment=n.notes)
            sortable.append(((n.notice_date, 1, n.id), item))
        sortable.sort(key=lambda t: t[0])
        balance = self.ledger.invoice_balance(invoice_id)
        warnings = [w for _k, it in sortable for w in it.warnings]
        case = self.repos.cases.get_by_invoice(invoice_id)
        return InvoiceHistory(
            invoice=invoice, supplier_name=supplier.name if supplier else "", balance=balance,
            references=self.references_of(invoice_id), next_deadline=self.next_deadline(invoice_id), case=case,
            items=[it for _k, it in sortable], warnings=warnings)

    def case_history(self, case_id: int) -> InvoiceHistory:
        case = self.repos.cases.get(case_id)
        if case is None or case.invoice_id is None:
            raise NotFoundError("Vorgang nicht gefunden.")
        return self.invoice_history(case.invoice_id)

    def notices_for_case(self, case_id: int) -> list[DunningNotice]:
        case = self.repos.cases.get(case_id)
        if case is None or case.invoice_id is None:
            return []
        return self.repos.notices.list(invoice_id=case.invoice_id)

    def overdue_days(self, invoice: Invoice) -> int:
        return max(0, (today() - invoice.due_date).days) if invoice.due_date else 0
