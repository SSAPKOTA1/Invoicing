"""Import workflow: file -> text -> recognition -> proposal -> (user confirms) -> bookings."""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from pathlib import Path

from supplier_app.ai.pipeline import AnalysisPipeline, build_default_pipeline
from supplier_app.ai.result_types import DocumentAnalysis, FieldValue
from supplier_app.errors import DocumentError, ValidationError
from supplier_app.models.entities import Document, DocumentReference, Party
from supplier_app.models.enums import (
    DUNNING_DOC_LEVELS,
    DocumentType,
    EntityKind,
    PartyRole,
    ReferenceType,
    ReviewStatus,
)
from supplier_app.ocr.pipeline import ExtractedText, TextExtractor
from supplier_app.ocr.tesseract import TesseractRunner
from supplier_app.repositories.interfaces import Repositories
from supplier_app.services.base import ServiceBase
from supplier_app.services.document_service import DocumentService, sha256_of
from supplier_app.services.dunning_service import DunningService, NoticeDraft
from supplier_app.services.invoice_service import InvoiceService
from supplier_app.services.ledger import NoticeClaim
from supplier_app.services.ledger_service import LedgerService
from supplier_app.services.payment_service import PaymentService
from supplier_app.services.review_models import (
    KIND_CREDIT,
    KIND_INVOICE,
    KIND_NONE,
    KIND_NOTICE,
    KIND_PAYMENT,
    ClaimInput,
    ConfirmResult,
    ReviewData,
)
from supplier_app.services.settings_service import SettingsService
from supplier_app.services.supplier_service import SupplierService
from supplier_app.util.normalize import normalize_reference, valid_iban

log = logging.getLogger(__name__)

_KIND_BY_TYPE = {
    DocumentType.INVOICE: KIND_INVOICE, DocumentType.CREDIT_NOTE: KIND_CREDIT, DocumentType.BANK_STATEMENT: KIND_PAYMENT,
    **dict.fromkeys(DUNNING_DOC_LEVELS, KIND_NOTICE),
}


@dataclass
class PreparedFile:
    """Result of the slow, DB-free step (hashing + text extraction); safe to run in a worker thread."""

    source: Path
    sha256: str
    extracted: ExtractedText | None
    error: str = ""


@dataclass
class ImportOutcome:
    document: Document | None
    created: bool
    analysis: DocumentAnalysis | None = None
    warnings: list[str] = field(default_factory=list)
    error: str = ""


class IngestService(ServiceBase):
    def __init__(
        self, repos: Repositories, documents: DocumentService, extractor: TextExtractor, settings: SettingsService,
        ledger: LedgerService, suppliers: SupplierService, invoices: InvoiceService, payments: PaymentService,
        dunning: DunningService,
    ) -> None:
        super().__init__(repos)
        self.documents, self.extractor, self.settings, self.ledger = documents, extractor, settings, ledger
        self.suppliers, self.invoices, self.payments, self.dunning = suppliers, invoices, payments, dunning

    def pipeline(self) -> AnalysisPipeline:
        return build_default_pipeline(self.repos, self.ledger, self.settings)

    # -- import ----------------------------------------------------------------
    def prepare(self, path: Path, progress: Callable[[int, int], None] | None = None) -> PreparedFile:
        """Hash and extract text (no database access). Errors are captured, never raised."""
        path = Path(path)
        try:
            digest = sha256_of(path)
            return PreparedFile(path, digest, self.extractor.extract(path, progress))
        except (DocumentError, OSError) as exc:
            return PreparedFile(path, "", None, str(exc))
        except Exception as exc:  # noqa: BLE001 - OCR problems must not crash the import
            log.exception("prepare failed for %s", path)
            return PreparedFile(path, "", None, str(getattr(exc, "message", exc)))

    def register(self, prepared: PreparedFile) -> ImportOutcome:
        """Store the file, analyse the text, persist everything with status pending/needs_review."""
        if prepared.error or prepared.extracted is None:
            return ImportOutcome(None, False, error=prepared.error or "Unbekannter Fehler")
        existing = self.repos.documents.get_by_hash(prepared.sha256)
        if existing is not None:
            return ImportOutcome(existing, False, warnings=[f"'{prepared.source.name}' wurde bereits importiert."])
        try:
            doc, created = self.documents.store_file(prepared.source)
        except DocumentError as exc:
            return ImportOutcome(None, False, error=str(exc))
        ext = prepared.extracted
        analysis = self.pipeline().analyze(ext.text)
        doc.ocr_text, doc.page_count, doc.text_source = ext.text, ext.page_count, ext.source
        self._apply_analysis(doc, analysis, ext)
        warnings = list(ext.warnings)
        return ImportOutcome(doc, created, analysis, warnings)

    def import_file(self, path: Path, progress: Callable[[int, int], None] | None = None) -> ImportOutcome:
        return self.register(self.prepare(path, progress))

    def _apply_analysis(self, doc: Document, analysis: DocumentAnalysis, ext: ExtractedText | None = None) -> None:
        doc.doc_type = analysis.classification.doc_type
        doc.confidence = analysis.overall_confidence
        doc.extraction_json = analysis.to_json()
        doc.supplier_id = analysis.sender.supplier_id if analysis.sender else None
        errors = any(i.severity == "error" for i in analysis.issues)
        low = analysis.overall_confidence < self.settings.low_confidence
        if ext is not None and ext.empty:
            low = True
        doc.review_status = ReviewStatus.NEEDS_REVIEW if (low or errors) else ReviewStatus.PENDING
        with self.repos.transaction():
            self.repos.documents.update(doc)
            assert doc.id is not None
            self._store_document_references(doc.id, analysis)

    def _store_document_references(self, doc_id: int, analysis: DocumentAnalysis) -> None:
        refs = [(r.ref_type, r.raw) for r in analysis.fields.references]
        refs += [(ReferenceType.INVOICE_NUMBER, str(f.value)) for f in analysis.fields.invoice_numbers]
        for ref_type, raw in refs:
            norm = normalize_reference(raw)
            if norm:
                self.repos.references.add(DocumentReference(EntityKind.DOCUMENT.value, doc_id, ref_type, raw, norm))

    def reanalyze(self, doc_id: int) -> DocumentAnalysis:
        doc = self.documents.get(doc_id)
        analysis = self.pipeline().analyze(doc.ocr_text)
        if doc.review_status in (ReviewStatus.PENDING, ReviewStatus.NEEDS_REVIEW):
            self._apply_analysis(doc, analysis)
        return analysis

    def stored_analysis(self, doc_id: int) -> DocumentAnalysis | None:
        """Fresh analysis of the stored text (the JSON snapshot is kept for the audit trail)."""
        doc = self.documents.get(doc_id)
        return self.pipeline().analyze(doc.ocr_text) if doc.ocr_text.strip() else None

    # -- proposal ---------------------------------------------------------------
    def build_review(self, doc_id: int) -> ReviewData:
        doc = self.documents.get(doc_id)
        analysis = self.pipeline().analyze(doc.ocr_text)
        return self.review_from_analysis(doc, analysis)

    def review_from_analysis(self, doc: Document, analysis: DocumentAnalysis) -> ReviewData:
        assert doc.id is not None
        f, cls = analysis.fields, analysis.classification
        review = ReviewData(document_id=doc.id, doc_type=cls.doc_type, kind=_KIND_BY_TYPE.get(cls.doc_type, KIND_NONE))
        review.confidence["doc_type"] = cls.confidence
        sender = analysis.sender
        if sender:
            review.supplier_id = sender.supplier_id
            review.sender_party_id = sender.party_id
            if sender.party_id is None:
                review.new_sender_name = sender.name
                review.new_sender_role = (
                    PartyRole.OTHER if cls.doc_type == DocumentType.COURT_ORDER else
                    PartyRole.COLLECTION_AGENCY if cls.doc_type in DUNNING_DOC_LEVELS else PartyRole.SUPPLIER)
                if review.kind in (KIND_INVOICE, KIND_CREDIT):
                    review.new_supplier_name = sender.name
                    review.new_sender_name = ""
            review.confidence["sender"] = sender.score
        self._copy(review, "document_date", f.document_date)
        review.document_date = f.document_date.value if f.document_date else None
        due = f.due_date or f.deadline
        review.due_date = due.value if due else None
        self._copy(review, "due_date", due)
        review.sender_ibans = [str(i.value) for i in f.ibans if i.confidence >= 0.9]
        review.sender_vat_ids = [str(v.value) for v in f.vat_ids]
        review.references = [(r.ref_type, r.raw) for r in f.references]
        review.messages = [i.message for i in analysis.issues]
        top = analysis.candidates[0] if analysis.candidates else None
        if f.invoice_numbers:
            review.invoice_number = str(f.invoice_numbers[0].value)
            self._copy(review, "invoice_number", f.invoice_numbers[0])
        if review.kind in (KIND_INVOICE, KIND_CREDIT):
            review.net_cents, review.vat_cents, review.gross_cents = f.amount("net"), f.amount("vat"), f.amount("gross")
            for key in ("net", "vat", "gross"):
                self._copy(review, f"{key}_cents", f.amounts.get(key))
            if f.vat_rate:
                try:
                    review.vat_rate = Decimal(str(f.vat_rate.value))
                except InvalidOperation:
                    pass
            if review.kind == KIND_CREDIT and top:
                review.invoice_id = top.invoice_id
                review.supplier_id = review.supplier_id or top.supplier_id
            if review.kind == KIND_INVOICE and review.supplier_id is None and sender is not None:
                review.new_supplier_name = review.new_supplier_name or sender.name
        elif review.kind == KIND_NOTICE:
            review.level = DUNNING_DOC_LEVELS.get(cls.doc_type)
            self._notice_claims(review, analysis)
        elif review.kind == KIND_PAYMENT:
            review.payment_amount_cents = f.amount("payment_amount")
            self._copy(review, "payment_amount_cents", f.amounts.get("payment_amount"))
            if f.payment_date:
                review.document_date = f.payment_date.value
            if analysis.candidates:
                review.payment_invoice_ids = [analysis.candidates[0].invoice_id]
                review.supplier_id = review.supplier_id or analysis.candidates[0].supplier_id
            review.bank_reference = next((str(x.value) for x in f.invoice_numbers), "")
            review.iban = review.sender_ibans[0] if review.sender_ibans else ""
        return review

    @staticmethod
    def _copy(review: ReviewData, name: str, fv: FieldValue | None) -> None:
        if fv is not None:
            review.confidence[name] = fv.confidence
            if fv.span:
                review.spans[name] = fv.span

    def _notice_claims(self, review: ReviewData, analysis: DocumentAnalysis) -> None:
        """Cumulative claim per invoice; a sender-side deduction (already paid) is reflected in the principal."""
        f = analysis.fields
        invoice_ids = [c.invoice_id for c in analysis.candidates[:1]]
        review.credited_cents = f.amount("already_paid") or 0
        principal = f.amount("principal") or 0
        fees, interest = f.amount("fees") or 0, f.amount("interest") or 0
        flat = f.amount("flat_fee") or 0
        other = (f.amount("collection_costs") or 0) + (f.amount("court_costs") or 0)
        charges = fees + interest + flat + other
        total = f.amount("total_claimed")
        remaining = f.amount("remaining")
        paid = review.credited_cents
        if remaining is not None:
            claim_total = remaining
        elif total is not None and paid and abs(total - (principal + charges)) <= 1:
            claim_total = max(0, total - paid)  # total printed before the deduction
        else:
            claim_total = total if total is not None else principal + charges
        if paid and principal and abs(principal - paid + charges - claim_total) <= 1:
            principal -= paid  # sender already deducted the payment from the principal
        elif not principal and claim_total:
            principal = max(0, claim_total - charges)
        review.total_claimed_cents = claim_total
        self._copy(review, "total_claimed_cents", f.amounts.get("remaining") or f.amounts.get("total_claimed"))
        if len(invoice_ids) == 1:
            review.claims = [ClaimInput(invoice_ids[0], principal, fees, interest, flat, other, claim_total)]
        review.invoice_id = invoice_ids[0] if invoice_ids else None
        if review.supplier_id is None and analysis.candidates:
            review.supplier_id = analysis.candidates[0].supplier_id

    # -- confirmation -------------------------------------------------------------
    def confirm(self, review: ReviewData) -> ConfirmResult:
        """Book the confirmed data in one transaction. Raises on invalid or duplicate input."""
        doc = self.documents.get(review.document_id)
        result = ConfirmResult(kind=review.kind)
        with self.repos.transaction():
            if review.kind == KIND_INVOICE:
                self._confirm_invoice(review, result)
            elif review.kind == KIND_CREDIT:
                self._confirm_credit(review, result)
            elif review.kind == KIND_NOTICE:
                self._confirm_notice(review, result)
            elif review.kind == KIND_PAYMENT:
                self._confirm_payment(review, result)
            elif review.kind != KIND_NONE:
                raise ValidationError("Unbekannte Buchungsart.")
            doc.doc_type = review.doc_type
            doc.supplier_id = review.supplier_id
            doc.review_status = ReviewStatus.ACCEPTED
            self.repos.documents.update(doc)
            self._audit("confirm", "document", doc.id, review.kind)
        return result

    def reject(self, doc_id: int) -> None:
        self.documents.set_review_status(doc_id, ReviewStatus.REJECTED)

    def _ensure_supplier(self, review: ReviewData) -> int:
        if review.supplier_id is not None:
            self._learn_master_data(review.supplier_id, review)
            return review.supplier_id
        name = review.new_supplier_name.strip()
        if not name:
            raise ValidationError("Bitte einen Lieferanten wählen oder einen neuen Namen angeben.")
        ibans = [i for i in review.sender_ibans if valid_iban(i)]
        vat = review.sender_vat_ids[0] if review.sender_vat_ids else ""
        party = self.suppliers.create(Party(name=name, role=PartyRole.SUPPLIER, ibans=ibans[:1], vat_id=vat))
        assert party.id is not None
        review.supplier_id = party.id
        return party.id

    def _learn_master_data(self, supplier_id: int, review: ReviewData) -> None:
        """Remember the printed name as alias and new IBANs of an already known supplier."""
        party = self.suppliers.get(supplier_id)
        changed = False
        printed = review.new_supplier_name.strip()
        if printed and printed != party.name and printed not in party.aliases:
            party.aliases.append(printed)
            changed = True
        if review.kind in (KIND_INVOICE, KIND_CREDIT):
            for iban in review.sender_ibans:
                if valid_iban(iban) and iban not in party.ibans:
                    party.ibans.append(iban)
                    changed = True
        if changed:
            self.suppliers.update(party)

    def _confirm_invoice(self, review: ReviewData, result: ConfirmResult) -> None:
        supplier_id = self._ensure_supplier(review)
        if not review.invoice_number.strip() or review.document_date is None:
            raise ValidationError("Rechnungsnummer und Rechnungsdatum sind Pflichtfelder.")
        invoice = self.invoices.create_invoice(
            supplier_id, review.invoice_number, review.document_date, gross_cents=review.gross_cents,
            net_cents=review.net_cents, vat_cents=review.vat_cents, vat_rate=review.vat_rate,
            due_date=review.due_date, document_id=review.document_id,
            references=[(t, v) for t, v in review.references if t != ReferenceType.INVOICE_NUMBER])
        assert invoice.id is not None
        result.invoice_id = invoice.id
        for ref_type, raw in review.references:
            norm = normalize_reference(raw)
            if norm:
                self.repos.references.add(DocumentReference(
                    EntityKind.DOCUMENT.value, review.document_id, ref_type, raw, norm))

    def _confirm_credit(self, review: ReviewData, result: ConfirmResult) -> None:
        if review.invoice_id is None or review.gross_cents is None or review.document_date is None:
            raise ValidationError("Für eine Gutschrift werden Rechnung, Betrag und Datum benötigt.")
        self.invoices.credit_note(review.invoice_id, review.gross_cents, review.document_date,
                                  f"Gutschrift {review.invoice_number}".strip(), review.document_id)
        result.invoice_id = review.invoice_id

    def _confirm_notice(self, review: ReviewData, result: ConfirmResult) -> None:
        if review.level is None or review.document_date is None or not review.claims:
            raise ValidationError("Für ein Schreiben werden Stufe, Datum und mindestens eine Rechnung benötigt.")
        first = self.repos.invoices.get(review.claims[0].invoice_id)
        supplier_id = review.supplier_id or (first.supplier_id if first else None)
        if supplier_id is None:
            raise ValidationError("Der Lieferant des Schreibens ist unbekannt.")
        sender_id = review.sender_party_id
        if sender_id is None:
            name = review.new_sender_name.strip()
            if not name:
                raise ValidationError("Bitte den Absender wählen oder einen neuen Namen angeben.")
            represents = supplier_id if review.new_sender_role == PartyRole.COLLECTION_AGENCY else None
            ibans = [i for i in review.sender_ibans if valid_iban(i)]
            sender = self.suppliers.create(Party(name=name, role=review.new_sender_role, ibans=ibans[:1],
                                                 represents_supplier_id=represents))
            assert sender.id is not None
            sender_id = sender.id
            review.sender_party_id = sender_id
        draft = NoticeDraft(
            sender_party_id=sender_id, supplier_id=supplier_id, notice_date=review.document_date, level=review.level,
            claims=[NoticeClaim(c.invoice_id, c.principal_cents, c.fees_cents, c.interest_cents, c.flat_fee_cents,
                                c.other_costs_cents, c.total_cents) for c in review.claims],
            new_deadline=review.due_date, total_claimed_cents=review.total_claimed_cents,
            credited_cents=review.credited_cents, document_id=review.document_id, references=list(review.references),
            notes=review.notes)
        booked = self.dunning.book_notice(draft)
        result.notice_id = booked.notice.id
        result.invoice_id = review.claims[0].invoice_id
        result.warnings.extend(booked.warnings)
        result.discrepancies.extend(i.message for i in booked.reconciliation.issues)

    def _confirm_payment(self, review: ReviewData, result: ConfirmResult) -> None:
        if review.supplier_id is None or review.payment_amount_cents is None or review.document_date is None:
            raise ValidationError("Für eine Zahlung werden Lieferant, Betrag und Datum benötigt.")
        payment = self.payments.record_payment(
            review.supplier_id, review.document_date, review.payment_amount_cents, review.payment_invoice_ids,
            method=review.method, bank_reference=review.bank_reference, iban=review.iban, document_id=review.document_id)
        result.payment_id = payment.id
        if review.payment_invoice_ids:
            result.invoice_id = review.payment_invoice_ids[0]


def make_text_extractor(settings: SettingsService) -> TextExtractor:
    return TextExtractor(TesseractRunner(settings.get("tesseract_path")))


__all__ = ["IngestService", "ImportOutcome", "PreparedFile", "make_text_extractor"]
