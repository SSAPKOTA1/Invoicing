"""Manual entry of an invoice (without a scan)."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from PySide6.QtWidgets import QComboBox, QDialog, QLineEdit, QWidget

from supplier_app.controllers.app_controller import AppController
from supplier_app.errors import SupplierAppError
from supplier_app.i18n import tr
from supplier_app.util.money import percent_of
from supplier_app.views.dialogs.forms import button_box, dialog_root, form_layout, message_label
from supplier_app.views.errors import show_error
from supplier_app.views.widgets.inputs import MoneyEdit, get_date, make_date_edit, set_date


class InvoiceDialog(QDialog):
    def __init__(self, ctrl: AppController, supplier_id: int | None = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.ctrl = ctrl
        self.svc = ctrl.ctx.services
        self.setWindowTitle(tr("invoice.new"))
        self.resize(480, 480)
        root = dialog_root(self)
        form = form_layout()
        self.supplier = QComboBox()
        for p in self.svc.suppliers.suppliers():
            self.supplier.addItem(p.name, p.id)
        if supplier_id is not None:
            self.supplier.setCurrentIndex(max(0, self.supplier.findData(supplier_id)))
        self.number = QLineEdit()
        self.date = make_date_edit()
        self.due = make_date_edit()
        self.vat_rate = QComboBox()
        for rate in ("19", "7", "0"):
            self.vat_rate.addItem(f"{rate} %", Decimal(rate))
        self.net, self.vat, self.gross = MoneyEdit(), MoneyEdit(), MoneyEdit()
        self.category = QComboBox()
        self.category.addItem(tr("common.none"), None)
        for c in self.svc.repos.categories.list():
            self.category.addItem(c.name, c.id)
        self.notes = QLineEdit()
        for label, w in (("invoice.supplier", self.supplier), ("invoice.number", self.number), ("invoice.date", self.date),
                         ("invoice.due", self.due), ("invoice.vat_rate", self.vat_rate), ("invoice.net", self.net),
                         ("invoice.vat", self.vat), ("invoice.gross", self.gross), ("invoice.category", self.category),
                         ("common.notes", self.notes)):
            form.addRow(tr(label), w)
        root.addLayout(form)
        self.error = message_label(danger=True)
        root.addWidget(self.error)
        root.addWidget(button_box(self))
        self.date.dateChanged.connect(self._sync_due)
        self.net.editingFinished.connect(self._from_net)
        self.gross.editingFinished.connect(self._from_gross)
        self.vat_rate.currentIndexChanged.connect(self._from_gross)
        self._sync_due()

    def _sync_due(self) -> None:
        set_date(self.due, get_date(self.date) + timedelta(days=self.svc.settings.default_payment_days))

    def _from_net(self) -> None:
        net = self.net.cents()
        if net is not None:
            vat = percent_of(net, self.vat_rate.currentData())
            self.vat.set_cents(vat)
            self.gross.set_cents(net + vat)

    def _from_gross(self) -> None:
        gross = self.gross.cents()
        if gross is not None:
            net = int((Decimal(gross) / (1 + self.vat_rate.currentData() / 100)).quantize(Decimal(1), rounding="ROUND_HALF_UP"))
            self.net.set_cents(net)
            self.vat.set_cents(gross - net)

    def accept(self) -> None:
        try:
            invoice = self.svc.invoices.create_invoice(
                self.supplier.currentData(), self.number.text(), get_date(self.date), gross_cents=self.gross.cents(),
                net_cents=self.net.cents(), vat_cents=self.vat.cents(), vat_rate=self.vat_rate.currentData(),
                due_date=get_date(self.due), notes=self.notes.text(), category_id=self.category.currentData())
        except SupplierAppError as exc:
            self.error.setText(exc.message)
            self.error.setVisible(True)
            return
        except Exception as exc:  # noqa: BLE001
            show_error(self, exc)
            return
        self.invoice_id = invoice.id
        self.ctrl.notify_changed()
        self.ctrl.status.emit(tr("invoice.created"))
        super().accept()

    invoice_id: int | None = None
