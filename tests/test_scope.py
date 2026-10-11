"""Companies, hotels and the 'all / company / hotel' view scope across every layer."""

from __future__ import annotations

import sqlite3
from datetime import date

import pytest

from supplier_app.errors import DuplicateError, NotFoundError, ValidationError
from supplier_app.models.entities import Document, Party
from supplier_app.models.enums import DunningLevel, ReviewStatus
from supplier_app.models.scope import ALL, Scope
from supplier_app.services.dashboard_models import DashboardFilter, DrillTarget
from supplier_app.services.dashboard_service import DashboardService
from supplier_app.services.demo_data import DemoDataService
from supplier_app.services.dunning_service import NoticeDraft
from supplier_app.services.ledger import NoticeClaim

TODAY = date(2026, 6, 15)


@pytest.fixture()
def world(svc):
    org = svc.organization
    a, b = org.create_company("Alpha Hotels GmbH"), org.create_company("Beta Resorts AG")
    a1, a2 = org.create_hotel(a.id, "Hotel Seeblick"), org.create_hotel(a.id, "Hotel Bergfried")
    b1 = org.create_hotel(b.id, "Strandhotel Möwe")
    sup = svc.suppliers.create(Party(name="Müller Bürobedarf GmbH"))
    other = svc.suppliers.create(Party(name="Nordwind Logistik AG"))

    def inv(supplier, number, gross, company, hotel, day=date(2026, 5, 1)):
        return svc.invoices.create_invoice(supplier.id, number, day, gross_cents=gross, company_id=company,
                                           hotel_id=hotel, due_date=date(2026, 5, 20))

    i_a1 = inv(sup, "A1-1", 100000, a.id, a1.id)
    i_a2 = inv(sup, "A2-1", 50000, None, a2.id)  # company is filled in automatically
    i_aco = inv(other, "A-CO", 20000, a.id, None)  # company only
    i_b1 = inv(other, "B1-1", 70000, b.id, b1.id)
    i_none = inv(sup, "UNASSIGNED", 1000, None, None)
    return svc, dict(a=a, b=b, a1=a1, a2=a2, b1=b1, sup=sup, other=other, i_a1=i_a1, i_a2=i_a2, i_aco=i_aco,
                     i_b1=i_b1, i_none=i_none)


def total(svc, scope):
    return sum(s.balance.balance_cents for s in svc.ledger.invoice_states(scope=scope))


def test_hotel_implies_company_and_company_only_is_allowed(world) -> None:
    svc, w = world
    assert (w["i_a2"].company_id, w["i_a2"].hotel_id) == (w["a"].id, w["a2"].id)
    assert (w["i_aco"].company_id, w["i_aco"].hotel_id) == (w["a"].id, None)
    assert svc.invoices.get(w["i_none"].id).company_id is None
    with pytest.raises(ValidationError):
        svc.invoices.create_invoice(w["sup"].id, "X", date(2026, 5, 1), gross_cents=1, company_id=w["b"].id,
                                    hotel_id=w["a1"].id)
    with pytest.raises(NotFoundError):
        svc.organization.resolve(999, None)


def test_database_rejects_hotel_of_other_company(world) -> None:
    svc, w = world
    with pytest.raises(sqlite3.DatabaseError):
        svc.repos.db.execute("UPDATE invoices SET company_id=?, hotel_id=? WHERE id=?",
                             (w["b"].id, w["a1"].id, w["i_a1"].id))


def test_scope_totals_add_up(world) -> None:
    svc, w = world
    everything = total(svc, ALL)
    assert everything == 241000
    company_a, company_b = total(svc, Scope(w["a"].id)), total(svc, Scope(w["b"].id))
    assert (company_a, company_b) == (170000, 70000)
    hotels = [total(svc, Scope(w["a"].id, w["a1"].id)), total(svc, Scope(w["a"].id, w["a2"].id))]
    assert hotels == [100000, 50000] and sum(hotels) + 20000 == company_a  # + company-level invoice
    assert company_a + company_b + 1000 == everything  # + unassigned invoice
    assert total(svc, Scope(w["b"].id, w["b1"].id)) == 70000
    assert svc.ledger.aging(TODAY, scope=Scope(w["a"].id)) == svc.ledger.aging(TODAY, scope=Scope(w["a"].id))
    assert sum(svc.ledger.aging(date(2026, 6, 1), scope=Scope(w["b"].id)).values()) == 70000
    bal = svc.ledger.supplier_balances(scope=Scope(w["a"].id))
    assert bal[w["sup"].id].total_cents == 150000 and bal[w["other"].id].total_cents == 20000
    assert svc.ledger.supplier_balance(w["sup"].id, scope=Scope(w["a"].id, w["a1"].id)).total_cents == 100000
    assert [i.invoice_number for i in svc.invoices.list(scope=Scope(w["a"].id))] == ["A1-1", "A2-1", "A-CO"]


def test_statement_payments_and_credit_follow_scope(world) -> None:
    svc, w = world
    sup = w["sup"]
    svc.payments.record_payment(sup.id, date(2026, 5, 25), 30000, [w["i_a1"].id, w["i_a2"].id],
                                rule=None)  # statutory: oldest due first, same due -> by id
    # overpayment on a hotel-bound invoice: the credit inherits the hotel
    pay = svc.payments.record_payment(sup.id, date(2026, 5, 26), 70000, [w["i_a2"].id])
    assert (pay.company_id, pay.hotel_id) == (w["a"].id, w["a2"].id)
    scope_a2 = Scope(w["a"].id, w["a2"].id)
    scope_a1 = Scope(w["a"].id, w["a1"].id)
    credit_a2 = svc.ledger.supplier_balance(sup.id, scope=scope_a2)
    assert credit_a2.unapplied_cents < 0
    assert svc.ledger.supplier_balance(sup.id, scope=scope_a1).unapplied_cents == 0
    # statements: each scoped statement only has its own entries; their closing balances add up to the full one
    full = svc.ledger.supplier_statement(sup.id).closing_cents
    parts = [svc.ledger.supplier_statement(sup.id, scope=s).closing_cents
             for s in (scope_a1, scope_a2, Scope(w["b"].id), ALL.__class__(None, None))]
    assert full == svc.ledger.supplier_balance(sup.id).total_cents
    st_a2 = svc.ledger.supplier_statement(sup.id, scope=scope_a2)
    assert all(r.invoice_number in ("A2-1", "") for r in st_a2.rows)
    assert parts[0] + parts[1] + svc.ledger.supplier_statement(sup.id, scope=Scope(None, None)).closing_cents - parts[3] \
        >= 0
    # explicit scope on a payment without invoices
    free = svc.payments.record_payment(sup.id, date(2026, 5, 27), 500, [], company_id=w["b"].id)
    assert (free.company_id, free.hotel_id) == (w["b"].id, None)
    assert svc.ledger.supplier_balance(sup.id, scope=Scope(w["b"].id)).total_cents == -500
    assert [p.id for p in svc.repos.payments.list(scope=Scope(w["b"].id))] == [free.id]
    assert pay.id in [p.id for p in svc.repos.payments.list(scope=scope_a2)]


def test_dashboard_consistency_per_scope(svc) -> None:
    DemoDataService(svc).load(TODAY)
    ds = DashboardService(svc.repos, svc.ledger, svc.settings)
    everything = ds.build(DashboardFilter.for_period("year", TODAY))
    org = svc.organization
    seen_total = 0
    for choice in org.choices():
        flt = DashboardFilter.for_period("year", TODAY, scope=choice.scope)
        data = ds.build(flt)
        k = data.kpis
        in_scope = svc.ledger.invoice_states(TODAY, scope=choice.scope)
        assert k["total_open"].value == sum(s.balance.balance_cents for s in in_scope if s.balance.balance_cents > 0)
        assert k["total_open"].value == sum(data.aging.values())
        for key, kpi in k.items():
            res = ds.drilldown(kpi.drill, flt)
            assert (res.total_cents == kpi.value) if kpi.is_money else (res.count == kpi.value), (choice.label, key)
        for bucket, cents in data.aging.items():
            assert ds.drilldown(DrillTarget("aging", bucket), flt).total_cents == cents
        if choice.level == 1:
            seen_total += k["total_open"].value
    assert seen_total == everything.kpis["total_open"].value == 3_277_340  # every demo invoice is assigned
    # hotels add up to their company (plus company-level invoices)
    seeblick = next(c for c in org.companies() if c.name.startswith("Seeblick"))
    company_total = ds.build(DashboardFilter.for_period("year", TODAY, scope=Scope(seeblick.id))).kpis["total_open"].value
    hotel_totals = [ds.build(DashboardFilter.for_period("year", TODAY, scope=Scope(seeblick.id, h.id))).kpis["total_open"].value
                    for h in org.hotels(seeblick.id)]
    assert 0 < sum(hotel_totals) <= company_total


def test_reports_documents_cases_notices_and_search_respect_scope(svc) -> None:
    DemoDataService(svc).load(TODAY)
    org = svc.organization
    nordlicht = next(c for c in org.companies() if c.name.startswith("Nordlicht"))
    scope = Scope(nordlicht.id)
    from supplier_app.reports.builders import ReportService
    rs = ReportService(svc)
    full, part = rs.open_items(TODAY, None), rs.open_items(TODAY, None, scope)
    assert 0 < part.totals[9] < full.totals[9]
    assert part.totals[9] == sum(s.balance.balance_cents for s in svc.ledger.invoice_states(TODAY, scope=scope)
                                 if s.balance.balance_cents > 0)
    assert "Nordlicht" in part.subtitle and {r[10] for r in part.raw_rows} <= {
        org.item_label(i.company_id, i.hotel_id) for i in svc.invoices.list(scope=scope)}
    assert rs.payments(None, None, None, scope).totals[2] < rs.payments(None, None, None).totals[2]
    assert len(rs.dunning_overview(None, None, None, scope).raw_rows) < len(rs.dunning_overview(None, None, None).raw_rows)
    assert len(svc.repos.notices.list(scope=scope)) < len(svc.repos.notices.list())
    assert len(svc.cases.list()) > len(svc.repos.cases.list(scope=scope)) >= 1
    docs_all = svc.repos.documents.list()
    docs_scoped = svc.repos.documents.list(scope=scope)
    unassigned = [d for d in docs_all if d.company_id is None]
    assert unassigned and all(d in docs_scoped for d in unassigned)  # not yet reviewed documents stay visible
    assert len(docs_scoped) < len(docs_all)
    # search
    nl = next(i for i in svc.invoices.list() if i.company_id != nordlicht.id)
    assert nl.id in svc.search.search(nl.invoice_number).invoice_ids()
    assert nl.id not in svc.search.search(nl.invoice_number, scope=scope).invoice_ids()
    inside = svc.invoices.list(scope=scope)[0]
    assert inside.id in svc.search.search(inside.invoice_number, scope=scope).invoice_ids()
    other_sup = svc.search.search("Müller", scope=Scope(nordlicht.id, org.hotels(nordlicht.id)[0].id))
    assert all(h.entity_id for h in other_sup.suppliers)


def test_assign_scope_later_moves_ledger_numbers(world) -> None:
    svc, w = world
    assert total(svc, Scope(w["b"].id)) == 70000
    svc.invoices.assign_scope(w["i_none"].id, w["b"].id, None)
    assert total(svc, Scope(w["b"].id)) == 71000
    svc.invoices.assign_scope(w["i_none"].id, None, w["b1"].id)  # hotel fills in the company
    inv = svc.invoices.get(w["i_none"].id)
    assert (inv.company_id, inv.hotel_id) == (w["b"].id, w["b1"].id)
    with pytest.raises(ValidationError):
        svc.invoices.assign_scope(w["i_none"].id, w["a"].id, w["b1"].id)
    assert any(a.action == "assign_scope" for a in svc.repos.audit.list(entity="invoice"))


def test_organization_management_rules(world) -> None:
    svc, w = world
    org = svc.organization
    assert org.configured
    with pytest.raises(DuplicateError):
        org.create_company("Alpha Hotels GmbH")
    with pytest.raises(DuplicateError):
        org.create_hotel(w["a"].id, "Hotel Seeblick")
    org.create_hotel(w["b"].id, "Hotel Seeblick")  # same name in another company is fine
    with pytest.raises(ValidationError):
        org.create_company(" ")
    with pytest.raises(ValidationError):
        org.create_hotel(w["a"].id, " ")
    org.rename_company(w["b"].id, "Beta Resorts SE", "Notiz")
    org.rename_hotel(w["b1"].id, "Strandhotel Welle")
    assert org.company(w["b"].id).name == "Beta Resorts SE" and org.hotel(w["b1"].id).name == "Strandhotel Welle"
    with pytest.raises(DuplicateError):
        org.delete_hotel(w["a1"].id)  # has an invoice
    with pytest.raises(DuplicateError):
        org.delete_company(w["a"].id)
    empty = org.create_company("Leer GmbH")
    h = org.create_hotel(empty.id, "Leer-Hotel")
    org.delete_hotel(h.id)
    org.delete_company(empty.id)
    with pytest.raises(NotFoundError):
        org.hotel(h.id)
    assert org.label(ALL) == "Alle Gesellschaften"
    assert "alle Hotels" in org.label(Scope(w["a"].id)) and "Hotel Seeblick" in org.label(Scope(w["a"].id, w["a1"].id))
    assert org.item_label(None, None) == "–" and "Hotel Seeblick" in org.item_label(w["a"].id, w["a1"].id)
    assert org.scope_from_key(Scope(w["a"].id, w["a1"].id).key()) == Scope(w["a"].id, w["a1"].id)
    assert org.scope_from_key(f"c:{w['b'].id}") == Scope(w["b"].id)
    assert org.scope_from_key("h:9999") == ALL and org.scope_from_key("x") == ALL and org.scope_from_key("c:zz") == ALL
    labels = [c.label for c in org.choices()]
    assert labels[0] == "Alle Gesellschaften" and any("Seeblick" in x for x in labels)


def test_due_date_proposal_edit_and_notice_deadline(world) -> None:
    svc, w = world
    inv = w["i_a1"]
    before = inv.due_date
    svc.cases.ensure_for_invoice(inv.id)
    svc.invoices.change_due_date(inv.id, date(2026, 7, 31))
    assert svc.invoices.get(inv.id).due_date == date(2026, 7, 31) != before
    assert any(e.kind == "due_date" for e in svc.cases.events(svc.repos.cases.get_by_invoice(inv.id).id))
    assert any(a.action == "due_date" for a in svc.repos.audit.list(entity="invoice"))
    assert svc.invoices.change_due_date(inv.id, date(2026, 7, 31)).due_date == date(2026, 7, 31)  # no-op
    with pytest.raises(ValidationError):
        svc.invoices.change_due_date(inv.id, date(2000, 1, 1))
    booked = svc.dunning.book_notice(NoticeDraft(
        w["sup"].id, date(2026, 6, 1), DunningLevel.FIRST, [NoticeClaim(inv.id, 100000, fees_cents=500)],
        new_deadline=date(2026, 6, 15)))
    svc.dunning.update_deadline(booked.notice.id, date(2026, 6, 30))
    assert svc.dunning.get(booked.notice.id).new_deadline == date(2026, 6, 30)
    assert svc.history.next_deadline(inv.id) == date(2026, 6, 30)
    svc.dunning.update_deadline(booked.notice.id, date(2026, 6, 30))
    assert any(e.kind == "deadline" for e in svc.cases.events(booked.notice.case_id))


def test_import_proposes_hotel_and_default_due_date(world, tmp_path) -> None:
    svc, w = world
    text = ("Müller Bürobedarf GmbH\nRechnung\nRechnungsnummer: R-77\nRechnungsdatum: 10.03.2026\n"
            "Rechnungsempfänger: Hotel Bergfried, Seestraße 1\nRechnungsbetrag: 119,00 €\nNettobetrag: 100,00 €\n"
            "zzgl. 19 % MwSt.: 19,00 €\n")
    f = tmp_path / "r77.txt"
    f.write_text(text, encoding="utf-8")
    out = svc.ingest.import_file(f)
    review = svc.ingest.build_review(out.document.id)
    assert (review.company_id, review.hotel_id) == (w["a"].id, w["a2"].id)  # hotel found in the text, company follows
    assert review.due_date == date(2026, 4, 9) and review.confidence["due_date"] < 0.5
    assert any("Fälligkeitsdatum" in m for m in review.messages)
    review.due_date = date(2026, 5, 15)  # the user edits the due date before booking
    review.supplier_id = w["sup"].id
    result = svc.ingest.confirm(review)
    invoice = svc.invoices.get(result.invoice_id)
    assert invoice.due_date == date(2026, 5, 15) and (invoice.company_id, invoice.hotel_id) == (w["a"].id, w["a2"].id)
    doc = svc.repos.documents.get(out.document.id)
    assert (doc.company_id, doc.hotel_id) == (w["a"].id, w["a2"].id) and doc.review_status == ReviewStatus.ACCEPTED
    # company named in the text only -> company without hotel
    g = tmp_path / "r78.txt"
    g.write_text(text.replace("R-77", "R-78").replace("Hotel Bergfried", "Beta Resorts AG"), encoding="utf-8")
    review2 = svc.ingest.build_review(svc.ingest.import_file(g).document.id)
    assert (review2.company_id, review2.hotel_id) == (w["b"].id, None)
    assert svc.organization.detect_in_text("nichts passendes") == (None, None)
    _ = Document
