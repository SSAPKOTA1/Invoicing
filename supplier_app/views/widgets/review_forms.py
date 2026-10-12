"""Kind specific parts of the review form. Each form maps :class:`ReviewData` <-> widgets."""

from __future__ import annotations

from collections.abc import Callable
from datetime import timedelta
from decimal import Decimal

from PySide6.QtCore import QObject, Qt
from PySide6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QWidget,
)

from supplier_app.i18n import level_label, tr, tx
from supplier_app.models.enums import DunningLevel, InvoiceStatus, PaymentMethod
from supplier_app.services.container import Services
from supplier_app.services.review_models import ReviewData
from supplier_app.util.dates import format_date
from supplier_app.util.money import format_cents
from supplier_app.views.theme import repolish
from supplier_app.views.widgets.claims_editor import ClaimsEditor
from supplier_app.views.widgets.common import button
from supplier_app.views.widgets.inputs import MoneyEdit, get_date, make_date_edit, set_date
from supplier_app.views.widgets.party_picker import PartyPicker
from supplier_app.views.widgets.scope_picker import ScopePicker


def mark(widget: QWidget, low: bool) -> None:
    widget.setProperty("lowConfidence", bool(low))
    repolish(widget)


class BaseForm(QWidget):
    """Common helpers: supplier combo with 'new' entry, confidence marking, focus tracking."""

    def __init__(self, svc: Services, threshold: float, on_focus: Callable[[str], None]) -> None:
        super().__init__()
        self.svc, self.threshold, self.on_focus = svc, threshold, on_focus
        self.form = QFormLayout(self)
        self.form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapAllRows)  # label above the field: the fields get the full width
        self.form.setHorizontalSpacing(14)
        self.form.setVerticalSpacing(6)
        self._tracked: dict[QObject, str] = {}

    def track(self, widget: QWidget, field: str) -> None:
        self._tracked[widget] = field
        widget.installEventFilter(self)

    def eventFilter(self, obj, event) -> bool:  # noqa: N802 - Qt API
        from PySide6.QtCore import QEvent
        if event.type() == QEvent.Type.FocusIn and obj in self._tracked:
            self.on_focus(self._tracked[obj])
        return False

    def low(self, review: ReviewData, field: str) -> bool:
        return field in review.confidence and review.confidence[field] < self.threshold

    def picker(self, allow_new: bool = True, with_role: bool = False, new_label: str | None = None) -> PartyPicker:
        """Supplier / sender chooser with the recognition's suggestions (see :class:`PartyPicker`)."""
        return PartyPicker(self.svc.suppliers.list(), allow_new=allow_new, with_role=with_role, new_label=new_label)

    def load(self, review: ReviewData) -> None:
        """Fill the widgets from the proposal (overridden by every concrete form)."""
        return None

    def apply(self, review: ReviewData) -> None:
        """Write the widget values back into the review (overridden by every concrete form)."""
        return None


class InvoiceForm(BaseForm):
    def __init__(self, svc, threshold, on_focus) -> None:
        super().__init__(svc, threshold, on_focus)
        self.supplier = self.picker()
        self.number = QLineEdit()
        self.date = make_date_edit()
        self.due = make_date_edit()
        self.vat_rate = QComboBox()
        for r in ("19", "7", "0"):
            self.vat_rate.addItem(f"{r} %", Decimal(r))
        self.net, self.vat, self.gross = MoneyEdit(), MoneyEdit(), MoneyEdit()
        self.scope = ScopePicker(svc.organization)
        due_row = QHBoxLayout()
        due_row.addWidget(self.due)
        for days in (14, 30, 60):
            btn = button(tr("review.due_plus", n=days), "", lambda _c=False, d=days: self._due_plus(d))
            btn.setToolTip(tr("review.due_plus.tip", n=days))
            due_row.addWidget(btn)
        due_row.addStretch(1)
        due_holder = QWidget()
        due_holder.setLayout(due_row)
        due_row.setContentsMargins(0, 0, 0, 0)
        self.form.addRow(tr("invoice.supplier"), self.supplier)
        self.form.addRow(tr("org.assignment"), self.scope)
        self.form.addRow(tr("invoice.number"), self.number)
        self.form.addRow(tr("invoice.date"), self.date)
        self.form.addRow(tr("review.due_label"), due_holder)
        self.form.addRow(tr("invoice.vat_rate"), self.vat_rate)
        self.form.addRow(tr("invoice.net"), self.net)
        self.form.addRow(tr("invoice.vat"), self.vat)
        self.form.addRow(tr("invoice.gross"), self.gross)
        self.due.dateChanged.connect(lambda _d: mark(self.due, False))  # an edited date is no longer a guess
        for w, f in ((self.number, "invoice_number"), (self.date, "document_date"), (self.due, "due_date"),
                     (self.net, "net_cents"), (self.vat, "vat_cents"), (self.gross, "gross_cents"), (self.supplier.combo, "sender"),
                     (self.supplier.new_name, "sender")):
            self.track(w, f)

    def _due_plus(self, days: int) -> None:
        set_date(self.due, get_date(self.date) + timedelta(days=days))
        mark(self.due, False)

    def load(self, r: ReviewData) -> None:
        self.scope.reload()
        self.form.setRowVisible(self.scope, self.svc.organization.configured)
        self.scope.set_values(r.company_id, r.hotel_id)
        self.supplier.set_candidates(r.supplier_candidates, r.supplier_id, r.new_supplier_name, r.author_info,
                                     r.supplier_suggested)
        self.supplier.mark(self.low(r, "sender") or r.supplier_suggested)
        self.number.setText(r.invoice_number)
        set_date(self.date, r.document_date)
        set_date(self.due, r.due_date or r.document_date)
        self.vat_rate.setCurrentIndex(max(0, self.vat_rate.findData(r.vat_rate)))
        self.net.set_cents(r.net_cents)
        self.vat.set_cents(r.vat_cents)
        self.gross.set_cents(r.gross_cents)
        for w, f in ((self.number, "invoice_number"), (self.date, "document_date"), (self.due, "due_date"),
                     (self.net, "net_cents"), (self.vat, "vat_cents"), (self.gross, "gross_cents")):
            mark(w, self.low(r, f))

    def apply(self, r: ReviewData) -> None:
        r.supplier_id = self.supplier.party_id()
        r.new_supplier_name = self.supplier.name_for_new()
        r.invoice_number = self.number.text().strip()
        r.document_date, r.due_date = get_date(self.date), get_date(self.due)
        r.company_id, r.hotel_id = self.scope.company_id, self.scope.hotel_id
        r.vat_rate = self.vat_rate.currentData()
        r.net_cents, r.vat_cents, r.gross_cents = self.net.cents(), self.vat.cents(), self.gross.cents()


class CreditForm(BaseForm):
    def __init__(self, svc, threshold, on_focus) -> None:
        super().__init__(svc, threshold, on_focus)
        self.supplier = self.picker(allow_new=False)
        self.invoice = QComboBox()
        self.number = QLineEdit()
        self.date = make_date_edit()
        self.amount = MoneyEdit()
        self.form.addRow(tr("invoice.supplier"), self.supplier)
        self.form.addRow(tr("review.credit_for"), self.invoice)
        self.form.addRow(tr("review.credit_number"), self.number)
        self.form.addRow(tr("common.date"), self.date)
        self.form.addRow(tr("common.amount"), self.amount)
        self.supplier.changed.connect(lambda: self._fill_invoices(None))
        for w, f in ((self.number, "invoice_number"), (self.date, "document_date"), (self.amount, "gross_cents")):
            self.track(w, f)

    def _fill_invoices(self, select: int | None) -> None:
        self.invoice.clear()
        sid = self.supplier.party_id()
        for inv in self.svc.invoices.list(supplier_id=sid) if sid else []:
            if inv.status != InvoiceStatus.CANCELLED:
                self.invoice.addItem(f"{inv.invoice_number} ({format_cents(inv.gross_cents)})", inv.id)
        self.invoice.setCurrentIndex(max(0, self.invoice.findData(select)))

    def load(self, r: ReviewData) -> None:
        self.supplier.set_candidates(r.supplier_candidates, r.supplier_id, "", r.author_info, r.supplier_suggested)
        self.supplier.mark(r.supplier_suggested)
        self._fill_invoices(r.invoice_id)
        self.number.setText(r.invoice_number)
        set_date(self.date, r.document_date)
        self.amount.set_cents(r.gross_cents)
        mark(self.amount, self.low(r, "gross_cents"))
        mark(self.date, self.low(r, "document_date"))

    def apply(self, r: ReviewData) -> None:
        r.supplier_id = self.supplier.party_id()
        r.invoice_id = self.invoice.currentData()
        r.invoice_number = self.number.text().strip()
        r.document_date = get_date(self.date)
        r.gross_cents = self.amount.cents()


class NoticeForm(BaseForm):
    """Reminder / collection letter: author, creditor (whose ledger), dates, and the invoices it concerns."""

    def __init__(self, svc, threshold, on_focus) -> None:
        super().__init__(svc, threshold, on_focus)
        self.supplier = self.picker(allow_new=True, new_label=tr("review.new_supplier"))
        self.sender = self.picker(allow_new=True, with_role=True, new_label=tr("review.new_sender"))
        self.sender.new_name.setPlaceholderText(tr("review.new_sender_name"))
        self.date = make_date_edit()
        self.level = QComboBox()
        for lv in DunningLevel:
            self.level.addItem(level_label(int(lv)), lv)
        self.deadline = make_date_edit()
        self.credited, self.total = MoneyEdit(), MoneyEdit()
        self.claims = ClaimsEditor(svc)
        self.form.addRow(tr("notice.sender"), self.sender)
        self.form.addRow(tr("review.notice_supplier"), self.supplier)
        self.form.addRow(tr("common.date"), self.date)
        self.form.addRow(tr("notice.level"), self.level)
        self.form.addRow(tr("notice.deadline"), self.deadline)
        self.form.addRow(tr("review.claims"), self.claims)
        self.form.addRow(tr("notice.credited"), self.credited)
        self.form.addRow(tr("notice.total_claimed"), self.total)
        self.supplier.changed.connect(lambda: self.claims.set_supplier(self.supplier.party_id()))
        for w, f in ((self.date, "document_date"), (self.deadline, "due_date"), (self.total, "total_claimed_cents"),
                     (self.sender.combo, "sender"), (self.sender.new_name, "sender")):
            self.track(w, f)

    def load(self, r: ReviewData) -> None:
        self.sender.set_candidates(r.sender_candidates, r.sender_party_id, r.new_sender_name, r.author_info, r.sender_suggested)
        if self.sender.new_role is not None:
            self.sender.new_role.setCurrentIndex(max(0, self.sender.new_role.findData(r.new_sender_role)))
        self.sender.mark(self.low(r, "sender") or r.sender_suggested)
        self.supplier.set_candidates(r.supplier_candidates, r.supplier_id, r.new_supplier_name, None, r.supplier_suggested)
        self.supplier.mark(r.supplier_suggested)
        set_date(self.date, r.document_date)
        if r.level:
            self.level.setCurrentIndex(max(0, self.level.findData(r.level)))
        set_date(self.deadline, r.due_date or r.document_date)
        self.claims.set_supplier(self.supplier.party_id())
        self.claims.set_claims(r.claims, r.invoice_candidates)
        self.credited.set_cents(r.credited_cents or None)
        self.total.set_cents(r.total_claimed_cents or None)
        for w, f in ((self.date, "document_date"), (self.deadline, "due_date"), (self.total, "total_claimed_cents")):
            mark(w, self.low(r, f))

    def apply(self, r: ReviewData) -> None:
        r.supplier_id = self.supplier.party_id()
        r.new_supplier_name = self.supplier.name_for_new()
        r.sender_party_id = self.sender.party_id()
        r.new_sender_name = self.sender.name_for_new()
        r.new_sender_role = self.sender.role_for_new() or r.new_sender_role
        r.document_date, r.due_date = get_date(self.date), get_date(self.deadline)
        r.level = DunningLevel(self.level.currentData())
        r.claims = self.claims.claims()
        r.credited_cents = int(self.credited.cents() or 0)
        r.total_claimed_cents = int(self.total.cents() or 0)


class PaymentForm(BaseForm):
    def __init__(self, svc, threshold, on_focus) -> None:
        super().__init__(svc, threshold, on_focus)
        self.supplier = self.picker(allow_new=False)
        self.date = make_date_edit()
        self.amount = MoneyEdit()
        self.method = QComboBox()
        for m in PaymentMethod:
            self.method.addItem(tr(f"method.{m.value}"), m)
        self.reference, self.iban = QLineEdit(), QLineEdit()
        self.invoices = QListWidget()
        self.invoices.setMaximumHeight(130)
        self.scope = ScopePicker(svc.organization)
        self.form.addRow(tr("payment.supplier"), self.supplier)
        self.form.addRow(tr("org.assignment"), self.scope)
        self.form.addRow(tr("common.date"), self.date)
        self.form.addRow(tr("common.amount"), self.amount)
        self.form.addRow(tr("payment.method"), self.method)
        self.form.addRow(tr("payment.reference"), self.reference)
        self.form.addRow(tr("payment.iban"), self.iban)
        self.form.addRow(tr("payment.invoices"), self.invoices)
        self.supplier.changed.connect(lambda: self._fill(set()))
        for w, f in ((self.date, "document_date"), (self.amount, "payment_amount_cents")):
            self.track(w, f)

    def _fill(self, selected: set[int]) -> None:
        self.invoices.clear()
        sid = self.supplier.party_id()
        for s in self.svc.ledger.invoice_states(supplier_id=sid) if sid else []:
            if s.balance.balance_cents > 0 and s.invoice.status != InvoiceStatus.CANCELLED:
                it = QListWidgetItem(tx(f"{s.invoice.invoice_number} · fällig {format_date(s.invoice.due_date)} · "
                                       f"offen {format_cents(s.balance.balance_cents)}"))
                it.setData(Qt.ItemDataRole.UserRole, s.invoice.id)
                it.setFlags(it.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                it.setCheckState(Qt.CheckState.Checked if s.invoice.id in selected else Qt.CheckState.Unchecked)
                self.invoices.addItem(it)

    def load(self, r: ReviewData) -> None:
        self.scope.reload()
        self.form.setRowVisible(self.scope, self.svc.organization.configured)
        self.scope.set_values(r.company_id, r.hotel_id)
        self.supplier.set_candidates(r.supplier_candidates, r.supplier_id, "", r.author_info, r.supplier_suggested)
        self.supplier.mark(r.supplier_suggested)
        self._fill(set(r.payment_invoice_ids))
        set_date(self.date, r.document_date)
        self.amount.set_cents(r.payment_amount_cents)
        self.reference.setText(r.bank_reference)
        self.iban.setText(r.iban)
        mark(self.amount, self.low(r, "payment_amount_cents"))
        mark(self.date, self.low(r, "document_date"))

    def apply(self, r: ReviewData) -> None:
        r.supplier_id = self.supplier.party_id()
        r.document_date = get_date(self.date)
        r.payment_amount_cents = self.amount.cents()
        r.company_id, r.hotel_id = self.scope.company_id, self.scope.hotel_id
        r.method = PaymentMethod(self.method.currentData())
        r.bank_reference, r.iban = self.reference.text().strip(), self.iban.text().strip()
        r.payment_invoice_ids = [self.invoices.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.invoices.count())
                                 if self.invoices.item(i).checkState() == Qt.CheckState.Checked]


class NoneForm(QLabel):
    """'Only file the document' - nothing is booked."""

    def __init__(self) -> None:
        super().__init__(tr("review.none_hint"))
        self.setWordWrap(True)
        self.setObjectName("Muted")

    def load(self, review: ReviewData) -> None:
        return None

    def apply(self, review: ReviewData) -> None:
        return None
