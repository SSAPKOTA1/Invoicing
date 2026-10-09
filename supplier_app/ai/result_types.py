"""Data types shared by the recognition components. Every value carries confidence and source span."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import date
from typing import Any

from supplier_app.models.enums import DocumentType, ReferenceType

Span = tuple[int, int]


@dataclass
class FieldValue:
    """One extracted value with a confidence in 0..1 and its location in the source text."""

    value: Any
    confidence: float
    span: Span | None = None
    raw: str = ""

    def to_json(self) -> dict[str, Any]:
        v = self.value.isoformat() if isinstance(self.value, date) else self.value
        return {"value": v, "confidence": round(self.confidence, 3), "span": list(self.span) if self.span else None,
                "raw": self.raw}


@dataclass
class Classification:
    doc_type: DocumentType
    confidence: float
    scores: dict[str, float] = field(default_factory=dict)
    reasons: list[str] = field(default_factory=list)


@dataclass
class ExtractedReference:
    ref_type: ReferenceType
    value: FieldValue  # raw text as printed

    @property
    def raw(self) -> str:
        return str(self.value.value)


#: keys used in ExtractedFields.amounts (all values are cents)
AMOUNT_KEYS = (
    "net", "vat", "gross", "principal", "fees", "interest", "flat_fee", "collection_costs", "court_costs",
    "total_claimed", "already_paid", "payment_amount", "credit_amount",
)


@dataclass
class ExtractedFields:
    sender_name: FieldValue | None = None
    document_date: FieldValue | None = None
    due_date: FieldValue | None = None  # invoice due date ("zahlbar bis")
    deadline: FieldValue | None = None  # new payment deadline in dunning letters
    payment_date: FieldValue | None = None
    invoice_numbers: list[FieldValue] = field(default_factory=list)
    referenced_invoice_dates: list[FieldValue] = field(default_factory=list)
    references: list[ExtractedReference] = field(default_factory=list)
    amounts: dict[str, FieldValue] = field(default_factory=dict)
    fee_items: list[FieldValue] = field(default_factory=list)
    ibans: list[FieldValue] = field(default_factory=list)
    vat_ids: list[FieldValue] = field(default_factory=list)
    vat_rate: FieldValue | None = None
    currency: FieldValue | None = None

    def amount(self, key: str) -> int | None:
        f = self.amounts.get(key)
        return int(f.value) if f is not None else None

    def to_json(self) -> dict[str, Any]:
        def one(f: FieldValue | None) -> Any:
            return f.to_json() if f else None

        return {
            "sender_name": one(self.sender_name), "document_date": one(self.document_date),
            "due_date": one(self.due_date), "deadline": one(self.deadline), "payment_date": one(self.payment_date),
            "invoice_numbers": [f.to_json() for f in self.invoice_numbers],
            "referenced_invoice_dates": [f.to_json() for f in self.referenced_invoice_dates],
            "references": [{"type": r.ref_type.value, **r.value.to_json()} for r in self.references],
            "amounts": {k: v.to_json() for k, v in self.amounts.items()},
            "fee_items": [f.to_json() for f in self.fee_items],
            "ibans": [f.to_json() for f in self.ibans], "vat_ids": [f.to_json() for f in self.vat_ids],
            "vat_rate": one(self.vat_rate), "currency": one(self.currency),
        }


@dataclass
class ValidationIssue:
    code: str
    message: str
    field_name: str = ""
    severity: str = "warning"  # 'warning' | 'error'


@dataclass
class LinkCandidate:
    invoice_id: int
    score: float
    reasons: list[str]
    supplier_id: int
    invoice_number: str = ""

    def to_json(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class SenderMatch:
    party_id: int | None
    name: str
    score: float
    reason: str
    supplier_id: int | None = None  # supplier whose ledger it belongs to (agency -> represented supplier)


@dataclass
class DocumentAnalysis:
    """Complete result of the recognition pipeline for one document."""

    text_length: int
    classification: Classification
    fields: ExtractedFields
    sender: SenderMatch | None
    candidates: list[LinkCandidate]
    issues: list[ValidationIssue]
    overall_confidence: float

    def to_json(self) -> str:
        data = {
            "text_length": self.text_length,
            "classification": {"doc_type": self.classification.doc_type.value,
                               "confidence": round(self.classification.confidence, 3),
                               "scores": {k: round(v, 3) for k, v in self.classification.scores.items()},
                               "reasons": self.classification.reasons},
            "fields": self.fields.to_json(),
            "sender": asdict(self.sender) if self.sender else None,
            "candidates": [c.to_json() for c in self.candidates],
            "issues": [asdict(i) for i in self.issues],
            "overall_confidence": round(self.overall_confidence, 3),
        }
        return json.dumps(data, ensure_ascii=False)
