"""Plausibility checks on extracted values."""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal, InvalidOperation

from supplier_app.models.enums import DocumentType as D
from supplier_app.util.money import format_cents, percent_of
from supplier_app.util.normalize import valid_iban, valid_vat_id

from .result_types import Classification, ExtractedFields, ValidationIssue


def validate_fields(
    fields: ExtractedFields, classification: Classification, today: date | None = None
) -> list[ValidationIssue]:
    """Return warnings/errors; an empty list means everything checks out."""
    today = today or date.today()
    issues: list[ValidationIssue] = []
    dtype = classification.doc_type
    net, vat, gross = fields.amount("net"), fields.amount("vat"), fields.amount("gross")
    if dtype in (D.INVOICE, D.CREDIT_NOTE):
        if net is not None and vat is not None and gross is not None and abs(net + vat - gross) > 1:
            issues.append(ValidationIssue(
                "NET_VAT_GROSS",
                f"Netto ({format_cents(net)}) + MwSt ({format_cents(vat)}) ergibt nicht Brutto ({format_cents(gross)}).",
                "gross"))
        if net is not None and vat is not None and fields.vat_rate is not None:
            try:
                rate = Decimal(str(fields.vat_rate.value))
                if abs(percent_of(net, rate) - vat) > 2:
                    issues.append(ValidationIssue(
                        "VAT_RATE", f"Die MwSt ({format_cents(vat)}) passt nicht zu {rate} % von {format_cents(net)}.", "vat"))
            except InvalidOperation:
                pass
        if gross is None:
            issues.append(ValidationIssue("MISSING_AMOUNT", "Kein Rechnungs-/Gutschriftsbetrag erkannt.", "gross", "error"))
        if dtype == D.INVOICE and not fields.invoice_numbers:
            issues.append(ValidationIssue("MISSING_NUMBER", "Keine Rechnungsnummer erkannt.", "invoice_number", "error"))
    if dtype in (D.PAYMENT_REMINDER, D.FIRST_DUNNING, D.SECOND_DUNNING, D.FINAL_DUNNING, D.COLLECTION_LETTER, D.COURT_ORDER):
        parts = sum(fields.amount(k) or 0 for k in ("principal", "fees", "interest", "flat_fee", "collection_costs", "court_costs"))
        total = fields.amount("total_claimed")
        if total is not None and parts and abs(parts - total) > 1:
            issues.append(ValidationIssue(
                "CLAIM_SUM",
                f"Gesamtforderung {format_cents(total)} weicht von der Summe der Einzelposten {format_cents(parts)} ab "
                f"(Differenz {format_cents(abs(total - parts))}).", "total_claimed"))
        remaining, paid = fields.amount("remaining"), fields.amount("already_paid")
        if remaining is not None and total is not None and paid is not None and abs(total - paid - remaining) > 1:
            issues.append(ValidationIssue(
                "REMAINING_SUM", f"Gesamtforderung − Zahlung ({format_cents(total - paid)}) ergibt nicht den Restbetrag "
                f"{format_cents(remaining)}.", "remaining"))
        if total is None and fields.amount("remaining") is None:
            issues.append(ValidationIssue("MISSING_AMOUNT", "Keine Gesamtforderung erkannt.", "total_claimed", "error"))
    if dtype == D.BANK_STATEMENT and fields.amount("payment_amount") is None:
        issues.append(ValidationIssue("MISSING_AMOUNT", "Kein Zahlungsbetrag erkannt.", "payment_amount", "error"))
    doc_date = fields.document_date.value if fields.document_date else None
    if doc_date is not None:
        if doc_date > today + timedelta(days=7):
            issues.append(ValidationIssue("DATE_FUTURE", "Das Dokumentdatum liegt in der Zukunft.", "document_date"))
        if doc_date.year < 1990:
            issues.append(ValidationIssue("DATE_OLD", "Das Dokumentdatum ist unplausibel alt.", "document_date"))
        due = fields.due_date.value if fields.due_date else None
        if due is not None and due < doc_date:
            issues.append(ValidationIssue("DUE_BEFORE_DATE", "Die Fälligkeit liegt vor dem Rechnungsdatum.", "due_date"))
        deadline = fields.deadline.value if fields.deadline else None
        if deadline is not None and deadline < doc_date:
            issues.append(ValidationIssue("DEADLINE_BEFORE_DATE", "Die Zahlungsfrist liegt vor dem Schreibendatum.", "deadline"))
    elif dtype not in (D.OTHER, D.DELIVERY_NOTE):
        issues.append(ValidationIssue("MISSING_DATE", "Kein Datum erkannt.", "document_date", "error"))
    for iban in fields.ibans:
        if not valid_iban(str(iban.value)):
            issues.append(ValidationIssue("IBAN", f"IBAN '{iban.raw}' hat eine ungültige Prüfsumme (OCR-Fehler?).", "iban"))
    for vid in fields.vat_ids:
        if not valid_vat_id(str(vid.value)):
            issues.append(ValidationIssue("VAT_ID", f"USt-IdNr. '{vid.raw}' hat ein ungültiges Format.", "vat_id"))
    return issues
