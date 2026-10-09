"""Create / edit a supplier, collection agency or other party."""

from __future__ import annotations

from PySide6.QtWidgets import QComboBox, QDialog, QLineEdit, QPlainTextEdit, QWidget

from supplier_app.controllers.app_controller import AppController
from supplier_app.errors import SupplierAppError
from supplier_app.i18n import tr
from supplier_app.models.entities import Party
from supplier_app.models.enums import PartyRole
from supplier_app.views.dialogs.forms import button_box, dialog_root, form_layout, message_label
from supplier_app.views.errors import show_error


def _lines(text: str) -> list[str]:
    return [ln.strip() for ln in text.splitlines() if ln.strip()]


class SupplierDialog(QDialog):
    def __init__(self, ctrl: AppController, party: Party | None = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.ctrl, self.party = ctrl, party
        self.setWindowTitle(tr("supplier.edit") if party else tr("supplier.new"))
        self.resize(560, 640)
        root = dialog_root(self)
        form = form_layout()
        self.role = QComboBox()
        for r in PartyRole:
            self.role.addItem(tr(f"role.{r.value}"), r)
        self.name = QLineEdit()
        self.aliases = QPlainTextEdit()
        self.aliases.setPlaceholderText(tr("supplier.aliases.hint"))
        self.aliases.setFixedHeight(64)
        self.ibans = QPlainTextEdit()
        self.ibans.setPlaceholderText(tr("supplier.ibans.hint"))
        self.ibans.setFixedHeight(64)
        self.vat = QLineEdit()
        self.tax = QLineEdit()
        self.address = QPlainTextEdit()
        self.address.setFixedHeight(64)
        self.email, self.phone, self.contact, self.terms = QLineEdit(), QLineEdit(), QLineEdit(), QLineEdit()
        self.notes = QPlainTextEdit()
        self.notes.setFixedHeight(64)
        self.represents = QComboBox()
        self.represents.addItem(tr("common.none"), None)
        for s in ctrl.ctx.services.suppliers.suppliers():
            if party is None or s.id != party.id:
                self.represents.addItem(s.name, s.id)
        for label, widget in (("supplier.role", self.role), ("supplier.name", self.name), ("supplier.represents", self.represents),
                              ("supplier.aliases", self.aliases), ("supplier.ibans", self.ibans), ("supplier.vat", self.vat),
                              ("supplier.tax", self.tax), ("supplier.address", self.address), ("supplier.email", self.email),
                              ("supplier.phone", self.phone), ("supplier.contact", self.contact),
                              ("supplier.terms", self.terms), ("supplier.notes", self.notes)):
            form.addRow(tr(label), widget)
        root.addLayout(form)
        self.error = message_label(danger=True)
        root.addWidget(self.error)
        root.addWidget(button_box(self))
        self.role.currentIndexChanged.connect(self._sync_role)
        if party:
            self._load(party)
        self._sync_role()

    def _sync_role(self) -> None:
        self.represents.setEnabled(self.role.currentData() == PartyRole.COLLECTION_AGENCY)

    def _load(self, p: Party) -> None:
        self.role.setCurrentIndex(self.role.findData(p.role))
        self.name.setText(p.name)
        self.aliases.setPlainText("\n".join(p.aliases))
        self.ibans.setPlainText("\n".join(p.ibans))
        self.vat.setText(p.vat_id)
        self.tax.setText(p.tax_number)
        self.address.setPlainText(p.address)
        self.email.setText(p.email)
        self.phone.setText(p.phone)
        self.contact.setText(p.contact)
        self.terms.setText(p.payment_terms)
        self.notes.setPlainText(p.notes)
        self.represents.setCurrentIndex(max(0, self.represents.findData(p.represents_supplier_id)))

    def _collect(self) -> Party:
        role = PartyRole(self.role.currentData())
        return Party(
            id=self.party.id if self.party else None, name=self.name.text().strip(), role=role,
            aliases=_lines(self.aliases.toPlainText()), ibans=_lines(self.ibans.toPlainText()),
            vat_id=self.vat.text().strip(), tax_number=self.tax.text().strip(), address=self.address.toPlainText().strip(),
            email=self.email.text().strip(), phone=self.phone.text().strip(), contact=self.contact.text().strip(),
            payment_terms=self.terms.text().strip(), notes=self.notes.toPlainText().strip(),
            represents_supplier_id=self.represents.currentData() if role == PartyRole.COLLECTION_AGENCY else None)

    def accept(self) -> None:
        party = self._collect()
        svc = self.ctrl.ctx.services.suppliers
        try:
            if self.party:
                svc.update(party)
                self.saved_id = party.id
            else:
                self.saved_id = svc.create(party).id
        except SupplierAppError as exc:
            self.error.setText(exc.message)
            self.error.setVisible(True)
            return
        except Exception as exc:  # noqa: BLE001
            show_error(self, exc)
            return
        self.ctrl.notify_changed()
        super().accept()

    saved_id: int | None = None
