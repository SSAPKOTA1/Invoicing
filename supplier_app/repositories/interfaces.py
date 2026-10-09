"""Abstract repository interfaces (the services depend only on these)."""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import date
from typing import Any

from supplier_app.models.entities import (
    AuditLogEntry,
    Case,
    CaseEvent,
    Category,
    Document,
    DocumentReference,
    DunningNotice,
    InterestRate,
    Invoice,
    LedgerEntry,
    Party,
    Payment,
    PaymentAllocation,
)
from supplier_app.models.enums import InvoiceStatus, PartyRole, ReviewStatus


class PartyRepository(ABC):
    @abstractmethod
    def add(self, party: Party) -> Party: ...
    @abstractmethod
    def update(self, party: Party) -> None: ...
    @abstractmethod
    def get(self, party_id: int) -> Party | None: ...
    @abstractmethod
    def list(self, role: PartyRole | None = None) -> list[Party]: ...
    @abstractmethod
    def delete(self, party_id: int) -> None: ...
    @abstractmethod
    def find_by_iban(self, iban: str) -> list[Party]: ...
    @abstractmethod
    def find_by_vat_id(self, vat_id: str) -> list[Party]: ...
    @abstractmethod
    def name_variants(self) -> list[tuple[int, str, str]]:
        """All (party_id, normalized variant, original variant) incl. aliases."""
    @abstractmethod
    def search_names(self, norm_fragment: str) -> list[Party]: ...
    @abstractmethod
    def has_dependents(self, party_id: int) -> bool: ...


class InvoiceRepository(ABC):
    @abstractmethod
    def add(self, invoice: Invoice) -> Invoice: ...
    @abstractmethod
    def update(self, invoice: Invoice) -> None: ...
    @abstractmethod
    def get(self, invoice_id: int) -> Invoice | None: ...
    @abstractmethod
    def get_by_number(self, supplier_id: int, invoice_number: str) -> Invoice | None: ...
    @abstractmethod
    def find_by_number_norm(self, norm: str, supplier_id: int | None = None, prefix: bool = False) -> list[Invoice]: ...
    @abstractmethod
    def list(self, supplier_id: int | None = None, status: InvoiceStatus | None = None) -> list[Invoice]: ...
    @abstractmethod
    def set_status(self, invoice_id: int, status: InvoiceStatus) -> None: ...
    @abstractmethod
    def find_by_gross(self, gross_cents: int, supplier_id: int | None = None) -> list[Invoice]: ...


class LedgerRepository(ABC):
    @abstractmethod
    def append(self, entry: LedgerEntry) -> LedgerEntry: ...
    @abstractmethod
    def get(self, entry_id: int) -> LedgerEntry | None: ...
    @abstractmethod
    def list(
        self,
        *,
        invoice_id: int | None = None,
        supplier_id: int | None = None,
        date_from: date | None = None,
        date_to: date | None = None,
        notice_id: int | None = None,
        payment_id: int | None = None,
    ) -> list[LedgerEntry]: ...
    @abstractmethod
    def is_reversed(self, entry_id: int) -> bool: ...
    @abstractmethod
    def sums_by_invoice(
        self, *, as_of: date | None = None, supplier_id: int | None = None
    ) -> list[tuple[int, int, str, int]]:
        """Rows ``(invoice_id, supplier_id, category_type, total_cents)`` for entries with an invoice."""
    @abstractmethod
    def unapplied_by_supplier(self, *, as_of: date | None = None) -> dict[int, int]:
        """Sum of entries without invoice per supplier (negative = credit on account)."""
    @abstractmethod
    def balances_by_invoice(self, *, as_of: date | None = None, supplier_id: int | None = None) -> dict[int, int]:
        """Sum of all entries per invoice (the open balance), one row per invoice."""
    @abstractmethod
    def unapplied_entries(self, *, supplier_id: int | None = None, as_of: date | None = None) -> list[LedgerEntry]:
        """Not yet reversed PAYMENT entries without invoice (credit on account)."""
    @abstractmethod
    def sums_by_type(
        self,
        *,
        date_from: date | None = None,
        date_to: date | None = None,
        supplier_id: int | None = None,
        month_buckets: bool = False,
    ) -> list[tuple[str, str, int]]:
        """Rows ``(bucket, category_type, total)``; bucket is ``YYYY-MM`` or ``''``."""
    @abstractmethod
    def count(self) -> int: ...


class NoticeRepository(ABC):
    @abstractmethod
    def add(self, notice: DunningNotice, dedup_key: str) -> DunningNotice: ...
    @abstractmethod
    def get(self, notice_id: int) -> DunningNotice | None: ...
    @abstractmethod
    def find_by_dedup_key(self, key: str) -> DunningNotice | None: ...
    @abstractmethod
    def list(
        self, *, supplier_id: int | None = None, invoice_id: int | None = None, case_id: int | None = None
    ) -> list[DunningNotice]: ...
    @abstractmethod
    def set_case(self, notice_id: int, case_id: int | None) -> None: ...


class PaymentRepository(ABC):
    @abstractmethod
    def add(self, payment: Payment) -> Payment: ...
    @abstractmethod
    def get(self, payment_id: int) -> Payment | None: ...
    @abstractmethod
    def list(
        self, *, supplier_id: int | None = None, date_from: date | None = None, date_to: date | None = None
    ) -> list[Payment]: ...
    @abstractmethod
    def add_allocation(self, alloc: PaymentAllocation) -> PaymentAllocation: ...
    @abstractmethod
    def allocations(
        self, *, payment_id: int | None = None, invoice_id: int | None = None
    ) -> list[PaymentAllocation]: ...
    @abstractmethod
    def allocation_sums(self, *, as_of: date | None = None) -> list[tuple[int, str, int]]:
        """Rows ``(invoice_id, component, total)`` of allocations booked up to ``as_of``."""


class DocumentRepository(ABC):
    @abstractmethod
    def add(self, doc: Document) -> Document: ...
    @abstractmethod
    def get(self, doc_id: int) -> Document | None: ...
    @abstractmethod
    def get_by_hash(self, sha256: str) -> Document | None: ...
    @abstractmethod
    def update(self, doc: Document) -> None: ...
    @abstractmethod
    def list(
        self, *, review_status: ReviewStatus | None = None, supplier_id: int | None = None, limit: int | None = None
    ) -> list[Document]: ...
    @abstractmethod
    def fulltext(self, fts_query: str, limit: int = 50) -> list[tuple[int, str]]:
        """``(document_id, snippet)`` for an FTS5 query."""
    @abstractmethod
    def count_by_status(self) -> dict[str, int]: ...


class ReferenceRepository(ABC):
    @abstractmethod
    def add(self, ref: DocumentReference) -> DocumentReference | None:
        """Insert unless an identical reference exists (returns ``None`` then)."""
    @abstractmethod
    def for_owner(self, owner_kind: str, owner_id: int) -> list[DocumentReference]: ...
    @abstractmethod
    def find(self, normalized: str, *, prefix: bool = False) -> list[DocumentReference]: ...


class CaseRepository(ABC):
    @abstractmethod
    def add(self, case: Case) -> Case: ...
    @abstractmethod
    def get(self, case_id: int) -> Case | None: ...
    @abstractmethod
    def get_by_invoice(self, invoice_id: int) -> Case | None: ...
    @abstractmethod
    def update(self, case: Case) -> None: ...
    @abstractmethod
    def list(self, *, supplier_id: int | None = None, status: str | None = None) -> list[Case]: ...
    @abstractmethod
    def add_event(self, event: CaseEvent) -> CaseEvent: ...
    @abstractmethod
    def events(self, case_id: int) -> list[CaseEvent]: ...


class SettingsRepository(ABC):
    @abstractmethod
    def get(self, key: str, default: str | None = None) -> str | None: ...
    @abstractmethod
    def set(self, key: str, value: str) -> None: ...
    @abstractmethod
    def delete(self, key: str) -> None: ...
    @abstractmethod
    def all(self) -> dict[str, str]: ...


class RateRepository(ABC):
    @abstractmethod
    def list(self) -> list[InterestRate]: ...
    @abstractmethod
    def upsert(self, rate: InterestRate) -> None: ...
    @abstractmethod
    def delete(self, valid_from: date) -> None: ...


class CategoryRepository(ABC):
    @abstractmethod
    def list(self) -> list[Category]: ...
    @abstractmethod
    def add(self, name: str) -> Category: ...
    @abstractmethod
    def delete(self, category_id: int) -> None: ...


class AuditRepository(ABC):
    @abstractmethod
    def add(self, entry: AuditLogEntry) -> AuditLogEntry: ...
    @abstractmethod
    def list(self, *, limit: int = 200, entity: str | None = None) -> list[AuditLogEntry]: ...


class Repositories(ABC):
    """Bundle of all repositories plus the transaction scope."""

    parties: PartyRepository
    invoices: InvoiceRepository
    ledger: LedgerRepository
    notices: NoticeRepository
    payments: PaymentRepository
    documents: DocumentRepository
    references: ReferenceRepository
    cases: CaseRepository
    settings: SettingsRepository
    rates: RateRepository
    categories: CategoryRepository
    audit: AuditRepository

    @abstractmethod
    def transaction(self) -> Any:
        """Context manager for an atomic unit of work."""
