"""Correcting a wrong supplier / sender later on."""

from __future__ import annotations

from datetime import date

import pytest

from supplier_app.errors import LedgerError, ValidationError
from supplier_app.models.entities import Party
from supplier_app.models.enums import DunningLevel, PartyRole
from supplier_app.services.dunning_service import NoticeDraft
from supplier_app.services.ledger import NoticeClaim
from tests.helpers import make_scenario


def _other(svc) -> Party:
    return svc.suppliers.create(Party(name="Hotelbedarf Nord GmbH"))


def test_change_supplier_rebooks_the_invoice(svc) -> None:
    sc = make_scenario(svc)
    other = _other(svc)
    svc.invoices.change_supplier(sc.invoice.id, other.id)
    assert svc.invoices.get(sc.invoice.id).supplier_id == other.id
    assert svc.ledger.invoice_balance(sc.invoice.id).balance_cents == 100000
    balances = svc.ledger.supplier_balances(date(2024, 12, 31))
    assert sc.supplier.id not in balances or balances[sc.supplier.id].total_cents == 0
    assert balances[other.id].total_cents == 100000
    assert svc.repos.db.scalar("SELECT COUNT(*) FROM audit_log WHERE action='change_supplier'") == 1


def test_change_supplier_refused_with_payment_or_duplicate_number(svc) -> None:
    sc = make_scenario(svc)
    other = _other(svc)
    svc.invoices.create_invoice(other.id, sc.invoice.invoice_number, date(2024, 1, 5), gross_cents=500)
    with pytest.raises(ValidationError):
        svc.invoices.change_supplier(sc.invoice.id, other.id)
    third = svc.suppliers.create(Party(name="Dritter GmbH"))
    svc.payments.record_payment(sc.supplier.id, date(2024, 2, 1), 1000, [sc.invoice.id])
    with pytest.raises(LedgerError):
        svc.invoices.change_supplier(sc.invoice.id, third.id)


def test_change_supplier_refused_with_letters(svc) -> None:
    sc = make_scenario(svc)
    svc.dunning.book_notice(NoticeDraft(
        sc.supplier.id, date(2024, 3, 1), DunningLevel.FIRST, [NoticeClaim(sc.invoice.id, 100000, fees_cents=500)]))
    with pytest.raises(LedgerError):
        svc.invoices.change_supplier(sc.invoice.id, _other(svc).id)


def test_change_notice_sender(svc) -> None:
    sc = make_scenario(svc)
    booked = svc.dunning.book_notice(NoticeDraft(
        sc.supplier.id, date(2024, 3, 1), DunningLevel.FIRST, [NoticeClaim(sc.invoice.id, 100000, fees_cents=500)]))
    nid = booked.notice.id
    svc.dunning.change_sender(nid, sc.agency.id)
    assert svc.dunning.get(nid).sender_party_id == sc.agency.id
    foreign = svc.suppliers.create(Party(name="Fremdes Inkasso", role=PartyRole.COLLECTION_AGENCY))
    with pytest.raises(ValidationError):
        svc.dunning.change_sender(nid, foreign.id)
    with pytest.raises(ValidationError):
        svc.dunning.change_sender(nid, _other(svc).id)


def test_change_document_supplier(svc, tmp_path) -> None:
    sc = make_scenario(svc)
    f = tmp_path / "a.txt"
    f.write_text("Hallo Welt", encoding="utf-8")
    doc = svc.ingest.import_file(f).document
    svc.documents.set_supplier(doc.id, sc.supplier.id)
    assert svc.documents.get(doc.id).supplier_id == sc.supplier.id
