from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from supplier_app.errors import DuplicateError, LedgerError, NotFoundError, ValidationError
from supplier_app.models.entities import (
    AuditLogEntry,
    Case,
    CaseEvent,
    Document,
    DocumentReference,
    DunningNotice,
    InterestRate,
    Invoice,
    LedgerEntry,
    NoticeInvoiceClaim,
    Party,
    Payment,
    PaymentAllocation,
)
from supplier_app.models.enums import (
    AllocationComponent,
    CaseStatus,
    DocumentType,
    DunningLevel,
    InvoiceStatus,
    LedgerEntryType,
    PartyRole,
    ReferenceType,
    ReviewStatus,
)
from supplier_app.repositories.sqlite_documents import fts_query_from_text
from supplier_app.util.normalize import normalize_reference


def mk_supplier(repos, name="Müller Bürobedarf GmbH", **kw) -> Party:
    return repos.parties.add(Party(name=name, **kw))


def mk_invoice(repos, supplier, number="RE-2024/001", gross=100000) -> Invoice:
    return repos.invoices.add(
        Invoice(supplier_id=supplier.id, invoice_number=number, invoice_date=date(2024, 1, 10),
                due_date=date(2024, 2, 9), gross_cents=gross, net_cents=84034, vat_cents=15966))


def test_party_roundtrip_aliases_ibans(repos) -> None:
    p = mk_supplier(repos, aliases=["Mueller Buero", "MB GmbH"], ibans=["de89 3704 0044 0532 0130 00"],
                    vat_id="DE123456789")
    got = repos.parties.get(p.id)
    assert got.aliases == ["MB GmbH", "Mueller Buero"]
    assert got.ibans == ["DE89370400440532013000"]
    got.aliases = ["Neu"]
    got.notes = "x"
    repos.parties.update(got)
    assert repos.parties.get(p.id).aliases == ["Neu"]
    assert repos.parties.find_by_iban("DE89 3704 0044 0532 0130 00")[0].id == p.id
    assert repos.parties.find_by_vat_id("de 123456789")[0].id == p.id
    assert repos.parties.search_names("mueller")[0].id == p.id
    assert repos.parties.search_names("neu")[0].id == p.id
    assert any(v[1] == "neu" for v in repos.parties.name_variants())
    assert [x.id for x in repos.parties.list(PartyRole.SUPPLIER)] == [p.id]
    assert repos.parties.list(PartyRole.OTHER) == []


def test_collection_agency_represents_supplier(repos) -> None:
    s = mk_supplier(repos)
    a = repos.parties.add(Party(name="Inkasso XY", role=PartyRole.COLLECTION_AGENCY, represents_supplier_id=s.id))
    assert repos.parties.get(a.id).represents_supplier_id == s.id
    bad = Party(name="Nicht Inkasso", role=PartyRole.SUPPLIER, represents_supplier_id=s.id)
    with pytest.raises(DuplicateError):
        repos.parties.add(bad)
    with pytest.raises(DuplicateError):
        repos.parties.add(Party(name="  "))


def test_party_delete_rules(repos) -> None:
    s = mk_supplier(repos)
    other = mk_supplier(repos, "Andere AG")
    mk_invoice(repos, s)
    assert repos.parties.has_dependents(s.id)
    with pytest.raises(DuplicateError):
        repos.parties.delete(s.id)
    repos.parties.delete(other.id)
    assert repos.parties.get(other.id) is None
    with pytest.raises(NotFoundError):
        repos.parties.update(Party(name="x"))


def test_invoice_crud_unique(repos) -> None:
    s = mk_supplier(repos)
    inv = mk_invoice(repos, s)
    assert repos.invoices.get(inv.id).vat_rate == Decimal("19")
    with pytest.raises(DuplicateError):
        mk_invoice(repos, s)
    inv.notes = "n"
    inv.invoice_number = "RE-2024/002"
    repos.invoices.update(inv)
    assert repos.invoices.get_by_number(s.id, "RE-2024/002").id == inv.id
    assert repos.invoices.find_by_number_norm(normalize_reference("re 2024 002"))[0].id == inv.id
    assert repos.invoices.find_by_number_norm("2024", prefix=True)[0].id == inv.id
    assert repos.invoices.find_by_number_norm("") == []
    assert repos.invoices.find_by_gross(100000, s.id)[0].id == inv.id
    repos.invoices.set_status(inv.id, InvoiceStatus.DISPUTED)
    assert repos.invoices.list(status=InvoiceStatus.DISPUTED)[0].id == inv.id
    assert repos.invoices.list(supplier_id=s.id + 99) == []
    # same number for another supplier is fine
    s2 = mk_supplier(repos, "Zweiter GmbH")
    mk_invoice(repos, s2, "RE-2024/002")


def test_ledger_append_list_sums(repos) -> None:
    s = mk_supplier(repos)
    inv = mk_invoice(repos, s)

    def add(t, amt, d=date(2024, 1, 10), **kw):
        return repos.ledger.append(LedgerEntry(entry_date=d, supplier_id=s.id, entry_type=t, category_type=t,
                                               amount_cents=amt, invoice_id=kw.pop("invoice_id", inv.id), **kw))

    e1 = add(LedgerEntry and LedgerEntryType.INVOICE, 100000)
    add(LedgerEntryType.DUNNING_FEE, 500, date(2024, 3, 1))
    add(LedgerEntryType.PAYMENT, -40000, date(2024, 4, 1))
    add(LedgerEntryType.PAYMENT, -1000, date(2024, 4, 2), invoice_id=None)
    assert repos.ledger.count() == 4
    assert len(repos.ledger.list(invoice_id=inv.id)) == 3
    assert len(repos.ledger.list(supplier_id=s.id, date_from=date(2024, 3, 1), date_to=date(2024, 3, 31))) == 1
    sums = {t: v for (_i, _s, t, v) in repos.ledger.sums_by_invoice()}
    assert sums == {"INVOICE": 100000, "DUNNING_FEE": 500, "PAYMENT": -40000}
    assert {t: v for (_i, _s, t, v) in repos.ledger.sums_by_invoice(as_of=date(2024, 3, 15))} == {
        "INVOICE": 100000, "DUNNING_FEE": 500}
    assert repos.ledger.unapplied_by_supplier() == {s.id: -1000}
    assert repos.ledger.unapplied_by_supplier(as_of=date(2024, 1, 1)) == {}
    by_month = {(b, t): v for b, t, v in repos.ledger.sums_by_type(month_buckets=True, supplier_id=s.id)}
    assert by_month[("2024-03", "DUNNING_FEE")] == 500
    assert sum(v for _b, _t, v in repos.ledger.sums_by_type(date_from=date(2024, 1, 1), date_to=date(2024, 12, 31))) == 59500
    # reversal
    assert not repos.ledger.is_reversed(e1.id)
    rev = repos.ledger.append(LedgerEntry(
        entry_date=date(2024, 5, 1), supplier_id=s.id, entry_type=LedgerEntryType.REVERSAL, amount_cents=-100000,
        category_type=LedgerEntryType.INVOICE, invoice_id=inv.id, reverses_entry_id=e1.id))
    assert repos.ledger.is_reversed(e1.id) and repos.ledger.get(rev.id).reverses_entry_id == e1.id
    with pytest.raises(LedgerError):  # a second reversal of the same entry is rejected
        repos.ledger.append(LedgerEntry(
            entry_date=date(2024, 5, 1), supplier_id=s.id, entry_type=LedgerEntryType.REVERSAL,
            amount_cents=-100000, category_type=LedgerEntryType.INVOICE, reverses_entry_id=e1.id))
    with pytest.raises(LedgerError):
        add(LedgerEntryType.PAYMENT, 5)
    assert repos.ledger.get(99999) is None


def test_notice_with_claims_and_dedup(repos) -> None:
    s = mk_supplier(repos)
    agency = repos.parties.add(Party(name="Inkasso XY", role=PartyRole.COLLECTION_AGENCY, represents_supplier_id=s.id))
    inv = mk_invoice(repos, s)
    inv2 = mk_invoice(repos, s, "RE-2")
    n = DunningNotice(
        sender_party_id=agency.id, supplier_id=s.id, notice_date=date(2024, 3, 1), level=DunningLevel.COLLECTION,
        new_deadline=date(2024, 3, 15), principal_cents=2000, fees_cents=500, total_claimed_cents=2500,
        claims=[NoticeInvoiceClaim(invoice_id=inv.id, principal_cents=1000, total_cents=1000),
                NoticeInvoiceClaim(invoice_id=inv2.id, principal_cents=1000, fees_cents=500, total_cents=1500)])
    repos.notices.add(n, "key1")
    got = repos.notices.get(n.id)
    assert got.level == DunningLevel.COLLECTION and len(got.claims) == 2
    assert repos.notices.find_by_dedup_key("key1").id == n.id
    assert repos.notices.find_by_dedup_key("nope") is None
    with pytest.raises(DuplicateError):
        repos.notices.add(DunningNotice(sender_party_id=agency.id, supplier_id=s.id, notice_date=date(2024, 3, 1),
                                        level=DunningLevel.FIRST), "key1")
    assert repos.notices.list(invoice_id=inv2.id)[0].id == n.id
    assert repos.notices.list(supplier_id=s.id + 1) == []
    case = repos.cases.add(Case(supplier_id=s.id, invoice_id=inv.id, title="t"))
    repos.notices.set_case(n.id, case.id)
    assert repos.notices.list(case_id=case.id)[0].id == n.id


def test_payments_and_allocations(repos) -> None:
    s = mk_supplier(repos)
    inv = mk_invoice(repos, s)
    p = repos.payments.add(Payment(supplier_id=s.id, payment_date=date(2024, 4, 1), amount_cents=40000,
                                   bank_reference="RE-2024/001"))
    repos.payments.add_allocation(PaymentAllocation(p.id, inv.id, AllocationComponent.COSTS, 1500))
    repos.payments.add_allocation(PaymentAllocation(p.id, inv.id, AllocationComponent.PRINCIPAL, 38500))
    assert repos.payments.get(p.id).bank_reference == "RE-2024/001"
    assert len(repos.payments.allocations(payment_id=p.id)) == 2
    assert len(repos.payments.allocations(invoice_id=inv.id)) == 2
    sums = {c: v for _i, c, v in repos.payments.allocation_sums()}
    assert sums == {"costs": 1500, "principal": 38500}
    assert repos.payments.allocation_sums(as_of=date(2024, 3, 1)) == []
    assert repos.payments.list(date_from=date(2024, 4, 1), date_to=date(2024, 4, 30))[0].id == p.id
    assert repos.payments.list(supplier_id=s.id + 1) == []


def test_documents_fts_and_references(repos) -> None:
    doc = repos.documents.add(Document(stored_path="a.pdf", sha256="a" * 64, original_name="Mahnung.pdf",
                                       ocr_text="Bearbeitungsnummer 4711 Zahlungserinnerung Überweisung"))
    with pytest.raises(DuplicateError):
        repos.documents.add(Document(stored_path="b.pdf", sha256="a" * 64, original_name="b.pdf"))
    assert repos.documents.get_by_hash("a" * 64).id == doc.id
    hits = repos.documents.fulltext(fts_query_from_text("zahlungserinn"))
    assert hits and hits[0][0] == doc.id and "[" in hits[0][1]
    assert repos.documents.fulltext(fts_query_from_text("ueberweisung")) == []  # umlaut folding is ü->u, not ue
    assert repos.documents.fulltext(fts_query_from_text("uberweisung"))
    doc.ocr_text = "ganz anderer Text"
    doc.doc_type = DocumentType.INVOICE
    doc.review_status = ReviewStatus.NEEDS_REVIEW
    repos.documents.update(doc)
    assert repos.documents.fulltext(fts_query_from_text("zahlungserinnerung")) == []
    assert repos.documents.fulltext(fts_query_from_text("anderer"))
    assert repos.documents.count_by_status() == {"needs_review": 1}
    assert len(repos.documents.list(review_status=ReviewStatus.NEEDS_REVIEW, limit=5)) == 1
    with pytest.raises(ValidationError):
        repos.documents.fulltext('"unterminated')

    ref = DocumentReference("document", doc.id, ReferenceType.PROCESSING_NUMBER, "4711/A",
                            normalize_reference("4711/A"))
    assert repos.references.add(ref) is not None
    assert repos.references.add(DocumentReference("document", doc.id, ReferenceType.PROCESSING_NUMBER, "4711-a",
                                                  normalize_reference("4711-a"))) is None
    assert repos.references.for_owner("document", doc.id)[0].raw_value == "4711/A"
    assert repos.references.find("4711A")[0].owner_id == doc.id
    assert repos.references.find("711", prefix=True)
    assert repos.references.find("") == []


def test_cases_events_settings_rates_categories_audit(repos) -> None:
    s = mk_supplier(repos)
    inv = mk_invoice(repos, s)
    c = repos.cases.add(Case(supplier_id=s.id, invoice_id=inv.id, title="Fall"))
    with pytest.raises(DuplicateError):
        repos.cases.add(Case(supplier_id=s.id, invoice_id=inv.id))
    c.status = CaseStatus.CLOSED
    repos.cases.update(c)
    assert repos.cases.get_by_invoice(inv.id).status == CaseStatus.CLOSED
    assert repos.cases.list(status="closed")[0].id == c.id and repos.cases.list(supplier_id=s.id + 1) == []
    repos.cases.add_event(CaseEvent(c.id, date(2024, 1, 1), "note", "Hallo"))
    assert repos.cases.events(c.id)[0].text == "Hallo"

    assert repos.settings.get("x") is None and repos.settings.get("x", "d") == "d"
    repos.settings.set("x", "1")
    repos.settings.set("x", "2")
    assert repos.settings.all() == {"x": "2"}
    repos.settings.delete("x")
    assert repos.settings.all() == {}

    repos.rates.upsert(InterestRate(date(2024, 1, 1), Decimal("3.62")))
    repos.rates.upsert(InterestRate(date(2024, 1, 1), Decimal("3.70")))
    assert [r.base_rate for r in repos.rates.list()] == [Decimal("3.70")]
    repos.rates.delete(date(2024, 1, 1))
    assert repos.rates.list() == []

    cat = repos.categories.add("Büro")
    with pytest.raises(DuplicateError):
        repos.categories.add("Büro")
    assert repos.categories.list()[0].name == "Büro"
    repos.categories.delete(cat.id)
    assert repos.categories.list() == []

    repos.audit.add(AuditLogEntry("create", "invoice", inv.id, "x"))
    assert repos.audit.list(entity="invoice")[0].action == "create"
    assert repos.audit.list(entity="nope") == []
    with repos.transaction():
        repos.settings.set("t", "1")
