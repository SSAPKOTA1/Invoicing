"""Data of the review form: what the recognition proposes and what the user confirms."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from supplier_app.models.enums import DocumentType, DunningLevel, PartyRole, PaymentMethod, ReferenceType

KIND_INVOICE = "invoice"
KIND_CREDIT = "credit_note"
KIND_NOTICE = "notice"
KIND_PAYMENT = "payment"
KIND_NONE = "none"


@dataclass
class ClaimInput:
    invoice_id: int
    principal_cents: int = 0
    fees_cents: int = 0
    interest_cents: int = 0
    flat_fee_cents: int = 0
    other_costs_cents: int = 0
    total_cents: int = 0


@dataclass
class ReviewData:
    """Editable proposal for one document. Nothing is booked until :meth:`IngestService.confirm`."""

    document_id: int
    kind: str = KIND_NONE
    doc_type: DocumentType = DocumentType.OTHER
    supplier_id: int | None = None
    new_supplier_name: str = ""
    sender_party_id: int | None = None
    new_sender_name: str = ""
    new_sender_role: PartyRole = PartyRole.COLLECTION_AGENCY
    document_date: date | None = None
    due_date: date | None = None  # invoice due date or the new deadline of a notice
    invoice_number: str = ""
    net_cents: int | None = None
    vat_cents: int | None = None
    gross_cents: int | None = None
    vat_rate: Decimal = Decimal("19")
    invoice_id: int | None = None  # target of a credit note
    level: DunningLevel | None = None
    claims: list[ClaimInput] = field(default_factory=list)
    total_claimed_cents: int = 0
    credited_cents: int = 0
    payment_amount_cents: int | None = None
    payment_invoice_ids: list[int] = field(default_factory=list)
    bank_reference: str = ""
    iban: str = ""
    method: PaymentMethod = PaymentMethod.BANK_TRANSFER
    references: list[tuple[ReferenceType, str]] = field(default_factory=list)
    notes: str = ""
    confidence: dict[str, float] = field(default_factory=dict)  # field name -> 0..1
    spans: dict[str, tuple[int, int]] = field(default_factory=dict)  # field name -> span in OCR text
    messages: list[str] = field(default_factory=list)  # validation / hints shown above the form
    sender_ibans: list[str] = field(default_factory=list)
    sender_vat_ids: list[str] = field(default_factory=list)


@dataclass
class ConfirmResult:
    kind: str
    invoice_id: int | None = None
    notice_id: int | None = None
    payment_id: int | None = None
    warnings: list[str] = field(default_factory=list)
    discrepancies: list[str] = field(default_factory=list)
