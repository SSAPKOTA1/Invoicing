"""PIN dialogs: unlock (with lockout countdown), set / change, disable."""

from __future__ import annotations

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QDialog, QLabel, QLineEdit, QWidget

from supplier_app.errors import AuthError, SupplierAppError
from supplier_app.i18n import tr
from supplier_app.services.pin_service import PinService
from supplier_app.views.dialogs.forms import button_box, dialog_root, form_layout, message_label


def _pin_edit() -> QLineEdit:
    e = QLineEdit()
    e.setEchoMode(QLineEdit.EchoMode.Password)
    e.setMaxLength(8)
    e.setPlaceholderText("••••")
    return e


class UnlockDialog(QDialog):
    """Modal lock screen; rejecting it quits the application."""

    def __init__(self, pin: PinService, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.pin = pin
        self.setWindowTitle(tr("pin.unlock.title"))
        self.setModal(True)
        self.resize(380, 220)
        root = dialog_root(self)
        title = QLabel(tr("pin.unlock.text"))
        title.setObjectName("SectionTitle")
        root.addWidget(title)
        self.edit = _pin_edit()
        self.edit.returnPressed.connect(self.accept)
        root.addWidget(self.edit)
        self.error = message_label(danger=True)
        root.addWidget(self.error)
        root.addWidget(button_box(self, tr("pin.unlock.button")))
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._tick()

    def _tick(self) -> None:
        left = self.pin.lockout_seconds_left()
        self.edit.setEnabled(left == 0)
        if left:
            self.error.setText(tr("pin.locked_out", n=left))
            self.error.setVisible(True)
            self._timer.start(1000)
        else:
            self._timer.stop()
            if self.error.text().startswith(tr("pin.locked_out", n=0)[:12]):
                self.error.setVisible(False)

    def accept(self) -> None:
        try:
            ok = self.pin.verify(self.edit.text())
        except AuthError as exc:
            self.error.setText(exc.message)
            self.error.setVisible(True)
            self._tick()
            return
        if ok:
            super().accept()
            return
        self.edit.clear()
        self.error.setText(tr("pin.wrong"))
        self.error.setVisible(True)
        self._tick()


class ChangePinDialog(QDialog):
    """mode: 'set' (no PIN yet), 'change' or 'disable' (both need the current PIN)."""

    def __init__(self, pin: PinService, mode: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.pin, self.mode = pin, mode
        self.setWindowTitle(tr(f"pin.{mode}.title"))
        self.resize(400, 280)
        root = dialog_root(self)
        form = form_layout()
        self.current = _pin_edit()
        self.new = _pin_edit()
        self.repeat = _pin_edit()
        if mode in ("change", "disable"):
            form.addRow(tr("pin.current"), self.current)
        if mode in ("set", "change"):
            form.addRow(tr("pin.new"), self.new)
            form.addRow(tr("pin.repeat"), self.repeat)
        root.addLayout(form)
        hint = QLabel(tr("pin.hint"))
        hint.setObjectName("Muted")
        hint.setWordWrap(True)
        root.addWidget(hint)
        self.error = message_label(danger=True)
        root.addWidget(self.error)
        root.addWidget(button_box(self))

    def accept(self) -> None:
        try:
            if self.mode == "disable":
                self.pin.disable(self.current.text())
            else:
                if self.new.text() != self.repeat.text():
                    raise AuthError(tr("pin.mismatch"))
                self.pin.set_pin(self.new.text(), self.current.text() if self.mode == "change" else None)
        except SupplierAppError as exc:
            self.error.setText(exc.message)
            self.error.setVisible(True)
            return
        super().accept()
