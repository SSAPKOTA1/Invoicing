"""Reports: Kontoblatt, open items with aging, dunning overview (claimed vs. calculated), payments; export."""

from __future__ import annotations

from datetime import date, timedelta

from PySide6.QtWidgets import QComboBox, QFileDialog, QHBoxLayout, QLabel, QVBoxLayout

from supplier_app.controllers.app_controller import AppController
from supplier_app.errors import SupplierAppError
from supplier_app.i18n import tr
from supplier_app.reports.builders import REPORT_KINDS
from supplier_app.reports.exporters import EXPORTERS
from supplier_app.reports.models import ReportTable
from supplier_app.views.errors import show_error
from supplier_app.views.pages.base import Page
from supplier_app.views.widgets.common import button, page_title
from supplier_app.views.widgets.data_table import Cell, DataTable, Row
from supplier_app.views.widgets.inputs import get_date, make_date_edit


class ReportsPage(Page):
    key = "reports"
    title = "nav.reports"

    def __init__(self, ctrl: AppController) -> None:
        super().__init__(ctrl)
        self.report: ReportTable | None = None
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 20)
        root.addWidget(page_title(tr("nav.reports")))
        bar = QHBoxLayout()
        self.kind = QComboBox()
        for k in REPORT_KINDS:
            self.kind.addItem(tr(f"report.{k}"), k)
        self.supplier = QComboBox()
        self.from_edit = make_date_edit(date.today() - timedelta(days=365))
        self.to_edit = make_date_edit(date.today())
        self.kind.currentIndexChanged.connect(self._kind_changed)
        for w in (self.supplier,):
            w.currentIndexChanged.connect(lambda _i: self.build())
        for e in (self.from_edit, self.to_edit):
            e.dateChanged.connect(lambda _d: self.build())
        bar.addWidget(self.kind)
        bar.addWidget(self.supplier)
        self.from_label, self.to_label = QLabel(tr("report.from")), QLabel(tr("report.to_asof"))
        for w in (self.from_label, self.from_edit, self.to_label, self.to_edit):
            bar.addWidget(w)
        bar.addStretch(1)
        for fmt in ("pdf", "xlsx", "csv"):
            bar.addWidget(button(tr(f"report.export.{fmt}"), "", lambda f=fmt: self.export(f)))
        root.addLayout(bar)
        self.hint = QLabel()
        self.hint.setObjectName("Muted")
        root.addWidget(self.hint)
        self.table = DataTable()
        root.addWidget(self.table, 1)
        self.extra = DataTable(sortable=False)
        self.extra.setMaximumHeight(170)
        root.addWidget(self.extra)
        self._reload_suppliers()
        self._kind_changed()

    def _reload_suppliers(self) -> None:
        cur = self.supplier.currentData()
        self.supplier.blockSignals(True)
        self.supplier.clear()
        self.supplier.addItem(tr("common.all_suppliers"), None)
        for p in self.svc.suppliers.suppliers():
            self.supplier.addItem(p.name, p.id)
        self.supplier.setCurrentIndex(max(0, self.supplier.findData(cur)))
        self.supplier.blockSignals(False)

    def _kind_changed(self) -> None:
        kind = self.kind.currentData()
        statement_like = kind in ("statement", "dunning", "payments")
        self.from_label.setVisible(statement_like)
        self.from_edit.setVisible(statement_like)
        self.to_label.setText(tr("report.to") if statement_like else tr("report.asof"))
        self.build()

    def refresh(self) -> None:
        self._reload_suppliers()
        self.build()

    def build(self) -> None:
        kind = self.kind.currentData()
        sid = self.supplier.currentData()
        self.hint.setText("")
        if kind == "statement" and sid is None:
            self.report = None
            self.table.set_data([], [])
            self.extra.set_data([], [])
            self.hint.setText(tr("report.statement.need_supplier"))
            return
        try:
            self.report = self.ctrl.ctx.reports.build(
                kind, supplier_id=sid, date_from=get_date(self.from_edit) if kind != "open_items" else None,
                date_to=get_date(self.to_edit) if kind != "open_items" else None, as_of=get_date(self.to_edit))
        except SupplierAppError as exc:
            show_error(self, exc)
            return
        rep = self.report
        rows = []
        for r in rep.rows:
            rows.append(Row([Cell(v, align="right") if i in rep.money_columns else v for i, v in enumerate(r)]))
        if rep.totals is not None:
            from supplier_app.util.money import format_cents
            rows.append(Row([Cell(rep.totals_label if (i == 0 and v is None) else
                                  (format_cents(v) if (i in rep.money_columns and isinstance(v, int)) else ("" if v is None else str(v))),
                                  align="right" if i in rep.money_columns else "left", tone="muted") for i, v in enumerate(rep.totals)],
                            tone="ok"))
        self.table.set_data(rep.columns, rows)
        self.table.setSortingEnabled(False)
        if rep.extra:
            ex = rep.extra[0]
            self.extra.set_data(ex.columns, [Row([Cell(v, align="right") if i in ex.money_columns else v for i, v in enumerate(r)])
                                             for r in ex.rows])
        else:
            self.extra.set_data([], [])
        self.extra.setVisible(bool(rep.extra))
        self.hint.setText(f"{rep.title} · {rep.subtitle}")

    def export(self, fmt: str) -> None:
        if self.report is None:
            return
        name = self.report.title.replace(" ", "_").replace("/", "-")
        path, _ = QFileDialog.getSaveFileName(self, tr(f"report.export.{fmt}"),
                                              str(self.ctrl.ctx.paths.exports / f"{name}.{fmt}"), f"*.{fmt}")
        if path:
            self.ctrl.run(EXPORTERS[fmt], self.report, path, parent=self, success=tr("export.done", path=path), notify=False)
