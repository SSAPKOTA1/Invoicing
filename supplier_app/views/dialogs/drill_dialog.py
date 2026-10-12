"""Filtered list opened by clicking a KPI card, chart segment or list row."""

from __future__ import annotations

from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from supplier_app.controllers.app_controller import AppController
from supplier_app.i18n import tr
from supplier_app.services.dashboard_models import DrillResult
from supplier_app.util.money import format_cents
from supplier_app.views.widgets.common import button
from supplier_app.views.widgets.data_table import Cell, DataTable, Row


class DrillDialog(QDialog):
    def __init__(self, ctrl: AppController, result: DrillResult, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.ctrl, self.result = ctrl, result
        self.setWindowTitle(result.title)
        self.resize(980, 560)
        lay = QVBoxLayout(self)
        title = QLabel(result.title)
        title.setObjectName("PageTitle")
        lay.addWidget(title)
        total = (f"{tr('drill.total')}: {format_cents(result.total_cents)} · " if result.total_cents is not None else "")
        self.summary = QLabel(f"{total}{tr('drill.count', n=result.count)}")
        self.summary.setObjectName("Muted")
        lay.addWidget(self.summary)
        self.table = DataTable()
        rows = []
        for r in result.rows:
            cells = [Cell(c, align="right") if i == len(r.cells) - 1 and result.total_cents is not None else c
                     for i, c in enumerate(r.cells)]
            rows.append(Row(cells, (r.open_kind, r.open_id)))
        self.table.set_data(result.columns, rows)
        self.table.row_activated.connect(self._open)
        lay.addWidget(self.table, 1)
        foot = QHBoxLayout()
        foot.addStretch(1)
        foot.addWidget(button(tr("common.close"), "", self.accept))
        lay.addLayout(foot)

    def _open(self, payload) -> None:
        kind, entity_id = payload
        if not entity_id:
            return
        {"invoice": self.ctrl.open_invoice, "supplier": self.ctrl.open_supplier, "document": self.ctrl.open_document,
         "case": self.ctrl.open_case}.get(kind, self.ctrl.open_invoice).emit(entity_id)
