"""Small helpers for dialog layout."""

from __future__ import annotations

from PySide6.QtWidgets import QDialog, QDialogButtonBox, QFormLayout, QLabel, QVBoxLayout, QWidget

from supplier_app.i18n import tr


def form_layout() -> QFormLayout:
    form = QFormLayout()
    form.setHorizontalSpacing(14)
    form.setVerticalSpacing(10)
    form.setLabelAlignment(form.labelAlignment())
    return form


def button_box(dialog: QDialog, ok_text: str | None = None) -> QDialogButtonBox:
    box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
    ok = box.button(QDialogButtonBox.StandardButton.Ok)
    ok.setText(ok_text or tr("common.save"))
    ok.setProperty("kind", "primary")
    box.button(QDialogButtonBox.StandardButton.Cancel).setText(tr("common.cancel"))
    box.accepted.connect(dialog.accept)
    box.rejected.connect(dialog.reject)
    return box


def message_label(parent: QWidget | None = None, danger: bool = False) -> QLabel:
    label = QLabel(parent)
    label.setObjectName("Danger" if danger else "Warning")
    label.setWordWrap(True)
    label.setVisible(False)
    return label


def dialog_root(dialog: QDialog) -> QVBoxLayout:
    lay = QVBoxLayout(dialog)
    lay.setContentsMargins(20, 18, 20, 16)
    lay.setSpacing(12)
    return lay
