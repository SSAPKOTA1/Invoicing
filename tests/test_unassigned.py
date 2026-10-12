"""Documents without an invoice: warn, file them, assign the invoice later."""

from __future__ import annotations

from datetime import date

import pytest

from supplier_app.errors import AssignmentMissingError
from supplier_app.models.enums import ReviewStatus
from supplier_app.services.review_models import KIND_NOTICE, ClaimInput, ReviewData
from tests.helpers import make_scenario

LETTER = (
    "Müller Bürobedarf GmbH\nMusterstraße 1\n12345 Musterstadt\n\n"
    "1. Mahnung\nDatum: 10.04.2024\nRechnungsnummer: RE-2024/777\nOffener Betrag: 250,00 €\n"
    "Zahlbar bis 20.04.2024\nIBAN DE89 3704 0044 0532 0130 00\n"
)


def _letter(svc, tmp_path):
    f = tmp_path / "mahnung.txt"
    f.write_text(LETTER, encoding="utf-8")
    return svc.ingest.import_file(f).document


def test_notice_without_invoice_needs_confirmation_then_is_filed(svc, tmp_path) -> None:
    sc = make_scenario(svc)
    doc = _letter(svc, tmp_path)
    review = svc.ingest.build_review(doc.id)
    assert review.kind == KIND_NOTICE and review.supplier_id == sc.supplier.id and not review.claims
    with pytest.raises(AssignmentMissingError):
        svc.ingest.confirm(review)
    assert svc.documents.get(doc.id).review_status != ReviewStatus.ACCEPTED  # nothing happened
    result = svc.ingest.confirm(review, allow_unassigned=True)
    assert result.unassigned and result.invoice_id is None
    stored = svc.documents.get(doc.id)
    assert stored.assignment_pending and stored.supplier_id == sc.supplier.id
    assert [d.id for d in svc.ingest.pending_documents()] == [doc.id]
    assert svc.repos.notices.list(supplier_id=sc.supplier.id) == []  # nothing booked


def test_pending_document_is_assigned_later(svc, tmp_path) -> None:
    sc = make_scenario(svc, gross=25000, number="RE-2024/777")
    doc = _letter(svc, tmp_path)
    review = svc.ingest.build_review(doc.id)
    review.claims = []
    svc.ingest.confirm(review, allow_unassigned=True)
    again = svc.ingest.pending_review(doc.id)
    assert isinstance(again, ReviewData) and again.kind == KIND_NOTICE and again.supplier_id == sc.supplier.id
    assert any(c.invoice_id == sc.invoice.id for c in again.invoice_candidates)  # the invoice exists now
    again.claims = [ClaimInput(sc.invoice.id, principal_cents=25000, total_cents=25000)]
    result = svc.ingest.confirm(again)
    assert not result.unassigned and result.notice_id
    stored = svc.documents.get(doc.id)
    assert not stored.assignment_pending and stored.review_status == ReviewStatus.ACCEPTED
    assert svc.ingest.pending_documents() == []
    assert svc.repos.notices.list(supplier_id=sc.supplier.id)


def test_dashboard_lists_pending_documents(svc, tmp_path) -> None:
    from supplier_app.services.dashboard_models import DashboardFilter, DrillTarget
    from supplier_app.services.dashboard_service import DashboardService
    sc = make_scenario(svc)
    doc = _letter(svc, tmp_path)
    svc.ingest.confirm(svc.ingest.build_review(doc.id), allow_unassigned=True)
    ds = DashboardService(svc.repos, svc.ledger, svc.settings)
    flt = DashboardFilter(as_of=date(2024, 4, 15), date_from=date(2024, 1, 1), date_to=date(2024, 12, 31))
    items = ds.build(flt).attention["unassigned"]
    assert [i.open_id for i in items] == [doc.id] and items[0].target == DrillTarget("docs", "unassigned")
    drill = ds.drilldown(DrillTarget("docs", "unassigned"), flt)
    assert drill.count == 1 and sc.supplier.id
