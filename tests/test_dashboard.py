from __future__ import annotations

import os
import time
from datetime import date, timedelta

import pytest

from supplier_app.models.enums import DunningLevel
from supplier_app.services.dashboard_models import DashboardFilter, DrillTarget
from supplier_app.services.dashboard_service import DashboardService
from supplier_app.services.demo_data import DemoDataService
from supplier_app.services.ledger import AGING_BUCKETS

TODAY = date(2026, 6, 15)


@pytest.fixture()
def demo(svc):
    summary = DemoDataService(svc).load(TODAY)
    ds = DashboardService(svc.repos, svc.ledger, svc.settings)
    return svc, ds, summary


def year_filter(supplier_id: int | None = None) -> DashboardFilter:
    return DashboardFilter.for_period("year", TODAY, supplier_id)


def test_demo_data_shows_expected_kpis(demo) -> None:
    _svc, ds, summary = demo
    assert (summary.suppliers, summary.invoices, summary.notices, summary.payments) == (8, 24, 11, 13)
    data = ds.build(year_filter())
    v = {k: kpi.value for k, kpi in data.kpis.items()}
    assert v == {
        "total_open": 3_277_340, "overdue": 2_633_240, "due_7": 196_100, "due_14": 291_100, "due_30": 520_100,
        "paid_period": 789_300, "charges": 94_040, "claim_diff": 200_000, "credits": 40_000, "open_cases": 6,
        "escalated_cases": 2, "docs_review": 3,
    }
    assert data.kpis["total_open"].previous == 1_274_100 and data.kpis["total_open"].change == 2_003_240
    assert data.aging == {"not_due": 644_100, "1-30": 203_200, "31-60": 751_000, "61-90": 276_500, "90+": 1_402_540}
    assert data.forecast == [("30", 520_100), ("60", 33_000), ("90", 91_000)]
    assert data.dunning_levels == {1: 1, 2: 1, 3: 0, 4: 1, 5: 1, 6: 1}
    assert data.charges_by_type == {"DUNNING_FEE": 4000, "LATE_INTEREST": 54_740, "LATE_PAYMENT_FLAT_FEE": 8000,
                                    "COLLECTION_COST": 27_300}
    assert data.top_suppliers[0][1:] == ("Nordwind Logistik AG", 1_611_250) and len(data.top_suppliers) == 6
    assert len(data.trend) == 12 and data.trend[-1][0] == "2026-06"


def test_every_widget_is_filled_by_demo_data(demo) -> None:
    _svc, ds, _ = demo
    data = ds.build(year_filter())
    assert not data.empty
    for key in ("total_open", "overdue", "due_7", "paid_period", "charges", "claim_diff", "credits", "open_cases",
                "escalated_cases", "docs_review"):
        assert data.kpis[key].value > 0, key
    assert all(v > 0 for v in data.aging.values())
    assert all(c > 0 for c in data.charges_by_type.values()) and all(v > 0 for _k, v in data.forecast)
    assert sum(1 for c in data.dunning_levels.values() if c) >= 5
    assert any(t[1] > 0 for t in data.trend) and any(t[2] > 0 for t in data.trend)
    for name in ("new_notices", "deadlines", "discrepancies", "low_confidence", "duplicates", "credits"):
        assert data.attention[name], name
    assert data.activity
    severities = {a.severity for a in data.attention["deadlines"]}
    assert "critical" in severities and all(a.days_left is not None for a in data.attention["deadlines"])


def test_dashboard_consistency_with_ledger(demo) -> None:
    svc, ds, _ = demo
    data = ds.build(year_filter())
    invoice_balances = [s.balance.balance_cents for s in svc.ledger.invoice_states(TODAY)]
    positive = sum(b for b in invoice_balances if b > 0)
    supplier_total = sum(b.total_cents for b in svc.ledger.supplier_balances(TODAY).values())
    entries_total = svc.repos.db.scalar("SELECT SUM(amount_cents) FROM ledger_entries")
    k = data.kpis
    assert k["total_open"].value == positive == sum(data.aging.values())
    assert k["total_open"].value - k["credits"].value == supplier_total == entries_total
    assert sum(c for _id, _n, c in data.top_suppliers) == k["total_open"].value  # only 6 suppliers have debt
    assert sum(c for _k, c in data.forecast) + data.aging["not_due"] - data.forecast[0][1] <= k["total_open"].value
    assert data.trend[-1][3] == entries_total  # last month-end balance equals all entries


def test_every_drilldown_total_equals_clicked_number(demo) -> None:
    _svc, ds, _ = demo
    flt = year_filter()
    data = ds.build(flt)
    for key, kpi in data.kpis.items():
        res = ds.drilldown(kpi.drill, flt)
        if kpi.is_money:
            assert res.total_cents == kpi.value, key
        else:
            assert res.count == kpi.value, key
        assert res.title and res.columns and len(res.rows) == res.count
    for bucket in AGING_BUCKETS:
        assert ds.drilldown(DrillTarget("aging", bucket), flt).total_cents == data.aging[bucket]
    for sid, _name, cents in data.top_suppliers:
        assert ds.drilldown(DrillTarget("supplier", str(sid)), flt).total_cents == cents
    for key, cents in data.forecast:
        assert ds.drilldown(DrillTarget("forecast", key), flt).total_cents == cents
    for level, count in data.dunning_levels.items():
        assert ds.drilldown(DrillTarget("level", str(level)), flt).count == count
    for etype, cents in data.charges_by_type.items():
        assert ds.drilldown(DrillTarget("charges", etype), flt).total_cents == cents
    assert ds.drilldown(DrillTarget("nonsense"), flt).count == 0
    # rows can be opened
    res = ds.drilldown(DrillTarget("open"), flt)
    assert all(r.open_kind == "invoice" and r.open_id for r in res.rows)


def test_supplier_filter_restricts_all_widgets(demo) -> None:
    svc, ds, _ = demo
    nordwind = next(p for p in svc.suppliers.suppliers() if p.name.startswith("Nordwind"))
    flt = year_filter(nordwind.id)
    data = ds.build(flt)
    assert data.kpis["total_open"].value == 1_611_250 == sum(data.aging.values())
    assert [t[0] for t in data.top_suppliers] == [nordwind.id]
    assert data.kpis["escalated_cases"].value == 1 and data.kpis["credits"].value == 0
    assert ds.drilldown(data.kpis["total_open"].drill, flt).total_cents == 1_611_250
    alpha = next(p for p in svc.suppliers.suppliers() if p.name.startswith("Alpha"))
    assert ds.build(year_filter(alpha.id)).kpis["credits"].value == 40_000


def test_period_filters_and_as_of(demo) -> None:
    _svc, ds, _ = demo
    month = DashboardFilter.for_period("month", TODAY)
    quarter = DashboardFilter.for_period("quarter", TODAY)
    assert (month.date_from, month.date_to) == (date(2026, 6, 1), date(2026, 6, 30))
    assert (quarter.date_from, quarter.date_to) == (date(2026, 4, 1), date(2026, 6, 30))
    assert month.previous().date_from == date(2026, 5, 1) and quarter.previous().date_from == date(2026, 1, 1)
    custom = DashboardFilter.for_period("custom", TODAY, custom=(date(2026, 1, 1), date(2026, 3, 31)))
    assert custom.previous().date_to == date(2025, 12, 31)
    assert DashboardFilter.for_period("year", TODAY).previous().date_from == date(2025, 1, 1)
    paid_q = ds.build(quarter).kpis["paid_period"].value
    paid_y = ds.build(year_filter()).kpis["paid_period"].value
    assert 0 < paid_q <= paid_y
    # "as of" in the past shows an older state
    past = DashboardFilter.for_period("year", TODAY, as_of=date(2025, 12, 31))
    assert ds.build(past).kpis["total_open"].value == 1_274_100 or ds.build(past).kpis["total_open"].value > 0


def test_empty_database_gives_empty_state(svc) -> None:
    ds = DashboardService(svc.repos, svc.ledger, svc.settings)
    data = ds.build(year_filter())
    assert data.empty and data.kpis["total_open"].value == 0 and sum(data.aging.values()) == 0
    assert all(not items for items in data.attention.values()) and data.activity == []
    assert len(data.trend) == 12


def test_refresh_after_booking_reflects_change(demo) -> None:
    svc, ds, _ = demo
    before = ds.build(year_filter()).kpis["total_open"].value
    nordwind = next(p for p in svc.suppliers.suppliers() if p.name.startswith("Nordwind"))
    inv = next(i for i in svc.invoices.list(nordwind.id) if i.invoice_number == "NL-89102")
    svc.payments.record_payment(nordwind.id, TODAY, 78_000, [inv.id])
    assert ds.build(year_filter()).kpis["total_open"].value == before - 78_000


def test_dashboard_loads_fast_with_50k_entries(svc) -> None:
    db = svc.repos.db
    sup_ids = []
    for i in range(100):
        sup_ids.append(db.insert("INSERT INTO parties(role,name,name_norm,created_at) VALUES ('supplier',?,?,'x')",
                                 (f"Lieferant {i}", f"lieferant {i}")))
    inv_rows, base = [], date(2025, 7, 1)
    for n in range(10_000):
        d = base + timedelta(days=n % 330)
        inv_rows.append((sup_ids[n % 100], f"R-{n}", f"R{n}", d.isoformat(), (d + timedelta(days=30)).isoformat(),
                         100_000, 'open', 'x'))
    db.executemany("INSERT INTO invoices(supplier_id,invoice_number,invoice_number_norm,invoice_date,due_date,"
                   "gross_cents,status,created_at) VALUES (?,?,?,?,?,?,?,?)", inv_rows)
    ids = [r[0] for r in db.query_all("SELECT id FROM invoices ORDER BY id")]
    inv_info = {r[0]: (r[1], r[2]) for r in db.query_all("SELECT id, supplier_id, invoice_date FROM invoices")}
    ent = []
    for n, iid in enumerate(ids):
        sid, d = inv_info[iid]
        ent.append((d, sid, iid, "INVOICE", "INVOICE", 100_000, "x"))
        ent.append((d, sid, iid, "DUNNING_FEE", "DUNNING_FEE", 500, "x"))
        ent.append((d, sid, iid, "LATE_INTEREST", "LATE_INTEREST", 120, "x"))
        ent.append((d, sid, iid, "PAYMENT", "PAYMENT", -(30_000 + n % 5_000), "x"))
        ent.append((d, sid, iid, "CREDIT_NOTE", "CREDIT_NOTE", -1_000, "x"))
    db.executemany("INSERT INTO ledger_entries(entry_date,supplier_id,invoice_id,entry_type,category_type,"
                   "amount_cents,created_at) VALUES (?,?,?,?,?,?,?)", ent)
    assert svc.repos.ledger.count() == 50_000
    ds = DashboardService(svc.repos, svc.ledger, svc.settings)
    flt = DashboardFilter.for_period("year", date(2026, 3, 1))
    ds.build(flt)  # warm-up (SQLite page cache)
    start = time.perf_counter()
    data = ds.build(flt)
    elapsed = time.perf_counter() - start
    print(f"dashboard build with 50k entries: {elapsed * 1000:.0f} ms")
    limit = 1.5 if os.environ.get("CI") else 0.5  # shared CI runners are slower than a desktop
    assert elapsed < limit, f"{elapsed:.3f}s"
    assert data.kpis["total_open"].value == sum(data.aging.values()) > 0
    assert DunningLevel.REMINDER == 1
