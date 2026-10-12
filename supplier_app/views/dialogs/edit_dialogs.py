"""Small edit dialogs: change a date (Fälligkeit / Frist) and change the company / hotel assignment."""

from __future__ import annotations

from datetime import date, timedelta

from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QWidget

from supplier_app.i18n import tr
from supplier_app.services.organization_service import OrganizationService
from supplier_app.views.dialogs.forms import button_box, dialog_root, form_layout
from supplier_app.views.widgets.common import button
from supplier_app.views.widgets.inputs import get_date, make_date_edit, set_date
from supplier_app.views.widgets.scope_picker import ScopePicker


class DateDialog(QDialog):
    """Edit one date with +14/+30/+60 day shortcuts relative to ``base`` (usually the invoice date)."""

    def __init__(self, title: str, label: str, current: date | None, base: date | None = None,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(460, 160)
        self.base = base or current or date.today()
        root = dialog_root(self)
        form = form_layout()
        self.edit = make_date_edit(current or self.base)
        row = QHBoxLayout()
        row.addWidget(self.edit)
        for days in (14, 30, 60):
            row.addWidget(button(tr("review.due_plus", n=days), "", lambda _c=False, d=days: self._plus(d)))
        row.addStretch(1)
        holder = QWidget()
        holder.setLayout(row)
        row.setContentsMargins(0, 0, 0, 0)
        form.addRow(label, holder)
        root.addLayout(form)
        root.addWidget(QLabel(tr("review.due_plus.hint")))
        root.addWidget(button_box(self))

    def _plus(self, days: int) -> None:
        set_date(self.edit, self.base + timedelta(days=days))

    def value(self) -> date:
        return get_date(self.edit)


class ScopeDialog(QDialog):
    """Assign an invoice (or document) to a company and / or hotel; a hotel fills in its company."""

    def __init__(self, org: OrganizationService, company_id: int | None, hotel_id: int | None,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("org.assign.title"))
        self.resize(560, 150)
        root = dialog_root(self)
        form = form_layout()
        self.picker = ScopePicker(org)
        self.picker.setVisible(True)
        self.picker.set_values(company_id, hotel_id)
        form.addRow(tr("org.assignment"), self.picker)
        root.addLayout(form)
        root.addWidget(button_box(self))

    def values(self) -> tuple[int | None, int | None]:
        return self.picker.company_id, self.picker.hotel_id
