"""Recognition pipeline: classify -> extract -> sender -> link -> validate -> confidence."""

from __future__ import annotations

from supplier_app.models.enums import DocumentType as D
from supplier_app.repositories.interfaces import Repositories
from supplier_app.services.ledger_service import LedgerService
from supplier_app.services.settings_service import SettingsService

from .classifier import KeywordClassifier
from .fields import RegexFieldExtractor
from .interfaces import DocumentClassifier, FieldExtractor, LinkMatcher, SenderMatcher
from .linker import RuleLinkMatcher
from .references import LabelledReferenceExtractor
from .result_types import DocumentAnalysis, ExtractedFields, SenderMatch, ValidationIssue
from .sender import RuleSenderMatcher
from .validation import validate_fields

_KEY_FIELDS: dict[D, tuple[str, ...]] = {
    D.INVOICE: ("invoice_number", "document_date", "gross", "sender"),
    D.CREDIT_NOTE: ("document_date", "gross", "sender"),
    D.BANK_STATEMENT: ("payment_date", "payment_amount", "invoice"),
}
_DUNNING = (D.PAYMENT_REMINDER, D.FIRST_DUNNING, D.SECOND_DUNNING, D.FINAL_DUNNING, D.COLLECTION_LETTER, D.COURT_ORDER)


def _presence(key: str, fields: ExtractedFields, sender: SenderMatch | None, linked: bool) -> bool:
    return {
        "invoice_number": bool(fields.invoice_numbers), "document_date": fields.document_date is not None,
        "gross": fields.amount("gross") is not None, "sender": sender is not None,
        "payment_date": fields.payment_date is not None or fields.document_date is not None,
        "payment_amount": fields.amount("payment_amount") is not None, "invoice": linked or bool(fields.invoice_numbers),
        "total": fields.amount("total_claimed") is not None or fields.amount("remaining") is not None,
    }[key]


class AnalysisPipeline:
    """Runs all recognition components. Components are injected (interfaces in ``interfaces.py``)."""

    def __init__(
        self, classifier: DocumentClassifier, extractor: FieldExtractor, sender_matcher: SenderMatcher,
        link_matcher: LinkMatcher,
    ) -> None:
        self.classifier = classifier
        self.extractor = extractor
        self.sender_matcher = sender_matcher
        self.link_matcher = link_matcher

    def analyze(self, text: str) -> DocumentAnalysis:
        classification = self.classifier.classify(text)
        fields = self.extractor.extract(text, classification)
        sender = self.sender_matcher.match(text, fields, classification)
        candidates = list(self.link_matcher.match(text, fields, classification, sender))
        issues = validate_fields(fields, classification)
        dtype = classification.doc_type
        if dtype == D.INVOICE and fields.invoice_numbers and sender and sender.supplier_id:
            for c in candidates:
                if c.supplier_id == sender.supplier_id and any(
                        r.startswith("Rechnungsnummer") for r in c.reasons):
                    issues.append(ValidationIssue(
                        "DUPLICATE_INVOICE", f"Rechnung {c.invoice_number} ist bereits erfasst.", "invoice_number"))
                    break
        if dtype in _DUNNING + (D.BANK_STATEMENT,) and not candidates:
            issues.append(ValidationIssue("NO_LINK", "Keine passende Rechnung gefunden. Bitte manuell zuordnen.", "invoice", "error"))
        if dtype in _DUNNING and sender is not None and sender.supplier_id is None:
            issues.append(ValidationIssue("NO_SUPPLIER", "Der Lieferant des Schreibens ist unbekannt.", "supplier", "error"))
        keys = _KEY_FIELDS.get(dtype) or (("document_date", "total", "invoice") if dtype in _DUNNING else ())
        linked = bool(candidates)
        coverage = (sum(_presence(k, fields, sender, linked) for k in keys) / len(keys)) if keys else 0.5
        link_conf = max((c.score for c in candidates), default=0.0) if dtype in _DUNNING + (D.BANK_STATEMENT,) else \
            (sender.score if sender else 0.2)
        overall = 0.4 * classification.confidence + 0.35 * coverage + 0.25 * min(1.0, link_conf)
        overall -= 0.12 * sum(1 for i in issues if i.severity == "error") + 0.05 * sum(1 for i in issues if i.severity == "warning")
        overall = max(0.0, min(1.0, overall))
        return DocumentAnalysis(len(text), classification, fields, sender, candidates, issues, round(overall, 3))


def build_default_pipeline(repos: Repositories, ledger: LedgerService, settings: SettingsService) -> AnalysisPipeline:
    """Rule based pipeline wired to the master data."""
    return AnalysisPipeline(
        KeywordClassifier(),
        RegexFieldExtractor(LabelledReferenceExtractor(settings.reference_rules())),
        RuleSenderMatcher(repos.parties),
        RuleLinkMatcher(repos, ledger),
    )
