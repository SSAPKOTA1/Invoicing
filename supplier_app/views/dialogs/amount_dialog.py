"""Credit note / write-off / adjustment: amount, date and comment."""

from __future__ import annotations

from datetime import date

from PySide6.QtWidgets import QDialog, QLabel, QLineEdit, QWidget

from supplier_app.i18n import tr
from supplier_app.views.dialogs.forms import button_box, dialog_root, form_layout, message_label
from supplier_app.views.widgets.inputs import MoneyEdit, get_date, make_date_edit


class AmountDialog(QDialog):
    """Collects ``(cents, date, comment)``; ``signed`` allows negative adjustments."""

    def __init__(self, title: str, hint: str = "", signed: bool = False, comment_required: bool = False,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(420, 260)
        self.comment_required = comment_required
        root = dialog_root(self)
        if hint:
            lbl = QLabel(hint)
            lbl.setObjectName("Muted")
            lbl.setWordWrap(True)
            root.addWidget(lbl)
        form = form_layout()
        self.amount = MoneyEdit(allow_negative=signed)
        self.date = make_date_edit()
        self.comment = QLineEdit()
        form.addRow(tr("common.amount"), self.amount)
        form.addRow(tr("common.date"), self.date)
        form.addRow(tr("common.comment"), self.comment)
        root.addLayout(form)
        self.error = message_label(danger=True)
        root.addWidget(self.error)
        root.addWidget(button_box(self, tr("common.book")))

    def accept(self) -> None:
        if not self.amount.cents():
            self.error.setText(tr("error.amount_required"))
            self.error.setVisible(True)
            return
        if self.comment_required and not self.comment.text().strip():
            self.error.setText(tr("error.comment_required"))
            self.error.setVisible(True)
            return
        super().accept()

    def values(self) -> tuple[int, date, str]:
        return int(self.amount.cents() or 0), get_date(self.date), self.comment.text().strip()
