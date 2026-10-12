"""Data of the review form: what the recognition proposes and what the user confirms."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import date
from decimal import Decimal

from supplier_app.ai.result_types import LinkCandidate, NewPartyInfo, PartyCandidate
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
    company_id: int | None = None  # own company / hotel the document is for (hotel implies its company)
    hotel_id: int | None = None
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
    supplier_candidates: list[PartyCandidate] = field(default_factory=list)  # suggestions for the supplier (ledger)
    sender_candidates: list[PartyCandidate] = field(default_factory=list)  # suggestions for the letter's author
    author_info: NewPartyInfo | None = None  # what the document says about its author (pre-fills a new record, is learned)
    invoice_candidates: list[LinkCandidate] = field(default_factory=list)  # invoices the letter may concern, best first
    supplier_suggested: bool = False  # the preselected supplier is a suggestion, not a certain match
    sender_suggested: bool = False


    # -- persistence of a confirmed proposal that waits for its invoice -------------------------------------------
    _SKIP = ("supplier_candidates", "sender_candidates", "invoice_candidates", "spans", "messages", "confidence")

    def to_json(self) -> str:
        """The confirmed values as JSON (suggestions and source spans are recalculated when the document is opened)."""
        data = asdict(self)
        for key in self._SKIP:
            data.pop(key, None)
        data["kind"], data["doc_type"] = self.kind, self.doc_type.value
        data["new_sender_role"], data["method"] = self.new_sender_role.value, self.method.value
        data["level"] = int(self.level) if self.level is not None else None
        data["vat_rate"] = str(self.vat_rate)
        for name in ("document_date", "due_date"):
            data[name] = getattr(self, name).isoformat() if getattr(self, name) else None
        data["references"] = [[t.value, v] for t, v in self.references]
        return json.dumps(data, ensure_ascii=False)

    @classmethod
    def from_json(cls, text: str) -> ReviewData:
        data = json.loads(text)
        info = data.pop("author_info", None)
        claims = [ClaimInput(**c) for c in data.pop("claims", [])]
        refs = [(ReferenceType(t), v) for t, v in data.pop("references", [])]
        data["doc_type"] = DocumentType(data["doc_type"])
        data["new_sender_role"] = PartyRole(data["new_sender_role"])
        data["method"] = PaymentMethod(data["method"])
        data["level"] = DunningLevel(data["level"]) if data.get("level") is not None else None
        data["vat_rate"] = Decimal(data["vat_rate"])
        for name in ("document_date", "due_date"):
            data[name] = date.fromisoformat(data[name]) if data.get(name) else None
        data["payment_invoice_ids"] = list(data.get("payment_invoice_ids", []))
        data["sender_ibans"], data["sender_vat_ids"] = list(data.get("sender_ibans", [])), list(data.get("sender_vat_ids", []))
        review = cls(**data)
        review.claims, review.references = claims, refs
        review.author_info = NewPartyInfo(**info) if info else None
        return review


@dataclass
class ConfirmResult:
    kind: str
    invoice_id: int | None = None
    notice_id: int | None = None
    payment_id: int | None = None
    warnings: list[str] = field(default_factory=list)
    discrepancies: list[str] = field(default_factory=list)
    unassigned: bool = False  # filed without an invoice: nothing was booked, the invoice is assigned later
