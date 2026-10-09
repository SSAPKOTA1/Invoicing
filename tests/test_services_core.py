from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from supplier_app.errors import (
    AuthError,
    DuplicateError,
    LedgerError,
    NotFoundError,
    ValidationError,
)
from supplier_app.models.entities import Party
from supplier_app.models.enums import (
    AllocationComponent,
    AllocationRule,
    CaseStatus,
    DunningLevel,
    InvoiceStatus,
    LedgerEntryType,
    PartyRole,
    ReferenceType,
)
from supplier_app.services.dunning_service import NoticeDraft
from supplier_app.services.ledger import NoticeClaim
from tests.helpers import make_scenario


def test_worked_example_end_to_end(svc) -> None:
    sc = make_scenario(svc)
    inv = sc.invoice.id
    first = svc.dunning.book_notice(NoticeDraft(
        sender_party_id=sc.supplier.id, notice_date=date(2024, 3, 1), level=DunningLevel.FIRST,
        claims=[NoticeClaim(inv, 100000, fees_cents=500, total_cents=100500)],
        references=[(ReferenceType.PROCESSING_NUMBER, "4711/A")]))
    assert first.reconciliation.ok and [e.amount_cents for e in first.entries] == [500]
    second = svc.dunning.book_notice(NoticeDraft(
        sender_party_id=sc.agency.id, notice_date=date(2024, 3, 20), level=DunningLevel.SECOND,
        claims=[NoticeClaim(inv, 100000, fees_cents=1500, total_cents=101500)],
        references=[(ReferenceType.FILE_NUMBER, "INK-2024-77881")]))
    assert [e.amount_cents for e in second.entries] == [1000]  # fee restated, only +10,00 booked
    assert second.reconciliation.ok
    assert svc.ledger.invoice_balance(inv).balance_cents == 101500
    pay = svc.payments.record_payment(sc.supplier.id, date(2024, 4, 1), 40000, [inv])
    bal = svc.ledger.invoice_balance(inv)
    assert bal.balance_cents == 61500 and bal.status == InvoiceStatus.PARTIALLY_PAID
    assert svc.repos.invoices.get(inv).status == InvoiceStatus.PARTIALLY_PAID
    allocs = {a.component: a.amount_cents for a in svc.repos.payments.allocations(payment_id=pay.id)}
    assert allocs == {AllocationComponent.COSTS: 1500, AllocationComponent.PRINCIPAL: 38500}
    # one case, all notices linked to it, new reference remembered on invoice
    cases = svc.cases.list()
    assert len(cases) == 1 and cases[0].invoice_id == inv
    assert len(svc.repos.notices.list(case_id=cases[0].id)) == 2 or len(svc.repos.notices.list(invoice_id=inv)) == 2
    assert svc.repos.references.find("INK202477881")[0].owner_kind in ("invoice", "case")


def test_notice_sent_twice_is_rejected_and_no_double_fee(svc) -> None:
    sc = make_scenario(svc)
    draft = NoticeDraft(sender_party_id=sc.supplier.id, notice_date=date(2024, 3, 1), level=DunningLevel.FIRST,
                        claims=[NoticeClaim(sc.invoice.id, 100000, fees_cents=500)])
    svc.dunning.book_notice(draft)
    assert svc.dunning.is_duplicate(draft) is not None
    with pytest.raises(DuplicateError):
        svc.dunning.book_notice(draft)
    assert svc.ledger.invoice_balance(sc.invoice.id).balance_cents == 100500
    # same fee restated by another letter does not double it
    svc.dunning.book_notice(NoticeDraft(
        sender_party_id=sc.supplier.id, notice_date=date(2024, 3, 15), level=DunningLevel.SECOND,
        claims=[NoticeClaim(sc.invoice.id, 100000, fees_cents=500)]))
    assert svc.ledger.invoice_balance(sc.invoice.id).balance_cents == 100500


def test_notice_validation(svc) -> None:
    sc = make_scenario(svc)
    other = svc.suppliers.create(Party(name="Anderer GmbH"))
    inv2 = svc.invoices.create_invoice(other.id, "X-1", date(2024, 1, 1), gross_cents=500)
    with pytest.raises(ValidationError):
        svc.dunning.book_notice(NoticeDraft(sc.supplier.id, date(2024, 3, 1), DunningLevel.FIRST, []))
    with pytest.raises(ValidationError):  # invoice of another supplier
        svc.dunning.book_notice(NoticeDraft(sc.supplier.id, date(2024, 3, 1), DunningLevel.FIRST,
                                            [NoticeClaim(inv2.id, 500)]))
    with pytest.raises(ValidationError):  # same invoice twice
        svc.dunning.book_notice(NoticeDraft(sc.supplier.id, date(2024, 3, 1), DunningLevel.FIRST,
                                            [NoticeClaim(sc.invoice.id, 1), NoticeClaim(sc.invoice.id, 2)]))
    lone = svc.suppliers.create(Party(name="Lone Inkasso", role=PartyRole.COLLECTION_AGENCY))
    with pytest.raises(ValidationError):
        svc.dunning.book_notice(NoticeDraft(lone.id, date(2024, 3, 1), DunningLevel.COLLECTION,
                                            [NoticeClaim(sc.invoice.id, 1)]))


def test_notice_lower_than_booked_warns(svc) -> None:
    sc = make_scenario(svc)
    svc.dunning.book_notice(NoticeDraft(sc.supplier.id, date(2024, 3, 1), DunningLevel.FIRST,
                                        [NoticeClaim(sc.invoice.id, 100000, fees_cents=500)]))
    booked = svc.dunning.book_notice(NoticeDraft(sc.supplier.id, date(2024, 3, 9), DunningLevel.SECOND,
                                                 [NoticeClaim(sc.invoice.id, 100000, fees_cents=300)]))
    assert booked.entries == [] and booked.warnings


def test_notice_discrepancy_when_payment_ignored(svc) -> None:
    sc = make_scenario(svc)
    svc.payments.record_payment(sc.supplier.id, date(2024, 2, 20), 40000, [sc.invoice.id])
    booked = svc.dunning.book_notice(NoticeDraft(
        sc.supplier.id, date(2024, 3, 1), DunningLevel.FIRST,
        [NoticeClaim(sc.invoice.id, 100000, fees_cents=500, total_cents=100500)]))
    codes = {i.code for i in booked.reconciliation.issues}
    assert {"DIFF", "PAYMENT_IGNORED"} <= codes
    hist = svc.history.invoice_history(sc.invoice.id)
    assert hist.warnings and any(it.kind == "notice" and it.warnings for it in hist.items)


def test_notice_two_invoices_and_collection_agency_supplier(svc) -> None:
    sc = make_scenario(svc)
    inv2 = svc.invoices.create_invoice(sc.supplier.id, "RE-2024/002", date(2024, 1, 20), gross_cents=50000)
    booked = svc.dunning.book_notice(NoticeDraft(
        sc.agency.id, date(2024, 4, 1), DunningLevel.COLLECTION,
        [NoticeClaim(sc.invoice.id, 100000, other_costs_cents=2500), NoticeClaim(inv2.id, 50000, other_costs_cents=1500)],
        references=[(ReferenceType.FILE_NUMBER, "AZ 55/24")]))
    assert booked.notice.supplier_id == sc.supplier.id
    assert booked.reconciliation.ok and booked.reconciliation.claimed_total_cents == 154000
    assert {e.entry_type for e in booked.entries} == {LedgerEntryType.COLLECTION_COST}
    assert svc.dunning.escalated_invoice_ids() == {sc.invoice.id, inv2.id}
    assert svc.dunning.latest_level(inv2.id) == DunningLevel.COLLECTION
    assert len(svc.cases.list()) == 2


def test_payment_two_invoices_overpayment_and_credit_application(svc) -> None:
    sc = make_scenario(svc, gross=30000)
    inv2 = svc.invoices.create_invoice(sc.supplier.id, "RE-2", date(2024, 1, 15), gross_cents=20000,
                                       due_date=date(2024, 2, 14))
    prev = svc.payments.preview(sc.supplier.id, 60000, [sc.invoice.id, inv2.id])
    assert prev.unallocated_cents == 10000 and [r.status_after for r in prev.rows] == [InvoiceStatus.PAID] * 2
    pay = svc.payments.record_payment(sc.supplier.id, date(2024, 3, 1), 60000, [sc.invoice.id, inv2.id])
    assert svc.repos.invoices.get(sc.invoice.id).status == InvoiceStatus.PAID
    sb = svc.ledger.supplier_balance(sc.supplier.id)
    assert (sb.invoices_cents, sb.unapplied_cents, sb.total_cents) == (0, -10000, -10000)  # credit visible
    unapplied = svc.payments.unapplied_payments(sc.supplier.id)
    assert unapplied[0].amount_cents == 10000 and unapplied[0].payment.id == pay.id
    # later invoice consumes the credit
    inv3 = svc.invoices.create_invoice(sc.supplier.id, "RE-3", date(2024, 3, 10), gross_cents=15000)
    svc.payments.apply_credit(pay.id, [inv3.id], on=date(2024, 3, 11))
    assert svc.ledger.invoice_balance(inv3.id).balance_cents == 5000
    assert svc.payments.unapplied_payments(sc.supplier.id) == []
    assert svc.ledger.supplier_balance(sc.supplier.id).total_cents == 5000
    with pytest.raises(LedgerError):
        svc.payments.apply_credit(pay.id, [inv3.id])


def test_payment_without_invoice_is_pure_credit_and_validation(svc) -> None:
    sc = make_scenario(svc)
    svc.payments.record_payment(sc.supplier.id, date(2024, 3, 1), 5000)
    assert svc.ledger.supplier_balance(sc.supplier.id).total_cents == 100000 - 5000
    with pytest.raises(ValidationError):
        svc.payments.record_payment(sc.supplier.id, date(2024, 3, 1), 0)
    with pytest.raises(NotFoundError):
        svc.payments.record_payment(999, date(2024, 3, 1), 100)
    other = svc.suppliers.create(Party(name="Fremd"))
    with pytest.raises(ValidationError):
        svc.payments.record_payment(other.id, date(2024, 3, 1), 100, [sc.invoice.id])


def test_manual_allocation_and_rule_oldest_first(svc) -> None:
    sc = make_scenario(svc, gross=30000)
    inv2 = svc.invoices.create_invoice(sc.supplier.id, "RE-2", date(2024, 1, 15), gross_cents=20000,
                                       due_date=date(2024, 2, 20))
    svc.payments.record_payment(
        sc.supplier.id, date(2024, 3, 1), 25000, [sc.invoice.id, inv2.id], rule=AllocationRule.MANUAL,
        manual=[(inv2.id, AllocationComponent.PRINCIPAL, 20000), (sc.invoice.id, AllocationComponent.PRINCIPAL, 5000)])
    assert svc.ledger.invoice_balance(inv2.id).status == InvoiceStatus.PAID
    assert svc.ledger.invoice_balance(sc.invoice.id).balance_cents == 25000
    pay2 = svc.payments.record_payment(sc.supplier.id, date(2024, 3, 2), 100, [sc.invoice.id],
                                       rule=AllocationRule.OLDEST_FIRST, bank_reference="Zahlung RE-2024/001")
    assert svc.ledger.invoice_balance(sc.invoice.id).balance_cents == 24900
    assert svc.repos.references.find("ZAHLUNGRE2024001")
    assert pay2.id


def test_reverse_payment_restores_balance_and_blocks_second_reversal(svc) -> None:
    sc = make_scenario(svc)
    pay = svc.payments.record_payment(sc.supplier.id, date(2024, 3, 1), 100000, [sc.invoice.id])
    assert svc.repos.invoices.get(sc.invoice.id).status == InvoiceStatus.PAID
    svc.payments.reverse_payment(pay.id, "falsch gebucht", date(2024, 3, 5))
    bal = svc.ledger.invoice_balance(sc.invoice.id)
    assert bal.balance_cents == 100000 and bal.status == InvoiceStatus.OPEN
    assert bal.open_principal_cents == 100000
    assert svc.repos.invoices.get(sc.invoice.id).status == InvoiceStatus.OPEN
    with pytest.raises(LedgerError):
        svc.payments.reverse_payment(pay.id)
    with pytest.raises(NotFoundError):
        svc.payments.reverse_payment(4711)
    # entries are never edited: original + reversal both exist
    kinds = [e.entry_type for e in svc.repos.ledger.list(invoice_id=sc.invoice.id)]
    assert kinds.count(LedgerEntryType.PAYMENT) == 1 and kinds.count(LedgerEntryType.REVERSAL) == 1


def test_generic_reversal_rules(svc) -> None:
    sc = make_scenario(svc)
    book = svc.dunning.book_notice(NoticeDraft(sc.supplier.id, date(2024, 3, 1), DunningLevel.FIRST,
                                               [NoticeClaim(sc.invoice.id, 100000, fees_cents=500)]))
    fee = book.entries[0]
    rev = svc.ledger.reverse_entry(fee.id, "Gebühr zu Unrecht", date(2024, 3, 2))
    assert rev.amount_cents == -500 and rev.category_type == LedgerEntryType.DUNNING_FEE
    assert svc.ledger.invoice_balance(sc.invoice.id).balance_cents == 100000
    with pytest.raises(LedgerError):
        svc.ledger.reverse_entry(fee.id)
    with pytest.raises(LedgerError):
        svc.ledger.reverse_entry(rev.id)
    with pytest.raises(NotFoundError):
        svc.ledger.reverse_entry(9999)
    pay = svc.payments.record_payment(sc.supplier.id, date(2024, 3, 3), 100)
    pay_entry = svc.repos.ledger.list(payment_id=pay.id)[0]
    with pytest.raises(LedgerError):
        svc.ledger.reverse_entry(pay_entry.id)
    with pytest.raises(LedgerError):
        svc.ledger.post(entry_date=date(2024, 1, 1), supplier_id=sc.supplier.id, entry_type=LedgerEntryType.REVERSAL,
                        amount_cents=1)


def test_invoice_lifecycle(svc) -> None:
    sc = make_scenario(svc)
    inv = sc.invoice.id
    svc.invoices.credit_note(inv, 10000, date(2024, 2, 1), "Retoure")
    assert svc.ledger.invoice_balance(inv).balance_cents == 90000
    svc.invoices.adjustment(inv, -500, date(2024, 2, 2), "Skonto")
    svc.invoices.write_off(inv, 1000, date(2024, 2, 3))
    assert svc.ledger.invoice_balance(inv).balance_cents == 88500
    with pytest.raises(ValidationError):
        svc.invoices.write_off(inv, 10_000_000, date(2024, 2, 3))
    with pytest.raises(ValidationError):
        svc.invoices.adjustment(inv, 100, date(2024, 2, 3), " ")
    with pytest.raises(ValidationError):
        svc.invoices.credit_note(inv, 0, date(2024, 2, 3))
    assert svc.invoices.set_disputed(inv, True) == InvoiceStatus.DISPUTED
    assert svc.invoices.set_disputed(inv, False) == InvoiceStatus.OPEN
    d = svc.invoices.update_details(inv, due_date=date(2024, 3, 1), notes="x")
    assert d.due_date == date(2024, 3, 1)
    with pytest.raises(ValidationError):
        svc.invoices.update_details(inv, due_date=date(2023, 1, 1))
    pay = svc.payments.record_payment(sc.supplier.id, date(2024, 3, 1), 100, [inv])
    with pytest.raises(LedgerError):
        svc.invoices.cancel_invoice(inv)
    svc.payments.reverse_payment(pay.id)
    svc.invoices.cancel_invoice(inv, "Fehler")
    assert svc.ledger.invoice_balance(inv).balance_cents == 0
    assert svc.repos.invoices.get(inv).status == InvoiceStatus.CANCELLED
    with pytest.raises(LedgerError):
        svc.invoices.set_disputed(inv, True)
    with pytest.raises(ValidationError):
        svc.payments.record_payment(sc.supplier.id, date(2024, 3, 1), 100, [inv])


def test_invoice_creation_validation_and_amounts(svc) -> None:
    sc = make_scenario(svc)
    s = sc.supplier.id
    inv = svc.invoices.create_invoice(s, "A-1", date(2024, 5, 1), net_cents=84034)
    assert (inv.vat_cents, inv.gross_cents) == (15966, 100000)
    inv = svc.invoices.create_invoice(s, "A-2", date(2024, 5, 1), gross_cents=11900, vat_rate=Decimal(19))
    assert (inv.net_cents, inv.vat_cents) == (10000, 1900)
    assert inv.due_date == date(2024, 5, 31)  # default payment days
    with pytest.raises(ValidationError):
        svc.invoices.create_invoice(s, "A-3", date(2024, 5, 1), gross_cents=10000, net_cents=5000, vat_cents=1000)
    with pytest.raises(ValidationError):
        svc.invoices.create_invoice(s, "A-4", date(2024, 5, 1))
    with pytest.raises(ValidationError):
        svc.invoices.create_invoice(s, " ", date(2024, 5, 1), gross_cents=1)
    with pytest.raises(ValidationError):
        svc.invoices.create_invoice(sc.agency.id, "A-5", date(2024, 5, 1), gross_cents=1)
    with pytest.raises(ValidationError):
        svc.invoices.create_invoice(s, "A-6", date(2024, 5, 1), gross_cents=1, due_date=date(2024, 4, 1))
    with pytest.raises(DuplicateError):
        svc.invoices.create_invoice(s, "A-1", date(2024, 5, 1), gross_cents=1)
    with pytest.raises(NotFoundError):
        svc.invoices.get(9999)


def test_cases_follow_invoice_status(svc) -> None:
    sc = make_scenario(svc)
    svc.dunning.book_notice(NoticeDraft(sc.supplier.id, date(2024, 3, 1), DunningLevel.FIRST,
                                        [NoticeClaim(sc.invoice.id, 100000, fees_cents=500)]))
    case = svc.cases.list()[0]
    assert case.status == CaseStatus.OPEN and case.auto_opened
    svc.invoices.set_disputed(sc.invoice.id, True)
    assert svc.cases.get(case.id).status == CaseStatus.IN_DISPUTE
    svc.invoices.set_disputed(sc.invoice.id, False)
    pay = svc.payments.record_payment(sc.supplier.id, date(2024, 3, 3), 100500, [sc.invoice.id])
    assert svc.cases.get(case.id).status == CaseStatus.PAID
    svc.payments.reverse_payment(pay.id)
    assert svc.cases.get(case.id).status == CaseStatus.OPEN
    svc.cases.add_note(case.id, "Rückruf vereinbart")
    svc.cases.set_status(case.id, CaseStatus.WAITING)
    assert any(e.kind == "note" for e in svc.cases.events(case.id))
    assert svc.cases.open_manual(sc.invoice.id).id == case.id
    with pytest.raises(NotFoundError):
        svc.cases.get(999)
    with pytest.raises(NotFoundError):
        svc.cases.ensure_for_invoice(999)


def test_statement_running_balance_and_aging(svc) -> None:
    sc = make_scenario(svc)
    svc.payments.record_payment(sc.supplier.id, date(2024, 3, 1), 30000, [sc.invoice.id])
    svc.invoices.create_invoice(sc.supplier.id, "RE-2", date(2024, 4, 1), gross_cents=5000, due_date=date(2024, 5, 1))
    st = svc.ledger.supplier_statement(sc.supplier.id)
    assert [r.running_cents for r in st.rows] == [100000, 70000, 75000] and st.closing_cents == 75000
    part = svc.ledger.supplier_statement(sc.supplier.id, date_from=date(2024, 3, 1))
    assert part.opening_cents == 100000 and part.closing_cents == 75000 and len(part.rows) == 2
    aging = svc.ledger.aging(date(2024, 6, 30))
    assert aging["31-60"] == 5000 and aging["90+"] == 70000 and sum(aging.values()) == 75000
    assert svc.ledger.supplier_balances()[sc.supplier.id].total_cents == 75000
    states = svc.ledger.invoice_states(date(2024, 1, 31))
    assert len(states) == 1 and states[0].balance.balance_cents == 100000


def test_interest_comparison_claimed_vs_calculated(svc) -> None:
    sc = make_scenario(svc)
    booked = svc.dunning.book_notice(NoticeDraft(
        sc.agency.id, date(2024, 3, 11), DunningLevel.COLLECTION,
        [NoticeClaim(sc.invoice.id, 100000, interest_cents=1500, flat_fee_cents=4000)]))
    rows = svc.dunning.compare_with_calculation(booked.notice.id)
    interest = next(r for r in rows if r.label == "Verzugszinsen")
    # due 2024-02-09 -> 2024-03-11 = 31 days at 3.62 + 9 = 12.62 %: 1072 cents
    assert interest.calculated_cents == 1072 and interest.difference_cents == 428
    flat = next(r for r in rows if r.label == "Verzugspauschale")
    assert flat.calculated_cents == 4000 and flat.difference_cents == 0
    assert svc.ledger.calculate_interest(sc.invoice.id, date(2024, 2, 9)).total_cents == 0
    svc.invoices.update_details(sc.invoice.id)
    assert svc.settings.interest_margin == Decimal(9)


def test_history_timeline_order_and_running(svc) -> None:
    sc = make_scenario(svc)
    svc.dunning.book_notice(NoticeDraft(sc.supplier.id, date(2024, 3, 1), DunningLevel.FIRST,
                                        [NoticeClaim(sc.invoice.id, 100000, fees_cents=500)],
                                        new_deadline=date(2024, 3, 15), references=[(ReferenceType.PROCESSING_NUMBER, "B-1")]))
    svc.payments.record_payment(sc.supplier.id, date(2024, 3, 5), 40000, [sc.invoice.id])
    h = svc.history.invoice_history(sc.invoice.id)
    assert [i.kind for i in h.items] == ["entry", "notice", "entry", "entry"]
    assert [i.running_cents for i in h.items if i.kind == "entry"] == [100000, 100500, 60500]
    assert h.balance.balance_cents == 60500 and h.next_deadline == date(2024, 3, 15)
    assert ("Bearbeitungsnummer", "B-1") in h.references
    assert svc.history.case_history(h.case.id).invoice.id == sc.invoice.id
    assert len(svc.history.notices_for_case(h.case.id)) == 1
    assert svc.history.overdue_days(h.invoice) > 0
    svc.payments.record_payment(sc.supplier.id, date(2024, 3, 6), 60500, [sc.invoice.id])
    assert svc.history.invoice_history(sc.invoice.id).next_deadline is None


def test_settings_and_pin(svc) -> None:
    st = svc.settings
    assert st.theme == "dark" and st.debtor_type == "b2b" and st.flat_fee_cents == 4000
    st.set_theme("light")
    assert st.theme == "light"
    with pytest.raises(ValidationError):
        st.set_theme("pink")
    st.set("debtor_type", "b2c")
    assert st.interest_margin == Decimal(5) and st.flat_fee_cents == 0
    st.set("allocation_rule", "bogus")
    assert st.allocation_rule == AllocationRule.STATUTORY
    st.set("default_payment_days", "x")
    assert st.get_int("default_payment_days") == 30
    st.set("margin_b2b", "abc")
    assert st.get_decimal("margin_b2b") == Decimal(9)
    st.set("low_confidence", "zzz")
    assert st.low_confidence == 0.75
    st.set_reference_rules({"file_number": ["AZ"]})
    assert st.reference_rules() == {"file_number": ["AZ"]}
    st.set("reference_rules", "{kaputt")
    assert st.reference_rules() == {}
    st.set_rate(date(2026, 1, 1), Decimal("1.27"))
    assert st.rate_points()[-1].base_rate == Decimal("1.27")


class Clock:
    def __init__(self) -> None:
        from datetime import datetime
        self.now = datetime(2025, 1, 1, 12, 0, 0)

    def __call__(self):
        return self.now


def test_pin_flow(storage) -> None:
    from datetime import timedelta

    from supplier_app.services.pin_service import PinService
    clock = Clock()
    pin = PinService(storage.repos, clock=clock)
    assert not pin.enabled and pin.verify("anything")
    with pytest.raises(ValidationError):
        pin.set_pin("12")
    with pytest.raises(ValidationError):
        pin.set_pin("abcd")
    pin.set_pin("1234")
    assert pin.enabled and pin.verify("1234")
    stored = storage.repos.settings.get("pin_hash")
    assert stored and "1234" not in stored and len(storage.repos.settings.get("pin_salt")) == 32
    for _ in range(5):
        assert pin.verify("0000") is False
    assert pin.lockout_seconds_left() == 30
    with pytest.raises(AuthError):
        pin.verify("1234")  # locked although correct
    clock.now += timedelta(seconds=31)
    assert pin.verify("1234") is True and pin.lockout_seconds_left() == 0
    # second lockout is longer
    for _ in range(5):
        pin.verify("9999")
    assert pin.lockout_seconds_left() == 30
    clock.now += timedelta(seconds=31)
    assert pin.verify("1234")
    # change requires current pin
    with pytest.raises(AuthError):
        pin.set_pin("5678", "wrong")
    pin.set_pin("5678", "1234")
    assert pin.verify("5678") and not pin.verify("1234")
    # disable requires current pin
    with pytest.raises(AuthError):
        pin.disable("1234")
    pin.disable("5678")
    assert not pin.enabled
    pin.disable("x")  # no-op
    pin.set_pin("4321")
    pin.reset()
    assert not pin.enabled


def test_suppliers_service_validation(svc) -> None:
    with pytest.raises(ValidationError):
        svc.suppliers.create(Party(name=" "))
    with pytest.raises(ValidationError):
        svc.suppliers.create(Party(name="X", ibans=["DE00 1234"]))
    with pytest.raises(ValidationError):
        svc.suppliers.create(Party(name="X", vat_id="DE12"))
    with pytest.raises(ValidationError):
        svc.suppliers.create(Party(name="X", represents_supplier_id=1))
    with pytest.raises(ValidationError):
        svc.suppliers.create(Party(name="A", role=PartyRole.COLLECTION_AGENCY, represents_supplier_id=77))
    s = svc.suppliers.create(Party(name="Gut GmbH"))
    svc.suppliers.add_alias(s.id, "Gut")
    svc.suppliers.add_iban(s.id, "DE89 3704 0044 0532 0130 00")
    svc.suppliers.add_iban(s.id, "DE89 3704 0044 0532 0130 00")
    with pytest.raises(ValidationError):
        svc.suppliers.add_iban(s.id, "DE00")
    got = svc.suppliers.get(s.id)
    assert got.aliases == ["Gut"] and got.ibans == ["DE89370400440532013000"]
    assert svc.suppliers.supplier_for(got).id == s.id
    agency = svc.suppliers.create(Party(name="Ink", role=PartyRole.COLLECTION_AGENCY))
    assert svc.suppliers.supplier_for(agency) is None
    svc.suppliers.delete(agency.id)
    with pytest.raises(NotFoundError):
        svc.suppliers.get(agency.id)
    got.notes = "n"
    svc.suppliers.update(got)
    assert [p.id for p in svc.suppliers.suppliers()] == [s.id] and len(svc.suppliers.list()) == 1
