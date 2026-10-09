"""Link a document to the invoice(s) it belongs to (number, known references, amount, date, supplier)."""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass, field

from supplier_app.models.entities import Invoice
from supplier_app.models.enums import DocumentType as D
from supplier_app.repositories.interfaces import Repositories
from supplier_app.services.ledger_service import LedgerService
from supplier_app.util.money import format_cents
from supplier_app.util.normalize import normalize_reference

from .interfaces import LinkMatcher
from .result_types import Classification, ExtractedFields, LinkCandidate, SenderMatch

_TOKEN_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9\-/._]*\d[A-Za-z0-9\-/._]*")
MIN_SCORE = 0.3
MAX_CANDIDATES = 6


@dataclass
class _Acc:
    invoice: Invoice
    score: float = 0.0
    reasons: list[str] = field(default_factory=list)

    def add(self, points: float, reason: str) -> None:
        self.score += points
        self.reasons.append(reason)


class RuleLinkMatcher(LinkMatcher):
    def __init__(self, repos: Repositories, ledger: LedgerService) -> None:
        self.repos = repos
        self.ledger = ledger

    def match(
        self, text: str, fields: ExtractedFields, classification: Classification, sender: SenderMatch | None
    ) -> Sequence[LinkCandidate]:
        acc: dict[int, _Acc] = {}
        supplier_id = sender.supplier_id if sender else None

        def get(inv: Invoice) -> _Acc:
            assert inv.id is not None
            return acc.setdefault(inv.id, _Acc(inv))

        labelled = {normalize_reference(str(f.value)) for f in fields.invoice_numbers}
        tokens = {normalize_reference(t.rstrip(".,;:")) for t in _TOKEN_RE.findall(text)}
        for norm in list(tokens | labelled)[:400]:
            if len(norm) < 4:
                continue
            for inv in self.repos.invoices.find_by_number_norm(norm):
                strong = norm in labelled
                get(inv).add(0.6 if strong else 0.45, f"Rechnungsnummer {inv.invoice_number} im Dokument")
        for ref in fields.references:
            norm = normalize_reference(ref.raw)
            if len(norm) < 3:
                continue
            for hit in self.repos.references.find(norm):
                inv_id: int | None = None
                if hit.owner_kind == "invoice":
                    inv_id = hit.owner_id
                elif hit.owner_kind == "case":
                    case = self.repos.cases.get(hit.owner_id)
                    inv_id = case.invoice_id if case else None
                if inv_id is not None:
                    inv = self.repos.invoices.get(inv_id)
                    if inv is not None:
                        get(inv).add(0.5, f"bekannte Referenz {ref.raw}")
        compact = normalize_reference(text)
        pool = self.repos.invoices.list(supplier_id=supplier_id)[-5000:]
        for inv in pool:
            if supplier_id is not None:
                get(inv)  # supplier's invoices are candidates for amount/date evidence
            number = normalize_reference(inv.invoice_number)
            if len(number) >= 6 and number in compact and not any(
                    r.startswith("Rechnungsnummer") for r in (acc[inv.id].reasons if inv.id in acc else [])):
                get(inv).add(0.4, f"Rechnungsnummer {inv.invoice_number} (abweichende Schreibweise)")
        amounts = {k: fields.amount(k) for k in ("principal", "gross", "total_claimed", "payment_amount", "remaining")}
        ref_dates = {f.value for f in fields.referenced_invoice_dates}
        out: list[LinkCandidate] = []
        for entry in acc.values():
            inv = entry.invoice
            if supplier_id is not None:
                if inv.supplier_id == supplier_id:
                    entry.add(0.15, "gleicher Lieferant")
                elif entry.score > 0:
                    entry.score -= 0.3
                    entry.reasons.append("anderer Lieferant")
            if entry.score <= 0:
                continue
            if inv.gross_cents in {v for k, v in amounts.items() if v and k in ("principal", "gross")}:
                entry.add(0.2, f"Betrag {format_cents(inv.gross_cents)} entspricht der Rechnung")
            if inv.invoice_date in ref_dates:
                entry.add(0.15, "Rechnungsdatum stimmt überein")
            if classification.doc_type == D.BANK_STATEMENT and amounts["payment_amount"]:
                bal = self.ledger.invoice_balance(inv.id or 0).balance_cents
                if bal == amounts["payment_amount"]:
                    entry.add(0.15, "Zahlung entspricht dem offenen Betrag")
            if entry.score >= MIN_SCORE:
                out.append(LinkCandidate(inv.id or 0, round(min(1.0, entry.score), 3), entry.reasons, inv.supplier_id,
                                         inv.invoice_number))
        out.sort(key=lambda c: c.score, reverse=True)
        return out[:MAX_CANDIDATES]
