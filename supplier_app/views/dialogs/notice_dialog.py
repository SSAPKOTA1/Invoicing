"""Manual entry of a dunning letter received on paper (no scan needed)."""

from __future__ import annotations

from PySide6.QtWidgets import QComboBox, QDialog, QLabel, QLineEdit, QPlainTextEdit, QWidget

from supplier_app.controllers.app_controller import AppController
from supplier_app.errors import SupplierAppError
from supplier_app.i18n import level_label, tr
from supplier_app.models.enums import DunningLevel, PartyRole, ReferenceType
from supplier_app.services.dunning_service import NoticeDraft
from supplier_app.services.ledger import NoticeClaim
from supplier_app.util.money import format_cents
from supplier_app.views.dialogs.forms import button_box, dialog_root, form_layout, message_label
from supplier_app.views.errors import show_error
from supplier_app.views.widgets.inputs import MoneyEdit, get_date, make_date_edit


class NoticeDialog(QDialog):
    """Cumulative amounts as printed on the letter; only the additional charges are booked."""

    def __init__(self, ctrl: AppController, invoice_id: int, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.ctrl, self.invoice_id = ctrl, invoice_id
        svc = ctrl.ctx.services
        self.invoice = svc.invoices.get(invoice_id)
        self.setWindowTitle(tr("notice.manual.title"))
        self.resize(560, 640)
        root = dialog_root(self)
        hint = QLabel(tr("notice.manual.hint"))
        hint.setObjectName("Muted")
        hint.setWordWrap(True)
        root.addWidget(hint)
        form = form_layout()
        self.sender = QComboBox()
        supplier = svc.suppliers.get(self.invoice.supplier_id)
        self.sender.addItem(supplier.name, supplier.id)
        for p in svc.suppliers.list(PartyRole.COLLECTION_AGENCY):
            if p.represents_supplier_id in (None, supplier.id):
                self.sender.addItem(p.name, p.id)
        self.date = make_date_edit()
        self.level = QComboBox()
        for lv in DunningLevel:
            self.level.addItem(level_label(int(lv)), lv)
        self.deadline = make_date_edit()
        self.principal, self.fees, self.interest = MoneyEdit(), MoneyEdit(), MoneyEdit()
        self.flat, self.other, self.total, self.credited = MoneyEdit(), MoneyEdit(), MoneyEdit(), MoneyEdit()
        bal = svc.ledger.invoice_balance(invoice_id)
        self.principal.set_cents(bal.open_principal_cents if bal.open_principal_cents > 0 else self.invoice.gross_cents)
        self.refs = QPlainTextEdit()
        self.refs.setPlaceholderText(tr("notice.manual.refs_hint"))
        self.refs.setFixedHeight(70)
        form.addRow(tr("notice.sender"), self.sender)
        form.addRow(tr("common.date"), self.date)
        form.addRow(tr("notice.level"), self.level)
        form.addRow(tr("notice.deadline"), self.deadline)
        for label, w in (("notice.principal", self.principal), ("notice.fees", self.fees), ("notice.interest", self.interest),
                         ("notice.flat", self.flat), ("notice.other", self.other), ("notice.total", self.total),
                         ("notice.credited", self.credited)):
            form.addRow(tr(label), w)
        form.addRow(tr("notice.refs"), self.refs)
        self.note = QLineEdit()
        form.addRow(tr("common.notes"), self.note)
        root.addLayout(form)
        self.error = message_label(danger=True)
        root.addWidget(self.error)
        root.addWidget(button_box(self, tr("common.book")))
        for w in (self.principal, self.fees, self.interest, self.flat, self.other):
            w.changed.connect(self._sum)
        self._sum()

    def _sum(self) -> None:
        parts = [w.cents() or 0 for w in (self.principal, self.fees, self.interest, self.flat, self.other)]
        self.total.set_cents(sum(parts))

    def _references(self) -> list[tuple[ReferenceType, str]]:
        out: list[tuple[ReferenceType, str]] = []
        labels = {tr(f"ref.{t.value}").lower(): t for t in ReferenceType}
        for line in self.refs.toPlainText().splitlines():
            if ":" in line:
                key, _, value = line.partition(":")
                out.append((labels.get(key.strip().lower(), ReferenceType.OTHER), value.strip()))
            elif line.strip():
                out.append((ReferenceType.OTHER, line.strip()))
        return out

    def accept(self) -> None:
        claim = NoticeClaim(self.invoice_id, self.principal.cents() or 0, self.fees.cents() or 0,
                            self.interest.cents() or 0, self.flat.cents() or 0, self.other.cents() or 0,
                            self.total.cents() or 0)
        draft = NoticeDraft(
            sender_party_id=self.sender.currentData(), supplier_id=self.invoice.supplier_id,
            notice_date=get_date(self.date), level=DunningLevel(self.level.currentData()), claims=[claim],
            new_deadline=get_date(self.deadline), total_claimed_cents=claim.total_cents,
            credited_cents=self.credited.cents() or 0, references=self._references(), notes=self.note.text())
        try:
            self.booked = self.ctrl.ctx.services.dunning.book_notice(draft)
        except SupplierAppError as exc:
            self.error.setText(exc.message)
            self.error.setVisible(True)
            return
        except Exception as exc:  # noqa: BLE001
            show_error(self, exc)
            return
        self.ctrl.notify_changed()
        msgs = [i.message for i in self.booked.reconciliation.issues] + self.booked.warnings
        self.ctrl.status.emit(tr("notice.booked", amount=format_cents(claim.total_cents)))
        if msgs:
            from supplier_app.views.errors import info
            info(self, tr("notice.discrepancy"), "\n\n".join(msgs))
        super().accept()

    booked = None
