"""Dashboard: filters, KPI cards, charts, attention lists, activity feed, quick actions."""

from __future__ import annotations

from datetime import date

from PySide6.QtCore import QDate, Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDateEdit,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMenu,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from supplier_app.controllers.app_controller import AppController
from supplier_app.i18n import level_label, tr
from supplier_app.reports.dashboard_export import export_pdf, export_png
from supplier_app.services.dashboard_models import AttentionItem, DashboardData, DashboardFilter, DrillTarget
from supplier_app.services.ledger import AGING_BUCKETS
from supplier_app.util.money import format_cents
from supplier_app.views.pages.base import Page
from supplier_app.views.widgets import charts
from supplier_app.views.widgets.attention_list import AttentionList
from supplier_app.views.widgets.common import Card, button, muted, page_title
from supplier_app.views.widgets.kpi_card import KpiCard
from supplier_app.views.widgets.reflow import ReflowGrid

KPI_ORDER = ["total_open", "overdue", "due_7", "due_14", "due_30", "paid_period", "charges", "claim_diff", "credits",
             "open_cases", "escalated_cases", "docs_review"]
PERIODS = ["month", "quarter", "year", "custom"]
ATTENTION = [("new_notices", "dash.attention.new_notices"), ("deadlines", "dash.attention.deadlines"),
             ("discrepancies", "dash.attention.discrepancies"), ("low_confidence", "dash.attention.low_confidence"),
             ("duplicates", "dash.attention.duplicates"), ("credits", "dash.attention.credits")]


class DashboardPage(Page):
    key = "dashboard"
    title = "nav.dashboard"

    def __init__(self, ctrl: AppController) -> None:
        super().__init__(ctrl)
        self.data: DashboardData | None = None
        self._building = False
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        outer.addWidget(self.scroll)
        self.content = QWidget()
        self.scroll.setWidget(self.content)
        root = QVBoxLayout(self.content)
        root.setContentsMargins(24, 20, 24, 24)
        root.setSpacing(16)

        head = QHBoxLayout()
        head.addWidget(page_title(tr("nav.dashboard")))
        head.addStretch(1)
        self.export_btn = QPushButton(tr("dash.export"))
        menu = QMenu(self.export_btn)
        menu.addAction(tr("dash.export.pdf"), self._export_pdf)
        menu.addAction(tr("dash.export.png"), self._export_png)
        self.export_btn.setMenu(menu)
        head.addWidget(self.export_btn)
        root.addLayout(head)
        root.addWidget(self._build_filter_bar())

        self.empty_card = Card()
        title = QLabel(tr("dash.empty.title"))
        title.setObjectName("EmptyTitle")
        self.empty_card.add(title)
        self.empty_card.add(muted(tr("dash.empty.text")))
        row = QHBoxLayout()
        row.addWidget(button(tr("action.import"), "primary", self.ctrl.import_requested.emit))
        row.addWidget(button(tr("action.demo"), "", self._load_demo))
        row.addStretch(1)
        self.empty_card.layout_.addLayout(row)
        root.addWidget(self.empty_card)

        self.kpi_grid = ReflowGrid(min_item_width=215, max_cols=6)
        self.cards: dict[str, KpiCard] = {}
        for key in KPI_ORDER:
            card = KpiCard(key, tr(f"dash.kpi.{key}"))
            card.clicked_key.connect(self._kpi_clicked)
            self.cards[key] = card
            self.kpi_grid.add(card)
        root.addWidget(self.kpi_grid)

        self.chart_grid = ReflowGrid(min_item_width=520, max_cols=2, spacing=14)
        self.chart_cards: dict[str, Card] = {}
        for key, title_key in (("aging", "dash.chart.aging"), ("top_suppliers", "dash.chart.top_suppliers"),
                               ("trend", "dash.chart.trend"), ("levels", "dash.chart.levels"),
                               ("charges", "dash.chart.charges"), ("forecast", "dash.chart.forecast")):
            card = Card(tr(title_key))
            self.chart_cards[key] = card
            self.chart_grid.add(card)
        root.addWidget(self.chart_grid)

        self.attention_grid = ReflowGrid(min_item_width=400, max_cols=3, spacing=14)
        self.lists: dict[str, AttentionList] = {}
        for key, title_key in ATTENTION:
            lst = AttentionList(tr(title_key))
            lst.item_clicked.connect(self._attention_clicked)
            self.lists[key] = lst
            self.attention_grid.add(lst)
        root.addWidget(self.attention_grid)

        bottom = QHBoxLayout()
        bottom.setSpacing(14)
        self.activity_card = Card(tr("dash.activity"))
        self.activity_label = QLabel()
        self.activity_label.setTextFormat(Qt.TextFormat.RichText)
        self.activity_label.setWordWrap(True)
        self.activity_card.add(self.activity_label)
        bottom.addWidget(self.activity_card, 3)
        quick = Card(tr("dash.quick"))
        for text, slot in ((tr("action.import"), self.ctrl.import_requested.emit),
                           (tr("action.payment"), lambda: self.ctrl.payment_requested.emit(None)),
                           (tr("action.new_supplier"), self.ctrl.supplier_requested.emit),
                           (tr("action.search"), self.ctrl.focus_search.emit)):
            quick.add(button(text, "", slot))
        quick.layout_.addStretch(1)
        bottom.addWidget(quick, 1)
        root.addLayout(bottom)
        root.addStretch(1)
        self._reload_suppliers()

    # -- filter bar -------------------------------------------------------------------------------------
    def _build_filter_bar(self) -> QWidget:
        bar = Card()
        row = QHBoxLayout()
        row.setSpacing(10)
        self.period = QComboBox()
        for p in PERIODS:
            self.period.addItem(tr(f"dash.period.{p}"), p)
        saved = self.svc.settings.get("dash_period") or "year"
        self.period.setCurrentIndex(max(0, PERIODS.index(saved) if saved in PERIODS else 2))
        self.period.currentIndexChanged.connect(self._filter_changed)
        self.from_edit = QDateEdit(QDate.currentDate().addMonths(-3))
        self.to_edit = QDateEdit(QDate.currentDate())
        for e in (self.from_edit, self.to_edit):
            e.setCalendarPopup(True)
            e.setDisplayFormat("dd.MM.yyyy")
            e.dateChanged.connect(self._filter_changed)
        self.supplier = QComboBox()
        self.supplier.setMinimumWidth(220)
        self.supplier.currentIndexChanged.connect(self._filter_changed)
        self.as_of = QDateEdit(QDate.currentDate())
        self.as_of.setCalendarPopup(True)
        self.as_of.setDisplayFormat("dd.MM.yyyy")
        self.as_of.dateChanged.connect(self._filter_changed)
        for text, w in ((tr("dash.filter.period"), self.period), ("", self.from_edit), ("–", self.to_edit),
                        (tr("dash.filter.supplier"), self.supplier), (tr("dash.filter.as_of"), self.as_of)):
            if text:
                lbl = QLabel(text)
                lbl.setObjectName("Muted")
                row.addWidget(lbl)
            row.addWidget(w)
        row.addStretch(1)
        row.addWidget(button(tr("common.refresh"), "", self.refresh))
        bar.layout_.addLayout(row)
        self._sync_custom_visibility()
        return bar

    def _sync_custom_visibility(self) -> None:
        custom = self.period.currentData() == "custom"
        self.from_edit.setVisible(custom)
        self.to_edit.setVisible(custom)

    def _reload_suppliers(self) -> None:
        current = self.supplier.currentData()
        self.supplier.blockSignals(True)
        self.supplier.clear()
        self.supplier.addItem(tr("common.all_suppliers"), None)
        for p in self.svc.suppliers.suppliers():
            self.supplier.addItem(p.name, p.id)
        idx = self.supplier.findData(current)
        self.supplier.setCurrentIndex(max(0, idx))
        self.supplier.blockSignals(False)

    def current_filter(self) -> DashboardFilter:
        period = self.period.currentData()
        qd = self.as_of.date()
        custom = (self.from_edit.date().toPython(), self.to_edit.date().toPython())
        return DashboardFilter.for_period(period, date.today(), self.supplier.currentData(),
                                          as_of=date(qd.year(), qd.month(), qd.day()),
                                          custom=custom if period == "custom" else None)

    def _filter_changed(self, *_args) -> None:
        if self._building:
            return
        self._sync_custom_visibility()
        self.svc.settings.set("dash_period", str(self.period.currentData()))
        self.refresh()

    # -- refresh --------------------------------------------------------------------------------------------
    def refresh(self) -> None:
        self._building = True
        try:
            self._reload_suppliers()
        finally:
            self._building = False
        flt = self.current_filter()
        data = self.ctrl.ctx.dashboard.build(flt)
        self.data = data
        theme = self.ctrl.theme
        self.empty_card.setVisible(data.empty)
        for key, card in self.cards.items():
            self._fill_kpi(card, data, key)
        self._fill_charts(data, theme)
        for key, _ in ATTENTION:
            self.lists[key].set_items(data.attention.get(key, []), theme)
        if data.activity:
            lines = "".join(f"<p style='margin:2px 0'><span style='color:gray'>{a.when}</span>&nbsp; {a.text}</p>"
                            for a in data.activity)
        else:
            lines = f"<span style='color:gray'>{tr('dash.activity.empty')}</span>"
        self.activity_label.setText(lines)

    def _fill_kpi(self, card: KpiCard, data: DashboardData, key: str) -> None:
        kpi = data.kpis[key]
        value = format_cents(kpi.value) if kpi.is_money else str(kpi.value)
        delta, tone = "", ""
        if kpi.change is not None:
            arrow = "▲" if kpi.change > 0 else "▼" if kpi.change < 0 else "■"
            amount = format_cents(abs(kpi.change)) if kpi.is_money else str(abs(kpi.change))
            delta = f"{arrow} {amount} {tr('dash.vs_previous')}"
            if kpi.change != 0:
                worse = (kpi.change > 0) == kpi.higher_is_worse
                tone = "bad" if worse else "good"
        card.set_content(value, delta, tone, tr("dash.click_hint"))

    def _fill_charts(self, data: DashboardData, theme: str) -> None:
        def put(key: str, view) -> None:
            card = self.chart_cards[key]
            old = getattr(card, "_chart", None)
            if old is not None:
                card.layout_.removeWidget(old)
                old.setParent(None)
                old.deleteLater()
            card.add(view, 1)
            card._chart = view  # type: ignore[attr-defined]

        buckets = list(AGING_BUCKETS)
        put("aging", charts.bar_chart([tr(f"aging.{b}") for b in buckets], [data.aging[b] for b in buckets],
                                      charts.AGING_COLORS, theme, lambda i: self._drill(DrillTarget("aging", buckets[i]))))
        top = data.top_suppliers
        put("top_suppliers", charts.bar_chart(
            [n for _i, n, _c in top] or [tr("common.none")], [c for _i, _n, c in top] or [0], charts.PALETTE, theme,
            (lambda i: self._drill(DrillTarget("supplier", str(top[i][0])))) if top else None, horizontal=True))
        put("trend", charts.trend_chart([t[0] for t in data.trend], [t[1] for t in data.trend],
                                        [t[2] for t in data.trend], [t[3] for t in data.trend], theme,
                                        (tr("dash.trend.invoiced"), tr("dash.trend.paid"), tr("dash.trend.balance"))))
        levels = sorted(data.dunning_levels)
        put("levels", charts.donut_chart([level_label(lv) for lv in levels], [data.dunning_levels[lv] for lv in levels],
                                         charts.LEVEL_COLORS, theme, lambda i: self._drill(DrillTarget("level", str(levels[i])))))
        types = list(data.charges_by_type)
        put("charges", charts.donut_chart([tr(f"entry.{t}") for t in types], [data.charges_by_type[t] for t in types],
                                          charts.PALETTE, theme,
                                          lambda i: self._drill(DrillTarget("charges", types[i])), money=True))
        windows = [k for k, _v in data.forecast]
        put("forecast", charts.bar_chart([f"{tr('dash.forecast.next')} {k}" for k in windows], [v for _k, v in data.forecast],
                                         charts.PALETTE, theme, lambda i: self._drill(DrillTarget("forecast", windows[i]))))

    # -- actions ---------------------------------------------------------------------------------------------------
    def _drill(self, target: DrillTarget) -> None:
        self.ctrl.drill.emit(target, self.current_filter())

    def _kpi_clicked(self, key: str) -> None:
        if self.data and self.data.kpis[key].drill:
            self._drill(self.data.kpis[key].drill)

    def _attention_clicked(self, item: AttentionItem) -> None:
        if item.open_kind == "invoice" and item.open_id:
            self.ctrl.open_invoice.emit(item.open_id)
        elif item.open_kind == "notice" and item.open_id:
            notice = self.svc.repos.notices.get(item.open_id)
            if notice and notice.claims:
                self.ctrl.open_invoice.emit(notice.claims[0].invoice_id)
        elif item.open_kind == "document" and item.open_id:
            self.ctrl.open_document.emit(item.open_id)
        elif item.open_kind == "supplier" and item.open_id:
            self.ctrl.open_supplier.emit(item.open_id)
        elif item.target:
            self._drill(item.target)

    def _load_demo(self) -> None:
        self.ctrl.run(self.ctrl.ctx.demo.load, parent=self, success=tr("settings.demo.done"))

    def _export_png(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, tr("dash.export.png"), str(self.ctrl.ctx.paths.exports / "dashboard.png"),
                                              "PNG (*.png)")
        if path:
            self.ctrl.run(export_png, self.content, path, parent=self, success=tr("export.done", path=path), notify=False)

    def _export_pdf(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, tr("dash.export.pdf"), str(self.ctrl.ctx.paths.exports / "dashboard.pdf"),
                                              "PDF (*.pdf)")
        if path:
            self.ctrl.run(export_pdf, self.content, path, tr("nav.dashboard"), parent=self,
                          success=tr("export.done", path=path), notify=False)
