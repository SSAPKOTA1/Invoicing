"""Modeless window showing the full history of one invoice."""

from __future__ import annotations

from PySide6.QtWidgets import QDialog, QVBoxLayout, QWidget

from supplier_app.controllers.app_controller import AppController
from supplier_app.i18n import tr
from supplier_app.views.widgets.invoice_history import InvoiceHistoryWidget


class InvoiceHistoryDialog(QDialog):
    def __init__(self, ctrl: AppController, invoice_id: int, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("history.window"))
        self.resize(1240, 800)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 14, 14, 14)
        self.widget = InvoiceHistoryWidget(ctrl)
        lay.addWidget(self.widget)
        self.widget.set_invoice(invoice_id)
        ctrl.data_changed.connect(self._reload)
        self.finished.connect(lambda _r: self._disconnect(ctrl))

    def _reload(self) -> None:
        try:
            self.widget.refresh()
        except Exception:  # noqa: BLE001 - e.g. invoice vanished
            self.close()

    def _disconnect(self, ctrl: AppController) -> None:
        try:
            ctrl.data_changed.disconnect(self._reload)
        except (RuntimeError, TypeError):
            pass
