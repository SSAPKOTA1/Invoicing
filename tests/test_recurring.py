"""Recurring invoices (rent): schedule, amounts, generation, duplicate protection."""

from __future__ import annotations

from datetime import date

import pytest

from supplier_app.errors import ValidationError
from supplier_app.models.entities import Party, RecurringAmount, RecurringInvoice
from supplier_app.models.enums import RecurrencePeriod
from supplier_app.services.recurring_service import RecurringService, add_months


def _landlord(svc) -> Party:
    return svc.suppliers.create(Party(name="Hausverwaltung Berger"))


def _rent(svc, **kw) -> RecurringInvoice:
    landlord = _landlord(svc)
    rec = RecurringInvoice(landlord.id, "Miete Hotel Alpenblick", RecurrencePeriod.MONTHLY, date(2024, 1, 1),
                           due_days=5, amounts=[RecurringAmount(date(2024, 1, 1), 450000)], **kw)
    return svc.recurring.create(rec)


def test_add_months_clamps_to_month_end() -> None:
    assert add_months(date(2024, 1, 31), 1, 31) == date(2024, 2, 29)
    assert add_months(date(2024, 11, 15), 3, 15) == date(2025, 2, 15)
    assert add_months(date(2024, 1, 1), 1, 30) == date(2024, 2, 29)


def test_occurrences_for_every_period(svc) -> None:
    rec = _rent(svc)
    days = RecurringService.occurrences(rec, date(2024, 4, 15))
    assert days == [date(2024, 1, 1), date(2024, 2, 1), date(2024, 3, 1), date(2024, 4, 1)]
    rec.period, rec.end_date = RecurrencePeriod.QUARTERLY, date(2024, 12, 31)
    assert RecurringService.occurrences(rec, date(2030, 1, 1)) == [
        date(2024, 1, 1), date(2024, 4, 1), date(2024, 7, 1), date(2024, 10, 1)]
    rec.period, rec.end_date = RecurrencePeriod.YEARLY, None
    assert RecurringService.occurrences(rec, date(2026, 6, 1)) == [date(2024, 1, 1), date(2025, 1, 1), date(2026, 1, 1)]


def test_generate_books_each_period_once(svc) -> None:
    rec = _rent(svc)
    report = svc.recurring.generate_due(date(2024, 3, 10))
    assert [inv.invoice_number for _r, inv in report.created] == ["MIETE-2024-01", "MIETE-2024-02", "MIETE-2024-03"]
    invoice = report.created[0][1]
    assert invoice.gross_cents == 450000 and invoice.due_date == date(2024, 1, 6)
    assert svc.ledger.invoice_balance(invoice.id).balance_cents == 450000
    again = svc.recurring.generate_due(date(2024, 3, 10))
    assert again.created == [] and again.skipped == []
    later = svc.recurring.generate_due(date(2024, 4, 2))
    assert [inv.invoice_number for _r, inv in later.created] == ["MIETE-2024-04"]
    assert len(svc.recurring.runs(rec.id)) == 4


def test_amount_changes_apply_from_their_date(svc) -> None:
    rec = _rent(svc)
    svc.recurring.set_amount(rec.id, date(2024, 3, 1), 470000)
    report = svc.recurring.generate_due(date(2024, 4, 1))
    assert [inv.gross_cents for _r, inv in report.created] == [450000, 450000, 470000, 470000]


def test_existing_invoice_is_adopted_not_duplicated(svc) -> None:
    rec = _rent(svc)
    svc.invoices.create_invoice(rec.supplier_id, "MIETE-2024-02", date(2024, 2, 1), gross_cents=450000)
    report = svc.recurring.generate_due(date(2024, 3, 1))
    assert [inv.invoice_number for _r, inv in report.created] == ["MIETE-2024-01", "MIETE-2024-03"]
    assert len(report.skipped) == 1 and "MIETE-2024-02" in report.skipped[0]


def test_inactive_template_is_ignored_and_validation(svc) -> None:
    rec = _rent(svc)
    svc.recurring.set_active(rec.id, False)
    assert svc.recurring.generate_due(date(2024, 6, 1)).created == []
    bad = RecurringInvoice(rec.supplier_id, "Leasing", RecurrencePeriod.MONTHLY, date(2024, 1, 1),
                           number_pattern="FIX", amounts=[RecurringAmount(date(2024, 1, 1), 100)])
    with pytest.raises(ValidationError):
        svc.recurring.create(bad)  # the number would never change
    bad.number_pattern = "{foo}-{year}"
    with pytest.raises(ValidationError):
        svc.recurring.create(bad)
    bad.number_pattern, bad.amounts = "", []
    with pytest.raises(ValidationError):
        svc.recurring.create(bad)


def test_deleting_the_template_keeps_the_invoices(svc) -> None:
    rec = _rent(svc)
    svc.recurring.generate_due(date(2024, 2, 1))
    svc.recurring.delete(rec.id)
    assert svc.recurring.list() == []
    assert len(svc.invoices.list(rec.supplier_id)) == 2
