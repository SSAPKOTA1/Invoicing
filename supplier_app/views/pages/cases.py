"""Cases (Bearbeitungsvorgänge): list on the left, full invoice history on the right."""

from __future__ import annotations

from datetime import date

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QComboBox, QHBoxLayout, QLineEdit, QSplitter, QVBoxLayout, QWidget

from supplier_app.controllers.app_controller import AppController
from supplier_app.i18n import level_label, tr
from supplier_app.models.enums import CaseStatus
from supplier_app.util.dates import format_date
from supplier_app.util.money import format_cents
from supplier_app.views.pages.base import Page
from supplier_app.views.widgets.common import page_title
from supplier_app.views.widgets.data_table import Cell, DataTable, Row
from supplier_app.views.widgets.invoice_history import InvoiceHistoryWidget


class CasesPage(Page):
    key = "cases"
    title = "nav.cases"

    def __init__(self, ctrl: AppController) -> None:
        super().__init__(ctrl)
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 20)
        root.addWidget(page_title(tr("nav.cases")))
        split = QSplitter(Qt.Orientation.Horizontal)
        left = QWidget()
        lay = QVBoxLayout(left)
        lay.setContentsMargins(0, 0, 0, 0)
        bar = QHBoxLayout()
        self.status = QComboBox()
        self.status.addItem(tr("common.all"), None)
        for st in CaseStatus:
            self.status.addItem(tr(f"case.{st.value}"), st)
        self.status.currentIndexChanged.connect(lambda _i: self.refresh())
        self.filter = QLineEdit()
        self.filter.setPlaceholderText(tr("common.filter"))
        self.filter.textChanged.connect(lambda t: self.table.set_filter_text(t))
        bar.addWidget(self.status)
        bar.addWidget(self.filter, 1)
        lay.addLayout(bar)
        self.table = DataTable()
        self.table.row_selected.connect(self._selected)
        lay.addWidget(self.table, 1)
        split.addWidget(left)
        self.history = InvoiceHistoryWidget(ctrl)
        split.addWidget(self.history)
        split.setSizes([520, 800])
        split.setChildrenCollapsible(False)
        root.addWidget(split, 1)

    def refresh(self) -> None:
        svc = self.svc
        status = CaseStatus(self.status.currentData()) if self.status.currentData() else None
        keep = self.table.selected_payload()
        rows = []
        for c in svc.cases.list(status=status):
            if c.invoice_id is None:
                continue
            bal = svc.ledger.invoice_balance(c.invoice_id)
            level = svc.dunning.latest_level(c.invoice_id)
            supplier = svc.repos.parties.get(c.supplier_id)
            deadline = svc.history.next_deadline(c.invoice_id)
            overdue = deadline is not None and deadline < date.today() and bal.balance_cents > 0
            rows.append(Row([supplier.name if supplier else "", svc.invoices.get(c.invoice_id).invoice_number,
                             Cell(tr(f"case.{c.status.value}"), c.status.value),
                             level_label(int(level)) if level else "–",
                             Cell(format_cents(bal.balance_cents), bal.balance_cents, "right"),
                             Cell(format_date(deadline), deadline.toordinal() if deadline else 0, tone="bad" if overdue else "")],
                            c.invoice_id))
        self.table.set_data([tr("supplier.name"), tr("invoice.number"), tr("invoice.status"), tr("notice.level"),
                             tr("invoice.open"), tr("history.deadline")], rows, [150, 100, 85, 105, 90, 90])
        if keep is not None:
            self.table.select_payload(keep)
        self.history.refresh()

    def select_invoice(self, invoice_id: int) -> bool:
        self.status.setCurrentIndex(0)
        self.refresh()
        return self.table.select_payload(invoice_id)

    def _selected(self, invoice_id) -> None:
        self.history.set_invoice(invoice_id)
