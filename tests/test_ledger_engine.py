"""Pure ledger engine tests (written before the engine)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from supplier_app.errors import LedgerError
from supplier_app.models.enums import AllocationComponent as C
from supplier_app.models.enums import AllocationRule, InvoiceStatus
from supplier_app.models.enums import LedgerEntryType as T
from supplier_app.services.ledger import (
    AGING_BUCKETS,
    AllocationRow,
    LedgerLine,
    NoticeClaim,
    OpenItem,
    RatePoint,
    aging_bucket,
    aging_totals,
    allocate_payment,
    annual_rate,
    balance_from_sums,
    calculate_interest,
    derive_status,
    plan_notice_postings,
    reconcile_notice,
    running_balance,
    summarize_invoice,
)

D = date


def L(eid, d, t, amt, inv=1, cat=None, **kw) -> LedgerLine:
    return LedgerLine(entry_id=eid, entry_date=d, invoice_id=inv, entry_type=t, category=cat or t, amount_cents=amt, **kw)


# ---------------------------------------------------------------- worked example
def test_worked_example_from_spec() -> None:
    lines = [L(1, D(2024, 1, 10), T.INVOICE, 100000)]
    # 1st Mahnung: fee 5,00 (claims 1.005,00)
    n1 = NoticeClaim(invoice_id=1, principal_cents=100000, fees_cents=500, total_cents=100500)
    posts1 = plan_notice_postings(n1, booked={})
    assert [(p.entry_type, p.amount_cents) for p in posts1.charges] == [(T.DUNNING_FEE, 500)]
    lines.append(L(2, D(2024, 3, 1), T.DUNNING_FEE, 500, notice_id=1))
    # 2nd Mahnung restates the 5,00 fee and adds 10,00 (claims 1.015,00)
    n2 = NoticeClaim(invoice_id=1, principal_cents=100000, fees_cents=1500, total_cents=101500)
    posts2 = plan_notice_postings(n2, booked={T.DUNNING_FEE: 500})
    assert [(p.entry_type, p.amount_cents) for p in posts2.charges] == [(T.DUNNING_FEE, 1000)]
    lines.append(L(3, D(2024, 3, 20), T.DUNNING_FEE, 1000, notice_id=2))
    bal = summarize_invoice(lines, [])
    assert bal.balance_cents == 101500  # not 1000 + 1005 + 1015
    assert bal.open_costs_cents == 1500 and bal.open_principal_cents == 100000
    # payment 400,00 allocated costs first (15,00), then principal (385,00)
    res = allocate_payment(40000, [OpenItem(1, D(2024, 2, 9), D(2024, 1, 10), 1500, 0, 100000)], AllocationRule.STATUTORY)
    assert [(a.component, a.amount_cents) for a in res.allocations] == [(C.COSTS, 1500), (C.PRINCIPAL, 38500)]
    assert res.unallocated_cents == 0
    lines.append(L(4, D(2024, 4, 1), T.PAYMENT, -40000, payment_id=1))
    allocs = [AllocationRow(D(2024, 4, 1), a.component, a.amount_cents) for a in res.allocations]
    bal = summarize_invoice(lines, allocs)
    assert bal.balance_cents == 61500  # exactly 615,00 EUR
    assert bal.status == InvoiceStatus.PARTIALLY_PAID
    assert bal.open_costs_cents == 0 and bal.open_principal_cents == 61500
    assert bal.paid_cents == 40000 and bal.charges_cents == 1500


def test_notice_reconciliation_message_from_spec() -> None:
    lines = [L(1, D(2024, 1, 10), T.INVOICE, 100000), L(2, D(2024, 3, 1), T.DUNNING_FEE, 500)]
    claim = NoticeClaim(invoice_id=1, principal_cents=100000, fees_cents=1500, total_cents=101500)
    rec = reconcile_notice(D(2024, 3, 20), [claim], {1: lines})
    assert rec.claimed_total_cents == 101500 and rec.expected_total_cents == 100500 and rec.difference_cents == 1000
    msgs = [i.message for i in rec.issues]
    assert any(m.startswith("Mahnung fordert 1.015,00 €, Konto zeigt 1.005,00 €, Differenz 10,00 €: Gebühr doppelt? "
                            "Zahlung nicht berücksichtigt?") for m in msgs)
    assert not rec.ok


def test_reconciliation_ok_when_ledger_matches() -> None:
    lines = [L(1, D(2024, 1, 10), T.INVOICE, 100000), L(2, D(2024, 3, 1), T.DUNNING_FEE, 500),
             L(3, D(2024, 3, 20), T.DUNNING_FEE, 1000)]
    claim = NoticeClaim(invoice_id=1, principal_cents=100000, fees_cents=1500, total_cents=101500)
    rec = reconcile_notice(D(2024, 3, 20), [claim], {1: lines})
    assert rec.ok and rec.difference_cents == 0
    # an earlier notice only sees entries up to its date
    first = reconcile_notice(D(2024, 3, 1), [NoticeClaim(1, 100000, 500, total_cents=100500)], {1: lines})
    assert first.ok


def test_reconciliation_flags_ignored_payment() -> None:
    lines = [L(1, D(2024, 1, 10), T.INVOICE, 100000), L(2, D(2024, 2, 20), T.PAYMENT, -40000)]
    claim = NoticeClaim(invoice_id=1, principal_cents=100000, total_cents=100000)
    rec = reconcile_notice(D(2024, 3, 1), [claim], {1: lines})
    codes = {i.code for i in rec.issues}
    assert "PAYMENT_IGNORED" in codes and "DIFF" in codes
    assert rec.difference_cents == 40000
    pay = next(i for i in rec.issues if i.code == "PAYMENT_IGNORED")
    assert "400,00 €" in pay.message and "20.02.2024" in pay.message
    # a notice that credits the payment is fine
    ok = reconcile_notice(D(2024, 3, 1), [NoticeClaim(1, 60000, total_cents=60000)], {1: lines}, credited_cents=40000)
    assert ok.ok


def test_reconciliation_claim_lower_and_sum_mismatch() -> None:
    lines = [L(1, D(2024, 1, 10), T.INVOICE, 100000)]
    low = reconcile_notice(D(2024, 3, 1), [NoticeClaim(1, 90000, total_cents=90000)], {1: lines})
    assert low.difference_cents == -10000 and any("weniger" in i.message for i in low.issues)
    bad_sum = reconcile_notice(D(2024, 3, 1), [NoticeClaim(1, 100000, fees_cents=500, total_cents=101000)], {1: lines})
    assert any(i.code == "SUM_MISMATCH" for i in bad_sum.issues)
    assert NoticeClaim(1, 100000, fees_cents=500).computed_total == 100500


def test_notice_referencing_two_invoices() -> None:
    lines = {1: [L(1, D(2024, 1, 1), T.INVOICE, 100000, inv=1)], 2: [L(2, D(2024, 1, 5), T.INVOICE, 50000, inv=2)]}
    claims = [NoticeClaim(1, 100000, fees_cents=500, total_cents=100500),
              NoticeClaim(2, 50000, fees_cents=500, total_cents=50500)]
    for c in claims:
        posts = plan_notice_postings(c, booked={})
        lines[c.invoice_id].append(L(10 + c.invoice_id, D(2024, 3, 1), T.DUNNING_FEE, posts.charges[0].amount_cents,
                                     inv=c.invoice_id))
    rec = reconcile_notice(D(2024, 3, 1), claims, lines)
    assert rec.ok and rec.claimed_total_cents == 151000 and rec.expected_total_cents == 151000
    assert len(rec.per_invoice) == 2


def test_duplicate_notice_import_creates_nothing_twice() -> None:
    claim = NoticeClaim(1, 100000, fees_cents=500, interest_cents=120, flat_fee_cents=4000, other_costs_cents=2500)
    first = plan_notice_postings(claim, booked={})
    assert {p.entry_type: p.amount_cents for p in first.charges} == {
        T.DUNNING_FEE: 500, T.LATE_INTEREST: 120, T.LATE_PAYMENT_FLAT_FEE: 4000, T.COLLECTION_COST: 2500}
    booked = {p.entry_type: p.amount_cents for p in first.charges}
    again = plan_notice_postings(claim, booked=booked)
    assert again.charges == []
    lower = plan_notice_postings(NoticeClaim(1, 100000, fees_cents=300), booked={T.DUNNING_FEE: 500})
    assert lower.charges == [] and lower.lower_than_booked == {T.DUNNING_FEE: 200}


# ---------------------------------------------------------------- balances
def test_reversal_neutralises_entry_and_category_is_kept() -> None:
    lines = [
        L(1, D(2024, 1, 1), T.INVOICE, 100000),
        L(2, D(2024, 2, 1), T.DUNNING_FEE, 500),
        L(3, D(2024, 2, 2), T.REVERSAL, -500, cat=T.DUNNING_FEE, reverses_id=2),
    ]
    bal = summarize_invoice(lines, [])
    assert bal.balance_cents == 100000 and bal.charges_cents == 0 and bal.fees_cents == 0
    active = [x for x in lines if x.entry_id not in {r.reverses_id for r in lines if r.reverses_id}]
    assert [x.entry_id for x in active if x.entry_type != T.REVERSAL] == [1]


def test_summary_all_types_and_credit_balance() -> None:
    lines = [
        L(1, D(2024, 1, 1), T.INVOICE, 100000),
        L(2, D(2024, 1, 2), T.CREDIT_NOTE, -10000),
        L(3, D(2024, 1, 3), T.LATE_INTEREST, 300),
        L(4, D(2024, 1, 3), T.LATE_PAYMENT_FLAT_FEE, 4000),
        L(5, D(2024, 1, 3), T.COLLECTION_COST, 2500),
        L(6, D(2024, 1, 4), T.ADJUSTMENT, -100),
        L(7, D(2024, 1, 5), T.WRITE_OFF, -50),
        L(8, D(2024, 1, 6), T.PAYMENT, -96650),
    ]
    bal = summarize_invoice(lines, [AllocationRow(D(2024, 1, 6), C.COSTS, 6500), AllocationRow(D(2024, 1, 6), C.INTEREST, 300),
                                    AllocationRow(D(2024, 1, 6), C.PRINCIPAL, 89850)])
    assert bal.invoiced_cents == 100000 and bal.credits_cents == 10000 and bal.interest_cents == 300
    assert bal.flat_fee_cents == 4000 and bal.collection_cents == 2500 and bal.adjustments_cents == -100
    assert bal.write_offs_cents == 50 and bal.paid_cents == 96650
    assert bal.balance_cents == 100000 - 10000 + 300 + 4000 + 2500 - 100 - 50 - 96650 == 0
    assert bal.status == InvoiceStatus.PAID and bal.credit_balance_cents == 0
    over = summarize_invoice(lines + [L(9, D(2024, 1, 7), T.PAYMENT, -500)], [])
    assert over.balance_cents == -500 and over.credit_balance_cents == 500 and over.status == InvoiceStatus.PAID
    as_of = summarize_invoice(lines, [], as_of=D(2024, 1, 1))
    assert as_of.balance_cents == 100000 and as_of.status == InvoiceStatus.OPEN


def test_status_derivation_and_manual_overrides() -> None:
    assert derive_status(100, 0, None) == InvoiceStatus.OPEN
    assert derive_status(50, 50, None) == InvoiceStatus.PARTIALLY_PAID
    assert derive_status(0, 100, None) == InvoiceStatus.PAID
    assert derive_status(-5, 105, None) == InvoiceStatus.PAID
    assert derive_status(50, 50, InvoiceStatus.DISPUTED) == InvoiceStatus.DISPUTED
    assert derive_status(0, 100, InvoiceStatus.CANCELLED) == InvoiceStatus.CANCELLED
    assert derive_status(50, 50, InvoiceStatus.OPEN) == InvoiceStatus.PARTIALLY_PAID


def test_balance_from_sums_matches_lines() -> None:
    lines = [L(1, D(2024, 1, 1), T.INVOICE, 100000), L(2, D(2024, 1, 2), T.DUNNING_FEE, 500),
             L(3, D(2024, 1, 3), T.PAYMENT, -200)]
    sums: dict[T, int] = {}
    for x in lines:
        sums[x.category] = sums.get(x.category, 0) + x.amount_cents
    assert balance_from_sums(sums, {}) == summarize_invoice(lines, [])


def test_running_balance() -> None:
    lines = [L(2, D(2024, 1, 5), T.PAYMENT, -300), L(1, D(2024, 1, 1), T.INVOICE, 1000),
             L(3, D(2024, 1, 5), T.DUNNING_FEE, 50)]
    rows = running_balance(lines)
    assert [(r.line.entry_id, r.balance_cents) for r in rows] == [(1, 1000), (2, 700), (3, 750)]
    assert running_balance(lines, opening_cents=100)[-1].balance_cents == 850
    assert running_balance([]) == []


# ---------------------------------------------------------------- allocation
def item(i, due, costs=0, interest=0, principal=0) -> OpenItem:
    return OpenItem(i, due, D(2024, 1, 1), costs, interest, principal)


def test_allocation_statutory_order_single_invoice() -> None:
    res = allocate_payment(10000, [item(1, D(2024, 2, 1), 500, 300, 20000)], AllocationRule.STATUTORY)
    assert [(a.component, a.amount_cents) for a in res.allocations] == [
        (C.COSTS, 500), (C.INTEREST, 300), (C.PRINCIPAL, 9200)]


def test_payment_covering_two_invoices() -> None:
    items = [item(2, D(2024, 3, 1), 0, 0, 50000), item(1, D(2024, 2, 1), 500, 0, 30000)]
    res = allocate_payment(60000, items, AllocationRule.OLDEST_FIRST)
    got = [(a.invoice_id, a.component, a.amount_cents) for a in res.allocations]
    assert got == [(1, C.COSTS, 500), (1, C.PRINCIPAL, 30000), (2, C.PRINCIPAL, 29500)]
    assert res.unallocated_cents == 0
    # statutory: all costs first, then interest, then principal (oldest due first)
    stat = allocate_payment(60000, [item(2, D(2024, 3, 1), 700, 0, 50000), item(1, D(2024, 2, 1), 500, 0, 30000)],
                            AllocationRule.STATUTORY)
    assert [(a.invoice_id, a.component, a.amount_cents) for a in stat.allocations][:2] == [
        (1, C.COSTS, 500), (2, C.COSTS, 700)]
    assert sum(a.amount_cents for a in stat.allocations) == 60000
    assert res.by_invoice()[1] == 30500


def test_overpayment_leaves_unallocated_credit() -> None:
    res = allocate_payment(100000, [item(1, D(2024, 2, 1), 0, 0, 60000)], AllocationRule.STATUTORY)
    assert sum(a.amount_cents for a in res.allocations) == 60000 and res.unallocated_cents == 40000


def test_manual_allocation_and_validation() -> None:
    items = [item(1, D(2024, 2, 1), 500, 0, 1000)]
    res = allocate_payment(900, items, AllocationRule.MANUAL, manual=[(1, C.PRINCIPAL, 800)])
    assert res.unallocated_cents == 100
    with pytest.raises(LedgerError):
        allocate_payment(900, items, AllocationRule.MANUAL, manual=[(1, C.PRINCIPAL, 1000)])
    with pytest.raises(LedgerError):
        allocate_payment(900, items, AllocationRule.MANUAL, manual=[(1, C.COSTS, 600)])  # exceeds open costs
    with pytest.raises(LedgerError):
        allocate_payment(900, items, AllocationRule.MANUAL, manual=[(9, C.COSTS, 1)])
    with pytest.raises(LedgerError):
        allocate_payment(900, items, AllocationRule.MANUAL, manual=[(1, C.COSTS, -1)])
    with pytest.raises(LedgerError):
        allocate_payment(900, items, AllocationRule.MANUAL, manual=None)
    with pytest.raises(LedgerError):
        allocate_payment(0, items, AllocationRule.STATUTORY)


def test_allocation_ignores_already_settled_items() -> None:
    res = allocate_payment(500, [item(1, D(2024, 2, 1), 0, 0, 0), item(2, D(2024, 2, 2), 0, 0, -100)],
                           AllocationRule.OLDEST_FIRST)
    assert res.allocations == [] and res.unallocated_cents == 500


# ---------------------------------------------------------------- interest
RATES = [RatePoint(D(2023, 7, 1), Decimal("3.12")), RatePoint(D(2024, 1, 1), Decimal("3.62")),
         RatePoint(D(2024, 7, 1), Decimal("3.37"))]


def test_annual_rate_lookup() -> None:
    assert annual_rate(D(2024, 3, 1), RATES, Decimal(9)) == Decimal("12.62")
    assert annual_rate(D(2024, 6, 30), RATES, Decimal(9)) == Decimal("12.62")
    assert annual_rate(D(2024, 7, 1), RATES, Decimal(5)) == Decimal("8.37")
    assert annual_rate(D(2020, 1, 1), RATES, Decimal(9)) == Decimal("12.12")  # before table: first known rate
    with pytest.raises(LedgerError):
        annual_rate(D(2024, 1, 1), [], Decimal(9))


def test_interest_simple() -> None:
    res = calculate_interest(100000, D(2024, 1, 1), D(2024, 1, 31), RATES, Decimal(9))
    assert res.days == 30 and res.total_cents == 1037  # 100000 * 12.62 % * 30 / 365 = 1037.26 cents
    assert calculate_interest(100000, D(2024, 1, 31), D(2024, 1, 31), RATES, Decimal(9)).total_cents == 0
    assert calculate_interest(0, D(2024, 1, 1), D(2024, 1, 31), RATES, Decimal(9)).total_cents == 0


def test_interest_with_partial_payment_in_between() -> None:
    res = calculate_interest(100000, D(2024, 1, 1), D(2024, 1, 31), RATES, Decimal(9),
                             principal_payments=[(D(2024, 1, 16), 40000)])
    # 15 days on 1000,00 (Jan 2-16) + 15 days on 600,00 (Jan 17-31)
    assert res.total_cents == 830
    assert [s.principal_cents for s in res.segments] == [100000, 60000]
    assert [s.days for s in res.segments] == [15, 15]


def test_interest_spans_rate_change_and_ignores_payments_before_due() -> None:
    res = calculate_interest(100000, D(2024, 6, 19), D(2024, 7, 10), RATES, Decimal(9),
                             principal_payments=[(D(2024, 6, 1), 0)])
    assert [s.days for s in res.segments] == [11, 10]
    assert [s.annual_rate for s in res.segments] == [Decimal("12.62"), Decimal("12.37")]
    expected = (Decimal(100000) * Decimal("12.62") / 100 * 11 + Decimal(100000) * Decimal("12.37") / 100 * 10) / 365
    assert res.total_cents == int(expected.quantize(Decimal(1), rounding="ROUND_HALF_UP"))
    paid_early = calculate_interest(100000, D(2024, 6, 20), D(2024, 6, 30), RATES, Decimal(9),
                                    principal_payments=[(D(2024, 6, 10), 100000)])
    assert paid_early.total_cents == 0


def test_interest_rounds_half_up() -> None:
    # 1 cent principal-style check: 5000 cents * 8 % * 1 / 365 = 1.0958 -> 1
    r = calculate_interest(5000, D(2024, 1, 1), D(2024, 1, 2), [RatePoint(D(2000, 1, 1), Decimal(-1))], Decimal(9))
    assert r.total_cents == 1
    # exactly 0.5 cents rounds up: 365 cents * 100 % * 1 / 365 = 1; use 36500 * 0.5% / 365... => 0.5
    r2 = calculate_interest(36500, D(2024, 1, 1), D(2024, 1, 2), [RatePoint(D(2000, 1, 1), Decimal(0))], Decimal("0.5"))
    assert r2.total_cents == 1


# ---------------------------------------------------------------- aging
def test_aging_buckets() -> None:
    asof = D(2024, 6, 30)
    assert aging_bucket(None, asof) == "not_due"
    assert aging_bucket(D(2024, 6, 30), asof) == "not_due"
    assert aging_bucket(D(2024, 6, 29), asof) == "1-30"
    assert aging_bucket(D(2024, 5, 31), asof) == "1-30"
    assert aging_bucket(D(2024, 5, 30), asof) == "31-60"
    assert aging_bucket(D(2024, 4, 30), asof) == "61-90"
    assert aging_bucket(D(2024, 4, 1), asof) == "61-90"
    assert aging_bucket(D(2024, 3, 31), asof) == "90+"
    totals = aging_totals([(D(2024, 7, 5), 100), (D(2024, 6, 1), 200), (D(2023, 1, 1), 300), (D(2023, 1, 1), -50),
                           (D(2023, 1, 1), 0)], asof)
    assert list(totals) == list(AGING_BUCKETS)
    assert totals == {"not_due": 100, "1-30": 200, "31-60": 0, "61-90": 0, "90+": 300}
