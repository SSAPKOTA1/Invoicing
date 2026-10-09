"""Enumerations used across the application."""

from __future__ import annotations

from enum import Enum, IntEnum


class PartyRole(str, Enum):
    SUPPLIER = "supplier"
    COLLECTION_AGENCY = "collection_agency"
    OTHER = "other"


class InvoiceStatus(str, Enum):
    OPEN = "open"
    PARTIALLY_PAID = "partially_paid"
    PAID = "paid"
    DISPUTED = "disputed"
    CANCELLED = "cancelled"


class LedgerEntryType(str, Enum):
    INVOICE = "INVOICE"
    CREDIT_NOTE = "CREDIT_NOTE"
    PAYMENT = "PAYMENT"
    DUNNING_FEE = "DUNNING_FEE"
    LATE_INTEREST = "LATE_INTEREST"
    LATE_PAYMENT_FLAT_FEE = "LATE_PAYMENT_FLAT_FEE"
    COLLECTION_COST = "COLLECTION_COST"
    ADJUSTMENT = "ADJUSTMENT"
    WRITE_OFF = "WRITE_OFF"
    REVERSAL = "REVERSAL"


#: Entry types that are additional charges on top of the invoice gross amount.
CHARGE_TYPES: frozenset[LedgerEntryType] = frozenset(
    {
        LedgerEntryType.DUNNING_FEE,
        LedgerEntryType.LATE_INTEREST,
        LedgerEntryType.LATE_PAYMENT_FLAT_FEE,
        LedgerEntryType.COLLECTION_COST,
    }
)


class DunningLevel(IntEnum):
    REMINDER = 1
    FIRST = 2
    SECOND = 3
    FINAL = 4
    COLLECTION = 5
    COURT_ORDER = 6


class AllocationComponent(str, Enum):
    COSTS = "costs"
    INTEREST = "interest"
    PRINCIPAL = "principal"


class AllocationRule(str, Enum):
    STATUTORY = "statutory"  # costs -> interest -> principal (par. 367 BGB)
    OLDEST_FIRST = "oldest_first"  # oldest invoice first, then statutory within invoice
    MANUAL = "manual"


class CaseStatus(str, Enum):
    OPEN = "open"
    WAITING = "waiting"
    IN_DISPUTE = "in_dispute"
    PAID = "paid"
    CLOSED = "closed"


class DocumentType(str, Enum):
    INVOICE = "invoice"
    CREDIT_NOTE = "credit_note"
    PAYMENT_REMINDER = "payment_reminder"
    FIRST_DUNNING = "first_dunning"
    SECOND_DUNNING = "second_dunning"
    FINAL_DUNNING = "final_dunning"
    COLLECTION_LETTER = "collection_letter"
    COURT_ORDER = "court_order"
    BANK_STATEMENT = "bank_statement"
    DELIVERY_NOTE = "delivery_note"
    OTHER = "other"


#: Document types that are dunning-type letters mapped to their level.
DUNNING_DOC_LEVELS: dict[DocumentType, DunningLevel] = {
    DocumentType.PAYMENT_REMINDER: DunningLevel.REMINDER,
    DocumentType.FIRST_DUNNING: DunningLevel.FIRST,
    DocumentType.SECOND_DUNNING: DunningLevel.SECOND,
    DocumentType.FINAL_DUNNING: DunningLevel.FINAL,
    DocumentType.COLLECTION_LETTER: DunningLevel.COLLECTION,
    DocumentType.COURT_ORDER: DunningLevel.COURT_ORDER,
}


class ReviewStatus(str, Enum):
    PENDING = "pending"
    NEEDS_REVIEW = "needs_review"
    ACCEPTED = "accepted"
    REJECTED = "rejected"


class ReferenceType(str, Enum):
    INVOICE_NUMBER = "invoice_number"
    PROCESSING_NUMBER = "processing_number"  # Bearbeitungsnummer
    FILE_NUMBER = "file_number"  # Aktenzeichen
    CASE_NUMBER = "case_number"  # Vorgangsnummer
    CLAIM_NUMBER = "claim_number"  # Forderungsnummer
    CUSTOMER_NUMBER = "customer_number"  # Kundennummer
    MANDATE_NUMBER = "mandate_number"  # Mandatsnummer
    DEBTOR_NUMBER = "debtor_number"  # Debitorennummer
    ORDER_NUMBER = "order_number"  # Bestellnummer
    PAYMENT_REFERENCE = "payment_reference"  # Zahlungsreferenz
    OTHER = "other"


class PaymentMethod(str, Enum):
    BANK_TRANSFER = "bank_transfer"
    DIRECT_DEBIT = "direct_debit"
    CASH = "cash"
    CARD = "card"
    OTHER = "other"


class EntityKind(str, Enum):
    """Kinds of entities that can own a DocumentReference."""

    DOCUMENT = "document"
    INVOICE = "invoice"
    CASE = "case"
