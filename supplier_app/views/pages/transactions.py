"""Transactions = the ledger: all entries, filters, reversal from the context menu."""

from __future__ import annotations

from datetime import date, timedelta

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QCheckBox, QComboBox, QHBoxLayout, QLabel, QLineEdit, QMenu, QVBoxLayout

from supplier_app.controllers.app_controller import AppController
from supplier_app.i18n import tr
from supplier_app.models.enums import LedgerEntryType
from supplier_app.util.dates import format_date
from supplier_app.util.money import format_cents
from supplier_app.views.errors import confirm
from supplier_app.views.pages.base import Page
from supplier_app.views.widgets.common import page_title
from supplier_app.views.widgets.data_table import Cell, DataTable, Row
from supplier_app.views.widgets.inputs import get_date, make_date_edit

ROW_LIMIT = 5000


class TransactionsPage(Page):
    key = "transactions"
    title = "nav.transactions"

    def __init__(self, ctrl: AppController) -> None:
        super().__init__(ctrl)
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 20)
        root.addWidget(page_title(tr("nav.transactions")))
        bar = QHBoxLayout()
        self.supplier = QComboBox()
        self.type = QComboBox()
        self.type.addItem(tr("common.all"), None)
        for t in LedgerEntryType:
            self.type.addItem(tr(f"entry.{t.value}"), t)
        self.use_period = QCheckBox(tr("suppliers.period"))
        self.use_period.setChecked(True)
        self.from_edit = make_date_edit(date.today() - timedelta(days=365))
        self.to_edit = make_date_edit(date.today())
        self.text = QLineEdit()
        self.text.setPlaceholderText(tr("common.filter"))
        self.text.textChanged.connect(lambda t: self.table.set_filter_text(t))
        for w in (self.supplier, self.type):
            w.currentIndexChanged.connect(lambda _i: self.refresh())
        self.use_period.stateChanged.connect(lambda _s: self.refresh())
        for e in (self.from_edit, self.to_edit):
            e.dateChanged.connect(lambda _d: self.refresh())
        for w in (self.supplier, self.type, self.use_period, self.from_edit, self.to_edit):
            bar.addWidget(w)
        bar.addWidget(self.text, 1)
        root.addLayout(bar)
        self.table = DataTable()
        self.table.row_activated.connect(lambda p: p and p[0] and self.ctrl.open_invoice.emit(p[0]))
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._menu)
        root.addWidget(self.table, 1)
        self.footer = QLabel()
        self.footer.setObjectName("Muted")
        root.addWidget(self.footer)
        self._entries: dict[int, object] = {}

    def refresh(self) -> None:
        svc = self.svc
        sid = self.supplier.currentData()
        self.supplier.blockSignals(True)
        self.supplier.clear()
        self.supplier.addItem(tr("common.all_suppliers"), None)
        for p in svc.suppliers.list():
            self.supplier.addItem(p.name, p.id)
        self.supplier.setCurrentIndex(max(0, self.supplier.findData(sid)))
        self.supplier.blockSignals(False)
        sid = self.supplier.currentData()
        d_from = get_date(self.from_edit) if self.use_period.isChecked() else None
        d_to = get_date(self.to_edit) if self.use_period.isChecked() else None
        entries = svc.repos.ledger.list(supplier_id=sid, date_from=d_from, date_to=d_to)
        wanted = self.type.currentData()
        if wanted:
            entries = [e for e in entries if e.entry_type == wanted]
        entries.sort(key=lambda e: (e.entry_date, e.id or 0), reverse=True)
        total = len(entries)
        entries = entries[:ROW_LIMIT]
        names = {p.id: p.name for p in svc.suppliers.list()}
        numbers = {i.id: i.invoice_number for i in svc.invoices.list(supplier_id=sid)}
        reversed_ids = {e.reverses_entry_id for e in svc.repos.ledger.list(supplier_id=sid, date_from=d_from) if e.reverses_entry_id}
        self._entries = {e.id: e for e in entries if e.id}
        rows = []
        for e in entries:
            label = tr(f"entry.{e.entry_type.value}")
            if e.entry_type == LedgerEntryType.REVERSAL:
                label += f" ({tr('entry.' + e.category_type.value)})"
            tone = "muted" if e.id in reversed_ids else ""
            rows.append(Row([Cell(format_date(e.entry_date), e.entry_date.toordinal()), Cell(names.get(e.supplier_id, ""), tone=tone),
                             Cell(numbers.get(e.invoice_id, "") if e.invoice_id else tr("transactions.credit_account"), tone=tone),
                             Cell(label, tone=tone),
                             Cell(format_cents(e.amount_cents, plus=True), e.amount_cents, "right",
                                  "ok" if e.amount_cents < 0 else ""), Cell(e.comment, tone=tone),
                             Cell("📎" if e.document_id else "", align="center")], (e.invoice_id, e.id)))
        self.table.set_data([tr("common.date"), tr("supplier.name"), tr("invoice.number"), tr("history.col.kind"),
                             tr("common.amount"), tr("history.col.text"), ""], rows, [95, 220, 150, 190, 120, 360, 40])
        self.table.setSortingEnabled(True)
        shown = len(entries)
        self.footer.setText(tr("transactions.footer", shown=shown, total=total, sum=format_cents(sum(e.amount_cents for e in entries))))
        if total > shown:
            self.footer.setText(self.footer.text() + " · " + tr("transactions.limited", n=ROW_LIMIT))

    def _menu(self, pos) -> None:
        payload = self.table.selected_payload()
        if not payload:
            return
        _inv, entry_id = payload
        entry = self._entries.get(entry_id)
        if entry is None or entry.entry_type in (LedgerEntryType.REVERSAL,):  # type: ignore[attr-defined]
            return
        menu = QMenu(self)
        if entry.payment_id:  # type: ignore[attr-defined]
            menu.addAction(tr("history.reverse_payment"), lambda: self._reverse_payment(entry.payment_id))  # type: ignore[attr-defined]
        elif entry.entry_type != LedgerEntryType.INVOICE:  # type: ignore[attr-defined]
            menu.addAction(tr("history.reverse_entry"), lambda: self._reverse(entry_id))
        if not menu.isEmpty():
            menu.exec(self.table.viewport().mapToGlobal(pos))

    def _reverse(self, entry_id: int) -> None:
        if confirm(self, tr("history.reverse.confirm")):
            self.ctrl.run(self.svc.ledger.reverse_entry, entry_id, "", None, parent=self)

    def _reverse_payment(self, payment_id: int) -> None:
        if confirm(self, tr("history.reverse.confirm")):
            self.ctrl.run(self.svc.payments.reverse_payment, payment_id, "", None, parent=self)
