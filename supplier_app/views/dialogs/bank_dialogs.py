"""Own bank accounts: list, edit, and choose when a statement does not say which account it belongs to."""

from __future__ import annotations

from PySide6.QtWidgets import QComboBox, QDialog, QHBoxLayout, QLineEdit, QWidget

from supplier_app.controllers.app_controller import AppController
from supplier_app.errors import SupplierAppError
from supplier_app.i18n import tr
from supplier_app.models.entities import BankAccount
from supplier_app.views.dialogs.forms import button_box, dialog_root, form_layout, message_label
from supplier_app.views.errors import confirm, show_error
from supplier_app.views.widgets.common import button, wrapped_label
from supplier_app.views.widgets.data_table import DataTable, Row
from supplier_app.views.widgets.scope_picker import ScopePicker


class BankAccountEditDialog(QDialog):
    def __init__(self, ctrl: AppController, account: BankAccount | None = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.ctrl = ctrl
        self.account = account
        self.saved: BankAccount | None = None
        self.setWindowTitle(tr("bank.account.edit") if account else tr("bank.account.new"))
        self.resize(520, 330)
        root = dialog_root(self)
        form = form_layout()
        self.name = QLineEdit(account.name if account else "")
        self.name.setPlaceholderText(tr("bank.account.name.placeholder"))
        self.iban = QLineEdit(account.iban if account else "")
        self.bic = QLineEdit(account.bic if account else "")
        self.scope = ScopePicker(ctrl.ctx.services.organization)
        self.scope.set_values(account.company_id if account else None, account.hotel_id if account else None)
        self.notes = QLineEdit(account.notes if account else "")
        for label, w in (("bank.account.name", self.name), ("bank.account.iban", self.iban), ("bank.account.bic", self.bic),
                         ("org.assignment", self.scope), ("common.notes", self.notes)):
            form.addRow(tr(label), w)
        root.addLayout(form)
        self.error = message_label(danger=True)
        root.addWidget(self.error)
        root.addWidget(button_box(self))

    def accept(self) -> None:
        acc = self.account or BankAccount("", "")
        acc.name, acc.iban, acc.bic = self.name.text().strip(), self.iban.text().strip(), self.bic.text().strip()
        acc.company_id, acc.hotel_id, acc.notes = self.scope.company_id, self.scope.hotel_id, self.notes.text().strip()
        svc = self.ctrl.ctx.services.bank
        try:
            if acc.id:
                svc.update_account(acc)
            else:
                svc.add_account(acc)
        except SupplierAppError as exc:
            self.error.setText(exc.message)
            self.error.setVisible(True)
            return
        except Exception as exc:  # noqa: BLE001
            show_error(self, exc)
            return
        self.saved = acc
        self.ctrl.notify_changed()
        super().accept()


class BankAccountsDialog(QDialog):
    def __init__(self, ctrl: AppController, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.ctrl = ctrl
        self.setWindowTitle(tr("bank.accounts"))
        self.resize(680, 420)
        root = dialog_root(self)
        root.addWidget(wrapped_label(tr("bank.accounts.hint"), "Muted", 3))
        self.table = DataTable()
        self.table.row_activated.connect(lambda _a: self._edit())
        root.addWidget(self.table, 1)
        bar = QHBoxLayout()
        bar.addWidget(button(tr("bank.account.new"), "primary", self._new))
        bar.addWidget(button(tr("common.edit"), "", self._edit))
        bar.addWidget(button(tr("common.delete"), "danger", self._delete))
        bar.addStretch(1)
        bar.addWidget(button(tr("common.close"), "", self.accept))
        root.addLayout(bar)
        self._fill()

    def _fill(self) -> None:
        org = self.ctrl.ctx.services.organization
        rows = [Row([a.name, a.iban, org.item_label(a.company_id, a.hotel_id) or "–"], a.id)
                for a in self.ctrl.ctx.services.bank.accounts()]
        self.table.set_data([tr("bank.account.name"), tr("bank.account.iban"), tr("org.assignment")], rows, [180, 230, 200])

    def _new(self) -> None:
        if BankAccountEditDialog(self.ctrl, parent=self).exec():
            self._fill()

    def _edit(self) -> None:
        aid = self.table.selected_payload()
        account = self.ctrl.ctx.services.repos.bank.get_account(int(aid)) if aid else None
        if account and BankAccountEditDialog(self.ctrl, account, self).exec():
            self._fill()

    def _delete(self) -> None:
        aid = self.table.selected_payload()
        if aid and confirm(self, tr("bank.account.delete.confirm")):
            if self.ctrl.run(self.ctrl.ctx.services.bank.delete_account, int(aid), parent=self):
                self._fill()


class AccountChooserDialog(QDialog):
    """The statement does not name its account: choose one of the own accounts or create it."""

    def __init__(self, ctrl: AppController, file_name: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.ctrl = ctrl
        self.account_id: int | None = None
        self.setWindowTitle(tr("bank.choose_account"))
        self.resize(520, 220)
        root = dialog_root(self)
        root.addWidget(wrapped_label(tr("bank.choose_account.hint", file=file_name), "", 3))
        row = QHBoxLayout()
        self.combo = QComboBox()
        self.combo.setMinimumHeight(34)
        row.addWidget(self.combo, 1)
        row.addWidget(button(tr("bank.account.new"), "", self._new))
        root.addLayout(row)
        root.addWidget(button_box(self, tr("bank.import")))
        self._fill()

    def _fill(self, select: int | None = None) -> None:
        self.combo.clear()
        for a in self.ctrl.ctx.services.bank.accounts():
            self.combo.addItem(f"{a.name}  ·  {a.iban}", a.id)
        if select is not None:
            self.combo.setCurrentIndex(max(0, self.combo.findData(select)))

    def _new(self) -> None:
        dlg = BankAccountEditDialog(self.ctrl, parent=self)
        if dlg.exec() and dlg.saved:
            self._fill(dlg.saved.id)

    def accept(self) -> None:
        self.account_id = self.combo.currentData()
        if self.account_id is not None:
            super().accept()
