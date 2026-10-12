"""Define or edit a recurring invoice (rent, leasing ...): schedule, amounts over time, invoice number pattern."""

from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QSpinBox,
    QTableWidget,
    QWidget,
)

from supplier_app.controllers.app_controller import AppController
from supplier_app.errors import SupplierAppError
from supplier_app.i18n import tr
from supplier_app.models.entities import RecurringAmount, RecurringInvoice
from supplier_app.models.enums import RecurrencePeriod
from supplier_app.services.recurring_service import DEFAULT_PATTERNS
from supplier_app.util.dates import format_date
from supplier_app.util.money import format_cents
from supplier_app.views.dialogs.forms import button_box, dialog_root, form_layout, message_label
from supplier_app.views.errors import show_error
from supplier_app.views.widgets.common import button, wrapped_label
from supplier_app.views.widgets.inputs import MoneyEdit, get_date, make_date_edit
from supplier_app.views.widgets.scope_picker import ScopePicker


class RecurringDialog(QDialog):
    def __init__(self, ctrl: AppController, supplier_id: int | None = None, rec: RecurringInvoice | None = None,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.ctrl = ctrl
        self.svc = ctrl.ctx.services
        self.rec = rec
        self.saved: RecurringInvoice | None = None
        self.setWindowTitle(tr("recurring.edit") if rec else tr("recurring.new"))
        self.resize(640, 720)
        root = dialog_root(self)
        root.addWidget(wrapped_label(tr("recurring.hint"), "Muted", 3))
        form = form_layout()
        self.supplier = QComboBox()
        for p in self.svc.suppliers.suppliers():
            self.supplier.addItem(p.name, p.id)
        self.supplier.setCurrentIndex(max(0, self.supplier.findData(rec.supplier_id if rec else supplier_id)))
        self.title_edit = QLineEdit(rec.title if rec else "")
        self.title_edit.setPlaceholderText(tr("recurring.title.placeholder"))
        self.period = QComboBox()
        for p in RecurrencePeriod:
            self.period.addItem(tr(f"recurring.period.{p.value}"), p)
        self.start = make_date_edit(rec.start_date if rec else date.today().replace(day=1))
        self.day = QSpinBox()
        self.day.setRange(1, 31)
        self.day.setSuffix(tr("recurring.day.suffix"))
        self.day.setValue(rec.day_of_month if rec else 1)
        self.has_end = QCheckBox(tr("recurring.end"))
        self.end = make_date_edit(rec.end_date if rec and rec.end_date else date.today())
        end_row = QHBoxLayout()
        end_row.addWidget(self.has_end)
        end_row.addWidget(self.end)
        end_row.addStretch(1)
        self.has_end.setChecked(bool(rec and rec.end_date))
        self.end.setEnabled(self.has_end.isChecked())
        self.has_end.toggled.connect(self.end.setEnabled)
        self.due_days = QSpinBox()
        self.due_days.setRange(0, 365)
        self.due_days.setValue(rec.due_days if rec else 0)
        self.vat = QLineEdit(str(rec.vat_rate).replace(".", ",") if rec else "0")
        self.pattern = QLineEdit(rec.number_pattern if rec else "")
        self.pattern.setToolTip(tr("recurring.pattern.tip"))
        self.notes = QLineEdit(rec.notes if rec else "")
        self.scope = ScopePicker(self.svc.organization)
        self.scope.set_values(rec.company_id if rec else ctrl.scope.company_id, rec.hotel_id if rec else ctrl.scope.hotel_id)
        if rec:
            self.period.setCurrentIndex(max(0, self.period.findData(rec.period)))
        for label, w in (("invoice.supplier", self.supplier), ("recurring.title", self.title_edit), ("org.assignment", self.scope),
                         ("recurring.period", self.period), ("recurring.start", self.start), ("recurring.day", self.day)):
            form.addRow(tr(label), w)
        form.addRow("", end_row)
        for label, w in (("recurring.due_days", self.due_days), ("invoice.vat_rate", self.vat),
                         ("recurring.pattern", self.pattern), ("common.notes", self.notes)):
            form.addRow(tr(label), w)
        root.addLayout(form)

        root.addWidget(QLabel(tr("recurring.amounts")))
        self.amounts = QTableWidget(0, 2)
        self.amounts.setHorizontalHeaderLabels([tr("recurring.amount.from"), tr("recurring.amount.gross")])
        self.amounts.verticalHeader().setVisible(False)
        self.amounts.horizontalHeader().setStretchLastSection(True)
        self.amounts.setColumnWidth(0, 190)
        self.amounts.verticalHeader().setDefaultSectionSize(40)
        self.amounts.setMinimumHeight(120)
        self.amounts.setMaximumHeight(170)
        root.addWidget(self.amounts)
        row = QHBoxLayout()
        row.addWidget(button(tr("recurring.amount.add"), "flat", lambda: self._add_amount(None)))
        row.addWidget(button(tr("recurring.amount.remove"), "flat", self._remove_amount))
        row.addStretch(1)
        root.addLayout(row)
        for a in (rec.amounts if rec else []):
            self._add_amount(a)
        if not rec:
            self._add_amount(None)
        self.preview = wrapped_label("", "Muted", 6)
        root.addWidget(self.preview)
        self.error = message_label(danger=True)
        root.addWidget(self.error)
        root.addWidget(button_box(self))
        for sig in (self.period.currentIndexChanged, self.start.dateChanged, self.day.valueChanged, self.has_end.toggled,
                    self.end.dateChanged, self.title_edit.textChanged, self.pattern.textChanged, self.due_days.valueChanged):
            sig.connect(lambda *_a: self._refresh_preview())
        self.start.dateChanged.connect(self._sync_day)
        self._refresh_preview()

    # -- amounts ------------------------------------------------------------------------------------------
    def _add_amount(self, amount: RecurringAmount | None) -> None:
        r = self.amounts.rowCount()
        self.amounts.insertRow(r)
        edit = make_date_edit(amount.valid_from if amount else get_date(self.start))
        money = MoneyEdit()
        if amount:
            money.set_cents(amount.gross_cents)
        money.changed.connect(self._refresh_preview)
        edit.dateChanged.connect(lambda _d: self._refresh_preview())
        self.amounts.setCellWidget(r, 0, edit)
        self.amounts.setCellWidget(r, 1, money)

    def _remove_amount(self) -> None:
        r = self.amounts.currentRow()
        if r >= 0 and self.amounts.rowCount() > 1:
            self.amounts.removeRow(r)
            self._refresh_preview()

    def _amount_list(self) -> list[RecurringAmount]:
        out = []
        for r in range(self.amounts.rowCount()):
            cents = self.amounts.cellWidget(r, 1).cents()
            if cents:
                out.append(RecurringAmount(get_date(self.amounts.cellWidget(r, 0)), int(cents)))
        return out

    # -- value ------------------------------------------------------------------------------------------------
    def _sync_day(self) -> None:
        if self.rec is None:
            self.day.setValue(get_date(self.start).day)

    def _build(self) -> RecurringInvoice:
        try:
            vat = Decimal(self.vat.text().strip().replace(",", ".") or "0")
        except InvalidOperation as exc:
            raise SupplierAppError(tr("error.number")) from exc
        period = RecurrencePeriod(self.period.currentData())
        rec = self.rec or RecurringInvoice(0, "", period, get_date(self.start))
        rec.supplier_id = int(self.supplier.currentData() or 0)
        rec.title, rec.period, rec.start_date = self.title_edit.text().strip(), period, get_date(self.start)
        rec.day_of_month, rec.end_date = self.day.value(), get_date(self.end) if self.has_end.isChecked() else None
        rec.due_days, rec.vat_rate, rec.number_pattern = self.due_days.value(), vat, self.pattern.text().strip()
        rec.notes, rec.amounts = self.notes.text().strip(), self._amount_list()
        rec.company_id, rec.hotel_id = self.scope.company_id, self.scope.hotel_id
        return rec

    def _refresh_preview(self) -> None:
        try:
            rec = self._build()
            rows = self.svc.recurring.upcoming(rec, 4)
        except Exception:  # noqa: BLE001 - half-filled form
            self.preview.setText("")
            return
        pattern = rec.number_pattern or DEFAULT_PATTERNS[rec.period]
        lines = [tr("recurring.preview.line", date=format_date(d), number=n, amount=format_cents(a) if a else "–") for d, n, a in rows]
        self.preview.setText(tr("recurring.preview", pattern=pattern) + "\n" + "\n".join(lines) if lines else "")

    def accept(self) -> None:
        try:
            rec = self._build()
            self.saved = self.svc.recurring.update(rec) if rec.id else self.svc.recurring.create(rec)
        except SupplierAppError as exc:
            self.error.setText(exc.message)
            self.error.setVisible(True)
            return
        except Exception as exc:  # noqa: BLE001
            show_error(self, exc)
            return
        self.ctrl.notify_changed()
        self.ctrl.status.emit(tr("recurring.saved"))
        super().accept()

