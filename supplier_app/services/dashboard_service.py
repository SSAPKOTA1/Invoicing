"""Dashboard numbers. Reads only from the ledger engine (via LedgerService) and repositories, so every
figure equals the ledger. All KPI values and their drill-down lists share the same selection code."""

from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta

from supplier_app.i18n import level_label, tr
from supplier_app.models.entities import Invoice
from supplier_app.models.enums import (
    CHARGE_TYPES,
    DocumentType,
    DunningLevel,
    InvoiceStatus,
    LedgerEntryType,
    ReviewStatus,
)
from supplier_app.repositories.interfaces import Repositories
from supplier_app.services.base import ServiceBase
from supplier_app.services.dashboard_models import (
    ActivityItem,
    AttentionItem,
    DashboardData,
    DashboardFilter,
    DrillResult,
    DrillRow,
    DrillTarget,
    Kpi,
)
from supplier_app.services.ledger import AGING_BUCKETS, aging_bucket
from supplier_app.services.ledger_service import LedgerService
from supplier_app.services.settings_service import SettingsService
from supplier_app.util.dates import format_date
from supplier_app.util.money import format_cents

_DUNNING_DOCS = {
    DocumentType.PAYMENT_REMINDER, DocumentType.FIRST_DUNNING, DocumentType.SECOND_DUNNING,
    DocumentType.FINAL_DUNNING, DocumentType.COLLECTION_LETTER, DocumentType.COURT_ORDER,
}
_CHARGE_VALUES = {t.value for t in CHARGE_TYPES}
Row = tuple[Invoice, int]  # invoice and its open balance in cents
FORECAST_WINDOWS = (("30", 0, 30), ("60", 31, 60), ("90", 61, 90))


class DashboardService(ServiceBase):
    def __init__(self, repos: Repositories, ledger: LedgerService, settings: SettingsService) -> None:
        super().__init__(repos)
        self.ledger = ledger
        self.settings = settings
        self._names: dict[int, str] = {}
        self._sums: dict[tuple, dict[str, int]] = {}
        self._open_cache: dict[int, tuple[list[Row], list[Row]]] = {}

    # -- selection helpers (shared by KPIs and drill-downs) -------------------------
    def _supplier_name(self, supplier_id: int) -> str:
        if supplier_id not in self._names:
            p = self.repos.parties.get(supplier_id)
            self._names[supplier_id] = p.name if p else "?"
        return self._names[supplier_id]

    def _rows(self, invoices: list[Invoice], as_of: date, supplier_id: int | None) -> list[Row]:
        balances = self.repos.ledger.balances_by_invoice(as_of=as_of, supplier_id=supplier_id)
        return [(inv, balances[inv.id]) for inv in invoices if inv.id in balances]

    def _open(self, rows: list[Row]) -> list[Row]:
        cached = self._open_cache.get(id(rows))
        if cached is None or cached[0] is not rows:
            cached = (rows, [r for r in rows if r[1] > 0 and r[0].status != InvoiceStatus.CANCELLED])
            self._open_cache[id(rows)] = cached
        return cached[1]

    def _select(self, kind: str, param: str, flt: DashboardFilter, states: list[Row]) -> list[Row]:
        open_ = self._open(states)
        asof = flt.as_of
        if kind == "open":
            return open_
        if kind == "overdue":
            return [s for s in open_ if s[0].due_date and s[0].due_date < asof]
        if kind == "due":
            limit = asof + timedelta(days=int(param))
            return [s for s in open_ if s[0].due_date and asof <= s[0].due_date <= limit]
        if kind == "aging":
            return [s for s in open_ if aging_bucket(s[0].due_date, asof) == param]
        if kind == "supplier":
            return [s for s in open_ if s[0].supplier_id == int(param)]
        if kind == "forecast":
            for key, lo, hi in FORECAST_WINDOWS:
                if key == param:
                    return [s for s in open_ if s[0].due_date
                            and asof + timedelta(days=lo) <= s[0].due_date <= asof + timedelta(days=hi)]
            return []
        if kind == "level":
            levels = self._max_levels()
            return [s for s in open_ if levels.get(s[0].id or 0) == int(param)]
        if kind == "credits":
            return [s for s in states if s[1] < 0 and s[0].status != InvoiceStatus.CANCELLED]
        return []

    def _max_levels(self) -> dict[int, int]:
        out: dict[int, int] = {}
        for n in self.repos.notices.list():
            for c in n.claims:
                out[c.invoice_id] = max(out.get(c.invoice_id, 0), int(n.level))
        return out

    # -- main entry ---------------------------------------------------------------
    def build(self, flt: DashboardFilter) -> DashboardData:
        self._sums.clear()
        self._open_cache.clear()
        invoices = self.repos.invoices.list(supplier_id=flt.supplier_id)
        states = self._rows(invoices, flt.as_of, flt.supplier_id)
        prev = flt.previous()
        prev_states = self._rows(invoices, prev.as_of, flt.supplier_id)
        data = DashboardData(filter=flt)
        data.empty = self.repos.ledger.count() == 0

        def money(kind: str, param: str, st: list[Row], f: DashboardFilter) -> int:
            return sum(r[1] for r in self._select(kind, param, f, st))

        k = data.kpis
        k["total_open"] = Kpi("total_open", money("open", "", states, flt), True,
                              money("open", "", prev_states, prev), DrillTarget("open"))
        k["overdue"] = Kpi("overdue", money("overdue", "", states, flt), True,
                           money("overdue", "", prev_states, prev), DrillTarget("overdue"))
        for days in (7, 14, 30):
            k[f"due_{days}"] = Kpi(f"due_{days}", money("due", str(days), states, flt), True, None,
                                   DrillTarget("due", str(days)), higher_is_worse=True)
        paid = -self._period_sum(flt, {LedgerEntryType.PAYMENT.value})
        paid_prev = -self._period_sum(prev, {LedgerEntryType.PAYMENT.value})
        k["paid_period"] = Kpi("paid_period", paid, True, paid_prev, DrillTarget("paid"), higher_is_worse=False)
        charges = self._period_sum(flt, _CHARGE_VALUES)
        k["charges"] = Kpi("charges", charges, True, self._period_sum(prev, _CHARGE_VALUES), DrillTarget("charges"))
        diffs = self._discrepancies(flt)
        k["claim_diff"] = Kpi("claim_diff", sum(abs(d[1]) for d in diffs), True, None, DrillTarget("discrepancies"))
        unapplied = self.repos.ledger.unapplied_by_supplier(as_of=flt.as_of)
        credit_unapplied = -sum(v for sid, v in unapplied.items() if flt.supplier_id in (None, sid) and v < 0)
        credits = -money("credits", "", states, flt) + credit_unapplied
        k["credits"] = Kpi("credits", credits, True, None, DrillTarget("credits"), higher_is_worse=False)
        cases = self.repos.cases.list(supplier_id=flt.supplier_id)
        active = [c for c in cases if c.status.value in ("open", "waiting", "in_dispute")]
        k["open_cases"] = Kpi("open_cases", len(active), False, None, DrillTarget("cases", "open"))
        escalated = self._escalated_cases(active)
        k["escalated_cases"] = Kpi("escalated_cases", len(escalated), False, None, DrillTarget("cases", "escalated"))
        review_docs = self._review_documents(flt)
        k["docs_review"] = Kpi("docs_review", len(review_docs), False, None, DrillTarget("docs", "review"))

        data.aging = {b: money("aging", b, states, flt) for b in AGING_BUCKETS}
        per_supplier: dict[int, int] = defaultdict(int)
        for inv, bal in self._open(states):
            per_supplier[inv.supplier_id] += bal
        data.top_suppliers = [
            (sid, self._supplier_name(sid), cents)
            for sid, cents in sorted(per_supplier.items(), key=lambda kv: kv[1], reverse=True)[:10]
        ]
        data.trend = self._trend(flt)
        levels = self._max_levels()
        counts: dict[int, int] = dict.fromkeys((int(x) for x in DunningLevel), 0)
        for inv, _bal in self._open(states):
            lvl = levels.get(inv.id or 0)
            if lvl:
                counts[lvl] += 1
        data.dunning_levels = counts
        data.charges_by_type = {
            t.value: self._period_sum(flt, {t.value}) for t in (
                LedgerEntryType.DUNNING_FEE, LedgerEntryType.LATE_INTEREST,
                LedgerEntryType.LATE_PAYMENT_FLAT_FEE, LedgerEntryType.COLLECTION_COST)
        }
        data.forecast = [(key, money("forecast", key, states, flt)) for key, _lo, _hi in FORECAST_WINDOWS]
        data.attention = self._attention(flt, states, diffs, review_docs)
        data.activity = self._activity()
        return data

    # -- period sums ----------------------------------------------------------------
    def _period_sum(self, flt: DashboardFilter, types: set[str]) -> int:
        key = (flt.date_from, flt.date_to, flt.supplier_id)
        if key not in self._sums:
            totals: dict[str, int] = defaultdict(int)
            for _b, ctype, total in self.repos.ledger.sums_by_type(
                    date_from=flt.date_from, date_to=flt.date_to, supplier_id=flt.supplier_id):
                totals[ctype] += total
            self._sums[key] = totals
        return sum(v for t, v in self._sums[key].items() if t in types)

    def _trend(self, flt: DashboardFilter) -> list[tuple[str, int, int, int]]:
        end = flt.as_of
        months: list[date] = []
        y, m = end.year, end.month
        for _ in range(12):
            months.append(date(y, m, 1))
            m -= 1
            if m == 0:
                y, m = y - 1, 12
        months.reverse()
        first = months[0]
        opening = sum(t for _b, _c, t in self.repos.ledger.sums_by_type(
            date_to=first - timedelta(days=1), supplier_id=flt.supplier_id))
        rows = self.repos.ledger.sums_by_type(date_from=first, date_to=end, supplier_id=flt.supplier_id,
                                              month_buckets=True)
        by_month: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
        for bucket, ctype, total in rows:
            by_month[bucket][ctype] += total
        out: list[tuple[str, int, int, int]] = []
        running = opening
        for d in months:
            key = f"{d.year:04d}-{d.month:02d}"
            vals = by_month.get(key, {})
            running += sum(vals.values())
            out.append((key, vals.get("INVOICE", 0), -vals.get("PAYMENT", 0), running))
        return out

    # -- lists ------------------------------------------------------------------------
    def _discrepancies(self, flt: DashboardFilter) -> list[tuple[int, int, str]]:
        """(notice_id, signed difference, first message) for notices of the period with a difference."""
        out: list[tuple[int, int, str]] = []
        for n in self.repos.notices.list(supplier_id=flt.supplier_id):
            if not (flt.date_from <= n.notice_date <= flt.date_to):
                continue
            assert n.id is not None
            rec = self.ledger.reconcile_notice(n.id)
            if rec.difference_cents != 0:
                out.append((n.id, rec.difference_cents, rec.issues[0].message if rec.issues else ""))
        return out

    def _escalated_cases(self, cases: list) -> list:
        levels = self._max_levels()
        return [c for c in cases if c.invoice_id and levels.get(c.invoice_id, 0) >= int(DunningLevel.COLLECTION)]

    def _review_documents(self, flt: DashboardFilter) -> list:
        docs = [d for d in self.repos.documents.list() if d.review_status in (ReviewStatus.PENDING, ReviewStatus.NEEDS_REVIEW)]
        if flt.supplier_id is not None:
            docs = [d for d in docs if d.supplier_id in (None, flt.supplier_id)]
        return docs

    def _attention(self, flt: DashboardFilter, states: list[Row], diffs: list[tuple[int, int, str]],
                   review_docs: list) -> dict[str, list[AttentionItem]]:
        today = flt.as_of
        out: dict[str, list[AttentionItem]] = {}
        out["new_notices"] = [
            AttentionItem(d.original_name, f"{tr(f'doctype.{d.doc_type.value}')} · {int(d.confidence * 100)} %",
                          "warn", DrillTarget("docs", "review"), "document", d.id)
            for d in review_docs if d.doc_type in _DUNNING_DOCS][:8]
        deadlines: list[AttentionItem] = []
        latest_deadline: dict[int, date] = {}
        for n in self.repos.notices.list(supplier_id=flt.supplier_id):
            if n.new_deadline:
                for c in n.claims:
                    prev = latest_deadline.get(c.invoice_id)
                    if prev is None or n.new_deadline > prev:
                        latest_deadline[c.invoice_id] = n.new_deadline
        for inv, bal in self._open(states):
            due = latest_deadline.get(inv.id or 0, inv.due_date)
            if due is None:
                continue
            left = (due - today).days
            if 0 <= left <= 7:
                deadlines.append(AttentionItem(
                    f"{self._supplier_name(inv.supplier_id)} – {inv.invoice_number}",
                    f"Frist {format_date(due)} · {format_cents(bal)}",
                    "critical" if left <= 2 else "warn" if left <= 5 else "info", DrillTarget("due", "7"),
                    "invoice", inv.id, left))
        out["deadlines"] = sorted(deadlines, key=lambda a: a.days_left or 0)[:8]
        out["discrepancies"] = [
            AttentionItem(f"Schreiben {nid}: Differenz {format_cents(diff, plus=True)}", msg, "critical",
                          DrillTarget("discrepancies"), "notice", nid)
            for nid, diff, msg in diffs][:8]
        low = self.settings.low_confidence
        out["low_confidence"] = [
            AttentionItem(d.original_name, f"{int(d.confidence * 100)} % Sicherheit", "warn",
                          DrillTarget("docs", "review"), "document", d.id)
            for d in review_docs if d.review_status == ReviewStatus.NEEDS_REVIEW or d.confidence < low][:8]
        out["duplicates"] = self._duplicates(states)
        credits = [
            AttentionItem(
                f"{self._supplier_name(p.payment.supplier_id)}: Guthaben {format_cents(p.amount_cents)}",
                f"Zahlung vom {format_date(p.payment.payment_date)} nicht zugeordnet", "warn",
                DrillTarget("credits"), "supplier", p.payment.supplier_id)
            for p in self._unapplied(flt)]
        credits += [
            AttentionItem(f"{self._supplier_name(inv.supplier_id)} – {inv.invoice_number}: Überzahlung",
                          format_cents(-bal), "warn", DrillTarget("credits"), "invoice", inv.id)
            for inv, bal in states if bal < 0 and inv.status != InvoiceStatus.CANCELLED]
        out["credits"] = credits[:8]
        return out

    def _unapplied(self, flt: DashboardFilter) -> list:
        from supplier_app.services.payment_service import UnappliedPayment  # local import: avoids a cycle at load
        out: list[UnappliedPayment] = []
        for e in self.repos.ledger.unapplied_entries(supplier_id=flt.supplier_id, as_of=flt.as_of):
            pay = self.repos.payments.get(e.payment_id or 0)
            if pay and e.id is not None:
                out.append(UnappliedPayment(pay, e.id, -e.amount_cents))
        return out

    def _duplicates(self, states: list[Row]) -> list[AttentionItem]:
        groups: dict[tuple[int, int], list[Invoice]] = defaultdict(list)
        for inv, _bal in states:
            if inv.status != InvoiceStatus.CANCELLED:
                groups[(inv.supplier_id, inv.gross_cents)].append(inv)
        items: list[AttentionItem] = []
        for (sid, gross), group in groups.items():
            group.sort(key=lambda i: i.invoice_date)
            for a, b in zip(group, group[1:], strict=False):
                if (b.invoice_date - a.invoice_date).days <= 14:
                    items.append(AttentionItem(
                        f"{self._supplier_name(sid)}: {a.invoice_number} / {b.invoice_number}",
                        f"gleicher Betrag {format_cents(gross)} innerhalb von 14 Tagen", "warn", None, "invoice", b.id))
        return items[:8]

    # -- activity ---------------------------------------------------------------------
    _ACTIONS = {
        ("import", "document"): "Dokument importiert", ("confirm", "document"): "Dokument übernommen",
        ("review", "document"): "Dokument geprüft", ("create", "invoice"): "Rechnung angelegt",
        ("create", "payment"): "Zahlung erfasst", ("create", "notice"): "Mahnung gebucht",
        ("reverse", "payment"): "Zahlung storniert", ("reverse", "ledger_entry"): "Buchung storniert",
        ("open_case", "case"): "Vorgang eröffnet", ("case_status", "case"): "Vorgangsstatus geändert",
        ("create", "party"): "Stammdaten angelegt", ("cancel", "invoice"): "Rechnung storniert",
        ("apply_credit", "payment"): "Guthaben zugeordnet",
    }

    def _activity(self, limit: int = 12) -> list[ActivityItem]:
        items: list[ActivityItem] = []
        for a in self.repos.audit.list(limit=limit * 3):
            label = self._ACTIONS.get((a.action, a.entity))
            if label is None:
                continue
            kind = {"invoice": "invoice", "document": "document", "case": "case", "party": "supplier"}.get(a.entity, "")
            text = f"{label}{': ' + a.details if a.details else ''}"
            items.append(ActivityItem(a.created_at[:16].replace("T", " "), text, kind, a.entity_id))
            if len(items) >= limit:
                break
        return items

    # -- drill-down ---------------------------------------------------------------------
    def drilldown(self, target: DrillTarget, flt: DashboardFilter) -> DrillResult:
        kind, param = target.kind, target.param
        if kind in ("open", "overdue", "due", "aging", "supplier", "forecast", "level"):
            states = self._rows(self.repos.invoices.list(supplier_id=flt.supplier_id), flt.as_of, flt.supplier_id)
            sel = self._select(kind, param, flt, states)
            return self._invoice_result(self._title(kind, param), sel)
        if kind == "credits":
            states = self._rows(self.repos.invoices.list(supplier_id=flt.supplier_id), flt.as_of, flt.supplier_id)
            rows = [DrillRow([self._supplier_name(inv.supplier_id), inv.invoice_number,
                              format_date(inv.due_date), format_cents(-bal)], -bal, "invoice", inv.id)
                    for inv, bal in self._select("credits", "", flt, states)]
            for p in self._unapplied(flt):
                rows.append(DrillRow([self._supplier_name(p.payment.supplier_id), "Guthaben (Zahlung)",
                                      format_date(p.payment.payment_date), format_cents(p.amount_cents)],
                                     p.amount_cents, "supplier", p.payment.supplier_id))
            return DrillResult(tr("dash.kpi.credits"), ["Lieferant", "Rechnung", "Datum", "Guthaben"], rows,
                               sum(r.amount_cents for r in rows), len(rows))
        if kind in ("paid", "charges"):
            return self._entries_result(kind, param, flt)
        if kind == "discrepancies":
            rows = []
            for nid, diff, msg in self._discrepancies(flt):
                n = self.repos.notices.get(nid)
                assert n is not None
                inv = self.repos.invoices.get(n.claims[0].invoice_id) if n.claims else None
                rows.append(DrillRow([format_date(n.notice_date), level_label(int(n.level)),
                                      self._supplier_name(n.supplier_id), format_cents(diff, plus=True), msg],
                                     abs(diff), "invoice", inv.id if inv else None))
            return DrillResult(tr("dash.kpi.claim_diff"), ["Datum", "Stufe", "Lieferant", "Differenz", "Hinweis"], rows,
                               sum(r.amount_cents for r in rows), len(rows))
        if kind == "cases":
            cases = [c for c in self.repos.cases.list(supplier_id=flt.supplier_id)
                     if c.status.value in ("open", "waiting", "in_dispute")]
            if param == "escalated":
                cases = self._escalated_cases(cases)
            rows = [DrillRow([c.title, tr(f"case.{c.status.value}"), self._supplier_name(c.supplier_id)], 0, "case", c.id)
                    for c in cases]
            return DrillResult(tr(f"dash.kpi.{'escalated_cases' if param == 'escalated' else 'open_cases'}"),
                               ["Vorgang", "Status", "Lieferant"], rows, None, len(rows))
        if kind == "docs":
            docs = self._review_documents(flt)
            rows = [DrillRow([d.original_name, tr(f"doctype.{d.doc_type.value}"), f"{int(d.confidence * 100)} %",
                              tr(f"review.{d.review_status.value}")], 0, "document", d.id) for d in docs]
            return DrillResult(tr("dash.kpi.docs_review"), ["Dokument", "Typ", "Sicherheit", "Status"], rows, None, len(rows))
        return DrillResult("", [], [], None, 0)

    @staticmethod
    def _title(kind: str, param: str) -> str:
        if kind == "due":
            return tr(f"dash.kpi.due_{param}")
        if kind == "aging":
            return f"{tr('dash.chart.aging')}: {tr(f'aging.{param}')}"
        if kind == "forecast":
            return f"{tr('dash.chart.forecast')} {param}"
        if kind == "level":
            return f"{tr('dash.chart.levels')}: {level_label(int(param or 1))}"
        return {"open": tr("dash.kpi.total_open"), "overdue": tr("dash.kpi.overdue"),
                "supplier": tr("dash.chart.top_suppliers")}.get(kind, kind)

    def _invoice_result(self, title: str, states: list[Row]) -> DrillResult:
        rows = [
            DrillRow([self._supplier_name(inv.supplier_id), inv.invoice_number, format_date(inv.due_date),
                      tr(f"status.{inv.status.value}"), format_cents(bal)], bal, "invoice", inv.id)
            for inv, bal in sorted(states, key=lambda r: r[0].due_date or date.max)
        ]
        return DrillResult(title, ["Lieferant", "Rechnung", "Fällig", "Status", "Offen"], rows,
                           sum(r.amount_cents for r in rows), len(rows))

    def _entries_result(self, kind: str, param: str, flt: DashboardFilter) -> DrillResult:
        wanted = {LedgerEntryType.PAYMENT.value} if kind == "paid" else (
            {param} if param else _CHARGE_VALUES)
        entries = [e for e in self.repos.ledger.list(supplier_id=flt.supplier_id, date_from=flt.date_from,
                                                     date_to=flt.date_to) if e.category_type.value in wanted]
        sign = -1 if kind == "paid" else 1
        rows = [DrillRow([format_date(e.entry_date), self._supplier_name(e.supplier_id),
                          tr(f"entry.{e.entry_type.value}"), e.comment, format_cents(sign * e.amount_cents)],
                         sign * e.amount_cents, "invoice" if e.invoice_id else "supplier", e.invoice_id or e.supplier_id)
                for e in entries]
        title = tr("dash.kpi.paid_period") if kind == "paid" else tr("dash.kpi.charges")
        return DrillResult(title, ["Datum", "Lieferant", "Art", "Text", "Betrag"], rows,
                           sum(r.amount_cents for r in rows), len(rows))
