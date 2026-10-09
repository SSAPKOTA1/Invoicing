"""Input widgets with German number / date handling."""

from __future__ import annotations

from datetime import date

from PySide6.QtCore import QDate, Qt, Signal
from PySide6.QtWidgets import QDateEdit, QLineEdit, QWidget

from supplier_app.errors import ValidationError
from supplier_app.util.money import format_cents, parse_amount
from supplier_app.views.theme import repolish


class MoneyEdit(QLineEdit):
    """Euro amount entry: accepts ``1.234,56``; ``cents()`` is ``None`` when empty or invalid."""

    changed = Signal()

    def __init__(self, parent: QWidget | None = None, allow_negative: bool = False) -> None:
        super().__init__(parent)
        self.allow_negative = allow_negative
        self.setPlaceholderText("0,00")
        self.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.editingFinished.connect(self._normalize)
        self.textChanged.connect(lambda _t: self.changed.emit())

    def cents(self) -> int | None:
        text = self.text().strip()
        if not text:
            return None
        try:
            value = parse_amount(text)
        except ValidationError:
            return None
        return value if (value >= 0 or self.allow_negative) else None

    def set_cents(self, cents: int | None) -> None:
        self.setText("" if cents is None else format_cents(cents, symbol=False))
        self._mark()

    def _normalize(self) -> None:
        value = self.cents()
        if value is not None:
            self.blockSignals(True)
            self.setText(format_cents(value, symbol=False))
            self.blockSignals(False)
        self._mark()

    def _mark(self) -> None:
        bad = bool(self.text().strip()) and self.cents() is None
        self.setProperty("invalid", bad)
        repolish(self)


def make_date_edit(value: date | None = None) -> QDateEdit:
    edit = QDateEdit()
    edit.setCalendarPopup(True)
    edit.setDisplayFormat("dd.MM.yyyy")
    set_date(edit, value or date.today())
    return edit


def set_date(edit: QDateEdit, value: date | None) -> None:
    value = value or date.today()
    edit.setDate(QDate(value.year, value.month, value.day))


def get_date(edit: QDateEdit) -> date:
    d = edit.date()
    return date(d.year(), d.month(), d.day())
