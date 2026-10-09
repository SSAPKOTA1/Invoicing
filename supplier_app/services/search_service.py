"""Global search: suppliers, invoices, cases and documents from one query string."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from supplier_app.errors import ValidationError
from supplier_app.i18n import tr
from supplier_app.repositories.interfaces import Repositories
from supplier_app.repositories.sqlite_documents import fts_query_from_text
from supplier_app.services.base import ServiceBase
from supplier_app.util.money import format_cents, parse_amount
from supplier_app.util.normalize import normalize_iban, normalize_name, normalize_reference

_AMOUNT_RE = re.compile(r"^\s*[\d][\d.,' ]*\s*(€|eur)?\s*$", re.I)
_IBAN_RE = re.compile(r"^[A-Za-z]{2}\d{2}[A-Za-z0-9 ]{10,32}$")


@dataclass
class SearchHit:
    kind: str  # supplier | invoice | case | document
    entity_id: int
    title: str
    subtitle: str = ""
    reason: str = ""
    snippet: str = ""


@dataclass
class SearchResults:
    query: str
    suppliers: list[SearchHit] = field(default_factory=list)
    invoices: list[SearchHit] = field(default_factory=list)
    cases: list[SearchHit] = field(default_factory=list)
    documents: list[SearchHit] = field(default_factory=list)

    @property
    def total(self) -> int:
        return len(self.suppliers) + len(self.invoices) + len(self.cases) + len(self.documents)

    def invoice_ids(self) -> list[int]:
        return [h.entity_id for h in self.invoices]


class SearchService(ServiceBase):
    def __init__(self, repos: Repositories) -> None:
        super().__init__(repos)

    def search(self, query: str, limit: int = 50) -> SearchResults:
        q = query.strip()
        res = SearchResults(query=q)
        if not q:
            return res
        ref_norm = normalize_reference(q)
        name_norm = normalize_name(q)
        invoice_reasons: dict[int, str] = {}
        supplier_reasons: dict[int, str] = {}
        case_reasons: dict[int, str] = {}
        doc_hits: dict[int, SearchHit] = {}

        # suppliers by name / alias / IBAN / VAT id
        if name_norm:
            for p in self.repos.parties.search_names(name_norm):
                assert p.id is not None
                supplier_reasons[p.id] = tr("search.reason.name")
        if _IBAN_RE.match(q):
            for p in self.repos.parties.find_by_iban(normalize_iban(q)):
                assert p.id is not None
                supplier_reasons.setdefault(p.id, "IBAN")
        for p in self.repos.parties.find_by_vat_id(q) if len(q) >= 8 else []:
            assert p.id is not None
            supplier_reasons.setdefault(p.id, "USt-IdNr.")

        # invoices by number
        if ref_norm:
            for inv in self.repos.invoices.find_by_number_norm(ref_norm, prefix=len(ref_norm) >= 3):
                assert inv.id is not None
                invoice_reasons.setdefault(inv.id, f"{tr('ref.invoice_number')} {inv.invoice_number}")
            # references of any type
            for ref in self.repos.references.find(ref_norm, prefix=len(ref_norm) >= 4):
                label = f"{tr(f'ref.{ref.ref_type.value}')} {ref.raw_value}"
                if ref.owner_kind == "invoice":
                    invoice_reasons.setdefault(ref.owner_id, label)
                elif ref.owner_kind == "case":
                    case = self.repos.cases.get(ref.owner_id)
                    if case:
                        case_reasons.setdefault(ref.owner_id, label)
                        if case.invoice_id:
                            invoice_reasons.setdefault(case.invoice_id, label)
                elif ref.owner_kind == "document":
                    doc = self.repos.documents.get(ref.owner_id)
                    if doc and doc.id not in doc_hits:
                        doc_hits[doc.id or 0] = SearchHit("document", doc.id or 0, doc.original_name,
                                                          tr(f"doctype.{doc.doc_type.value}"), label)

        # amounts
        if _AMOUNT_RE.match(q) and re.search(r"\d", q):
            try:
                cents = parse_amount(q)
            except ValidationError:
                cents = 0
            if cents > 0:
                for inv in self.repos.invoices.find_by_gross(cents):
                    assert inv.id is not None
                    invoice_reasons.setdefault(inv.id, f"{tr('search.reason.amount')} {format_cents(cents)}")
                for pay in self.repos.payments.list():
                    if pay.amount_cents == cents:
                        for alloc in self.repos.payments.allocations(payment_id=pay.id):
                            invoice_reasons.setdefault(alloc.invoice_id, f"{tr('search.reason.payment')} {format_cents(cents)}")

        # all invoices of a matched supplier
        for sid, why in list(supplier_reasons.items()):
            for inv in self.repos.invoices.list(supplier_id=sid):
                assert inv.id is not None
                invoice_reasons.setdefault(inv.id, why)

        # full text in documents
        fts = fts_query_from_text(q)
        if fts:
            for doc_id, snippet in self.repos.documents.fulltext(fts, limit):
                doc = self.repos.documents.get(doc_id)
                if doc and doc_id not in doc_hits:
                    doc_hits[doc_id] = SearchHit("document", doc_id, doc.original_name,
                                                 tr(f"doctype.{doc.doc_type.value}"), tr("search.reason.text"), snippet)

        # cases of found invoices
        for inv_id in invoice_reasons:
            case = self.repos.cases.get_by_invoice(inv_id)
            if case and case.id:
                case_reasons.setdefault(case.id, invoice_reasons[inv_id])

        self._fill(res, supplier_reasons, invoice_reasons, case_reasons, doc_hits, limit)
        return res

    def _fill(
        self, res: SearchResults, suppliers: dict[int, str], invoices: dict[int, str], cases: dict[int, str],
        docs: dict[int, SearchHit], limit: int,
    ) -> None:
        for sid, why in list(suppliers.items())[:limit]:
            p = self.repos.parties.get(sid)
            if p:
                res.suppliers.append(SearchHit("supplier", sid, p.name, tr(f"role.{p.role.value}"), why))
        for iid, why in list(invoices.items())[:limit]:
            inv = self.repos.invoices.get(iid)
            if inv:
                sup = self.repos.parties.get(inv.supplier_id)
                res.invoices.append(SearchHit(
                    "invoice", iid, f"{sup.name if sup else ''} – {inv.invoice_number}",
                    f"{format_cents(inv.gross_cents)} · {tr(f'status.{inv.status.value}')}", why))
        for cid, why in list(cases.items())[:limit]:
            case = self.repos.cases.get(cid)
            if case:
                res.cases.append(SearchHit("case", cid, case.title or f"Vorgang {cid}",
                                           tr(f"case.{case.status.value}"), why))
        res.documents.extend(list(docs.values())[:limit])
