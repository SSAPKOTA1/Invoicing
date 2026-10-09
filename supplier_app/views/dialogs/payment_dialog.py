"""'Zahlung erfassen': full, partial or multi-invoice payment with allocation preview before saving."""

from __future__ import annotations

from datetime import date

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from supplier_app.controllers.app_controller import AppController
from supplier_app.errors import SupplierAppError
from supplier_app.i18n import tr
from supplier_app.models.enums import AllocationComponent, AllocationRule, InvoiceStatus, PaymentMethod
from supplier_app.services.payment_service import PaymentPreview
from supplier_app.util.dates import format_date
from supplier_app.util.money import format_cents
from supplier_app.views.dialogs.forms import button_box, dialog_root, form_layout, message_label
from supplier_app.views.errors import show_error
from supplier_app.views.widgets.common import button
from supplier_app.views.widgets.inputs import MoneyEdit, get_date, make_date_edit

COMPONENTS = (AllocationComponent.COSTS, AllocationComponent.INTEREST, AllocationComponent.PRINCIPAL)


class PaymentDialog(QDialog):
    def __init__(self, ctrl: AppController, supplier_id: int | None = None, invoice_id: int | None = None,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.ctrl = ctrl
        self.svc = ctrl.ctx.services
        self.setWindowTitle(tr("payment.title"))
        self.resize(860, 760)
        self._invoice_rows: list[int] = []
        self._manual_edits: dict[tuple[int, AllocationComponent], MoneyEdit] = {}
        root = dialog_root(self)
        form = form_layout()
        self.supplier = QComboBox()
        for p in self.svc.suppliers.suppliers():
            self.supplier.addItem(p.name, p.id)
        self.date = make_date_edit()
        self.amount = MoneyEdit()
        self.method = QComboBox()
        for m in PaymentMethod:
            self.method.addItem(tr(f"method.{m.value}"), m)
        self.reference = QLineEdit()
        self.iban = QLineEdit()
        self.notes = QLineEdit()
        self.rule = QComboBox()
        for r in AllocationRule:
            self.rule.addItem(tr(f"rule.{r.value}"), r)
        self.rule.setCurrentIndex(self.rule.findData(self.svc.settings.allocation_rule))
        form.addRow(tr("payment.supplier"), self.supplier)
        row = QHBoxLayout()
        row.addWidget(self.date)
        row.addWidget(QLabel(tr("common.amount")))
        row.addWidget(self.amount)
        row.addWidget(self.method)
        form.addRow(tr("common.date"), row)
        form.addRow(tr("payment.reference"), self.reference)
        form.addRow(tr("payment.iban"), self.iban)
        form.addRow(tr("common.notes"), self.notes)
        form.addRow(tr("payment.rule"), self.rule)
        root.addLayout(form)

        root.addWidget(QLabel(tr("payment.invoices")))
        self.invoice_table = QTableWidget(0, 4)
        self.invoice_table.setHorizontalHeaderLabels([tr("payment.col.pay"), tr("invoice.number"), tr("invoice.due"),
                                                      tr("invoice.open")])
        self.invoice_table.verticalHeader().setVisible(False)
        self.invoice_table.horizontalHeader().setStretchLastSection(True)
        self.invoice_table.setColumnWidth(0, 60)
        self.invoice_table.setColumnWidth(1, 240)
        self.invoice_table.setColumnWidth(2, 120)
        self.invoice_table.setMaximumHeight(170)
        self.invoice_table.itemChanged.connect(lambda _i: self._update())
        root.addWidget(self.invoice_table)
        tools = QHBoxLayout()
        tools.addWidget(button(tr("payment.select_all"), "flat", self._select_all))
        tools.addWidget(button(tr("payment.fill_amount"), "flat", self._fill_amount))
        tools.addStretch(1)
        root.addLayout(tools)

        self.manual_box = QGroupBox(tr("payment.manual"))
        self.manual_layout = QVBoxLayout(self.manual_box)
        self.manual_table = QTableWidget(0, 4)
        self.manual_table.setHorizontalHeaderLabels([tr("invoice.number"), tr("component.costs"),
                                                     tr("component.interest"), tr("component.principal")])
        self.manual_table.verticalHeader().setVisible(False)
        self.manual_table.horizontalHeader().setStretchLastSection(True)
        self.manual_table.setMaximumHeight(150)
        self.manual_layout.addWidget(self.manual_table)
        root.addWidget(self.manual_box)

        root.addWidget(QLabel(tr("payment.preview")))
        self.preview_table = QTableWidget(0, 5)
        self.preview_table.setHorizontalHeaderLabels([tr("invoice.number"), tr("payment.before"), tr("payment.applied"),
                                                      tr("payment.after"), tr("invoice.status")])
        self.preview_table.verticalHeader().setVisible(False)
        self.preview_table.horizontalHeader().setStretchLastSection(True)
        self.preview_table.setMaximumHeight(170)
        root.addWidget(self.preview_table)
        self.summary = QLabel()
        self.summary.setObjectName("Muted")
        self.summary.setWordWrap(True)
        root.addWidget(self.summary)
        self.error = message_label(danger=True)
        root.addWidget(self.error)
        self.buttons = button_box(self, tr("payment.book"))
        root.addWidget(self.buttons)

        self.supplier.currentIndexChanged.connect(self._load_invoices)
        self.rule.currentIndexChanged.connect(self._update)
        self.amount.changed.connect(self._update)
        self.date.dateChanged.connect(lambda _d: None)
        if supplier_id is not None:
            self.supplier.setCurrentIndex(max(0, self.supplier.findData(supplier_id)))
        self._load_invoices(preselect=invoice_id)

    # -- data -----------------------------------------------------------------------------------------
    def _load_invoices(self, *_args, preselect: int | None = None) -> None:
        sid = self.supplier.currentData()
        self.invoice_table.blockSignals(True)
        self.invoice_table.setRowCount(0)
        self._invoice_rows = []
        states = [s for s in self.svc.ledger.invoice_states(supplier_id=sid)
                  if s.balance.balance_cents > 0 and s.invoice.status != InvoiceStatus.CANCELLED] if sid else []
        states.sort(key=lambda s: s.invoice.due_date or date.max)
        for s in states:
            r = self.invoice_table.rowCount()
            self.invoice_table.insertRow(r)
            chk = QTableWidgetItem()
            chk.setFlags(Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled)
            chk.setCheckState(Qt.CheckState.Checked if s.invoice.id == preselect else Qt.CheckState.Unchecked)
            self.invoice_table.setItem(r, 0, chk)
            for c, text in enumerate((s.invoice.invoice_number, format_date(s.invoice.due_date),
                                      format_cents(s.balance.balance_cents)), start=1):
                it = QTableWidgetItem(text)
                it.setFlags(Qt.ItemFlag.ItemIsEnabled)
                if c == 3:
                    it.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                self.invoice_table.setItem(r, c, it)
            self._invoice_rows.append(s.invoice.id or 0)
        self.invoice_table.blockSignals(False)
        if preselect is not None and self.amount.cents() is None:
            self._fill_amount()
        self._update()

    def selected_invoice_ids(self) -> list[int]:
        return [iid for r, iid in enumerate(self._invoice_rows)
                if self.invoice_table.item(r, 0).checkState() == Qt.CheckState.Checked]

    def _select_all(self) -> None:
        self.invoice_table.blockSignals(True)
        for r in range(self.invoice_table.rowCount()):
            self.invoice_table.item(r, 0).setCheckState(Qt.CheckState.Checked)
        self.invoice_table.blockSignals(False)
        self._fill_amount()

    def _fill_amount(self) -> None:
        ids = self.selected_invoice_ids()
        total = sum(self.svc.ledger.invoice_balance(i).balance_cents for i in ids)
        self.amount.set_cents(total or None)
        self._update()

    # -- manual allocation table ---------------------------------------------------------------------------
    def _rebuild_manual(self, ids: list[int]) -> None:
        self._manual_edits.clear()
        self.manual_table.setRowCount(len(ids))
        for r, iid in enumerate(ids):
            inv = self.svc.invoices.get(iid)
            self.manual_table.setItem(r, 0, QTableWidgetItem(inv.invoice_number))
            item = self.svc.ledger.open_item(iid)
            for c, comp in enumerate(COMPONENTS, start=1):
                edit = MoneyEdit()
                limit = {AllocationComponent.COSTS: item.open_costs_cents, AllocationComponent.INTEREST: item.open_interest_cents,
                         AllocationComponent.PRINCIPAL: item.open_principal_cents}[comp]
                edit.setToolTip(f"{tr('payment.max')}: {format_cents(max(0, limit))}")
                edit.changed.connect(self._update_preview_only)
                self.manual_table.setCellWidget(r, c, edit)
                self._manual_edits[(iid, comp)] = edit

    def _manual_values(self) -> list[tuple[int, AllocationComponent, int]]:
        return [(iid, comp, int(e.cents() or 0)) for (iid, comp), e in self._manual_edits.items() if (e.cents() or 0) > 0]

    # -- preview ---------------------------------------------------------------------------------------------------
    def _update(self, *_args) -> None:
        ids = self.selected_invoice_ids()
        manual = self.rule.currentData() == AllocationRule.MANUAL
        self.manual_box.setVisible(manual)
        if manual and set(ids) != {k[0] for k in self._manual_edits}:
            self._rebuild_manual(ids)
        self._update_preview_only()

    def _update_preview_only(self, *_args) -> None:
        self.error.setVisible(False)
        ok = self.buttons.button(self.buttons.StandardButton.Ok)
        amount = self.amount.cents()
        self.preview_table.setRowCount(0)
        self.summary.setText("")
        ok.setEnabled(False)
        sid = self.supplier.currentData()
        if not amount or not sid:
            return
        try:
            rule = AllocationRule(self.rule.currentData())
            preview: PaymentPreview = self.svc.payments.preview(
                sid, amount, self.selected_invoice_ids(), rule, self._manual_values() if rule == AllocationRule.MANUAL else None)
        except SupplierAppError as exc:
            self.error.setText(exc.message)
            self.error.setVisible(True)
            return
        for row in preview.rows:
            r = self.preview_table.rowCount()
            self.preview_table.insertRow(r)
            vals = [row.invoice_number, format_cents(row.balance_before_cents), format_cents(row.applied_cents),
                    format_cents(row.balance_after_cents), tr(f"status.{row.status_after.value}")]
            for c, text in enumerate(vals):
                it = QTableWidgetItem(text)
                if c in (1, 2, 3):
                    it.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                self.preview_table.setItem(r, c, it)
        parts = [f"{format_cents(a.amount_cents)} {tr('component.' + a.component.value)}" for a in preview.result.allocations]
        text = tr("payment.allocation") + ": " + (", ".join(parts) if parts else "–")
        if preview.unallocated_cents:
            text += "\n" + tr("payment.credit_hint", amount=format_cents(preview.unallocated_cents))
        self.summary.setText(text)
        ok.setEnabled(True)

    # -- save ---------------------------------------------------------------------------------------------------------
    def accept(self) -> None:
        sid, amount = self.supplier.currentData(), self.amount.cents()
        if not sid or not amount:
            return
        rule = AllocationRule(self.rule.currentData())
        try:
            self.payment = self.svc.payments.record_payment(
                sid, get_date(self.date), amount, self.selected_invoice_ids(), rule=rule,
                manual=self._manual_values() if rule == AllocationRule.MANUAL else None,
                method=PaymentMethod(self.method.currentData()), bank_reference=self.reference.text(), iban=self.iban.text(),
                notes=self.notes.text())
        except SupplierAppError as exc:
            self.error.setText(exc.message)
            self.error.setVisible(True)
            return
        except Exception as exc:  # noqa: BLE001
            show_error(self, exc)
            return
        self.ctrl.notify_changed()
        self.ctrl.status.emit(tr("payment.booked"))
        super().accept()

    payment = None


