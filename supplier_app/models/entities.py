"""Plain dataclasses for the domain model (no behaviour, no persistence)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from .enums import (
    AllocationComponent,
    CaseStatus,
    DocumentType,
    DunningLevel,
    InvoiceStatus,
    LedgerEntryType,
    PartyRole,
    PaymentMethod,
    ReferenceType,
    ReviewStatus,
)


@dataclass
class Party:
    """Supplier, collection agency or other counterpart."""

    name: str
    role: PartyRole = PartyRole.SUPPLIER
    id: int | None = None
    aliases: list[str] = field(default_factory=list)
    ibans: list[str] = field(default_factory=list)
    address: str = ""
    vat_id: str = ""
    tax_number: str = ""
    email: str = ""
    phone: str = ""
    contact: str = ""
    payment_terms: str = ""
    notes: str = ""
    represents_supplier_id: int | None = None
    created_at: str = ""


@dataclass
class Category:
    name: str
    id: int | None = None


@dataclass
class Invoice:
    supplier_id: int
    invoice_number: str
    invoice_date: date
    gross_cents: int
    id: int | None = None
    due_date: date | None = None
    net_cents: int = 0
    vat_rate: Decimal = Decimal("19")
    vat_cents: int = 0
    currency: str = "EUR"
    status: InvoiceStatus = InvoiceStatus.OPEN
    notes: str = ""
    category_id: int | None = None
    created_at: str = ""


@dataclass
class LedgerEntry:
    """Immutable, append-only ledger row. ``amount_cents`` is signed: debts positive."""

    entry_date: date
    supplier_id: int
    entry_type: LedgerEntryType
    amount_cents: int
    category_type: LedgerEntryType
    id: int | None = None
    invoice_id: int | None = None
    document_id: int | None = None
    notice_id: int | None = None
    payment_id: int | None = None
    reverses_entry_id: int | None = None
    comment: str = ""
    created_at: str = ""


@dataclass
class NoticeInvoiceClaim:
    """Amounts a notice claims for one invoice (cumulative, as stated by the sender)."""

    invoice_id: int
    principal_cents: int = 0
    fees_cents: int = 0
    interest_cents: int = 0
    flat_fee_cents: int = 0
    other_costs_cents: int = 0
    total_cents: int = 0
    id: int | None = None
    notice_id: int | None = None


@dataclass
class DunningNotice:
    sender_party_id: int
    supplier_id: int
    notice_date: date
    level: DunningLevel
    id: int | None = None
    new_deadline: date | None = None
    principal_cents: int = 0
    fees_cents: int = 0
    interest_cents: int = 0
    flat_fee_cents: int = 0
    other_costs_cents: int = 0
    total_claimed_cents: int = 0
    credited_cents: int = 0
    document_id: int | None = None
    case_id: int | None = None
    notes: str = ""
    claims: list[NoticeInvoiceClaim] = field(default_factory=list)
    created_at: str = ""


@dataclass
class Payment:
    supplier_id: int
    payment_date: date
    amount_cents: int
    id: int | None = None
    method: PaymentMethod = PaymentMethod.BANK_TRANSFER
    bank_reference: str = ""
    iban: str = ""
    notes: str = ""
    document_id: int | None = None
    created_at: str = ""


@dataclass
class PaymentAllocation:
    payment_id: int
    invoice_id: int
    component: AllocationComponent
    amount_cents: int
    id: int | None = None


@dataclass
class DocumentReference:
    owner_kind: str  # EntityKind value
    owner_id: int
    ref_type: ReferenceType
    raw_value: str
    normalized_value: str
    id: int | None = None


@dataclass
class Case:
    supplier_id: int
    invoice_id: int | None = None
    id: int | None = None
    title: str = ""
    status: CaseStatus = CaseStatus.OPEN
    notes: str = ""
    opened_at: str = ""
    auto_opened: bool = True


@dataclass
class CaseEvent:
    case_id: int
    event_date: date
    kind: str
    text: str
    id: int | None = None
    created_at: str = ""


@dataclass
class Document:
    stored_path: str
    sha256: str
    original_name: str
    id: int | None = None
    page_count: int = 1
    doc_type: DocumentType = DocumentType.OTHER
    ocr_text: str = ""
    extraction_json: str = ""
    review_status: ReviewStatus = ReviewStatus.PENDING
    confidence: float = 0.0
    supplier_id: int | None = None
    text_source: str = ""  # 'text_layer' | 'ocr' | 'plain' | ''
    created_at: str = ""


@dataclass
class InterestRate:
    valid_from: date
    base_rate: Decimal
    id: int | None = None


@dataclass
class AuditLogEntry:
    action: str
    entity: str
    entity_id: int | None
    details: str = ""
    id: int | None = None
    created_at: str = ""
