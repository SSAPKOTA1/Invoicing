"""Kind specific parts of the review form. Each form maps :class:`ReviewData` <-> widgets."""

from __future__ import annotations

from collections.abc import Callable
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
    QTableWidget,
    QVBoxLayout,
    QWidget,
)

from supplier_app.i18n import level_label, tr
from supplier_app.models.enums import DunningLevel, InvoiceStatus, PartyRole, PaymentMethod
from supplier_app.services.container import Services
from supplier_app.services.review_models import ClaimInput, ReviewData
from supplier_app.util.dates import format_date
from supplier_app.util.money import format_cents
from supplier_app.views.theme import repolish
from supplier_app.views.widgets.common import button
from supplier_app.views.widgets.inputs import MoneyEdit, get_date, make_date_edit, set_date


def mark(widget: QWidget, low: bool) -> None:
    widget.setProperty("lowConfidence", bool(low))
    repolish(widget)


class BaseForm(QWidget):
    """Common helpers: supplier combo with 'new' entry, confidence marking, focus tracking."""

    def __init__(self, svc: Services, threshold: float, on_focus: Callable[[str], None]) -> None:
        super().__init__()
        self.svc, self.threshold, self.on_focus = svc, threshold, on_focus
        self.form = QFormLayout(self)
        self.form.setHorizontalSpacing(14)
        self.form.setVerticalSpacing(8)
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

    def supplier_combo(self, allow_new: bool = True) -> tuple[QComboBox, QLineEdit]:
        combo = QComboBox()
        if allow_new:
            combo.addItem(tr("review.new_supplier"), None)
        for p in self.svc.suppliers.suppliers():
            combo.addItem(p.name, p.id)
        name = QLineEdit()
        name.setPlaceholderText(tr("review.new_supplier_name"))
        return combo, name

    def load(self, review: ReviewData) -> None:
        """Fill the widgets from the proposal (overridden by every concrete form)."""
        return None

    def apply(self, review: ReviewData) -> None:
        """Write the widget values back into the review (overridden by every concrete form)."""
        return None


class InvoiceForm(BaseForm):
    def __init__(self, svc, threshold, on_focus) -> None:
        super().__init__(svc, threshold, on_focus)
        self.supplier, self.new_name = self.supplier_combo()
        self.number = QLineEdit()
        self.date = make_date_edit()
        self.due = make_date_edit()
        self.vat_rate = QComboBox()
        for r in ("19", "7", "0"):
            self.vat_rate.addItem(f"{r} %", Decimal(r))
        self.net, self.vat, self.gross = MoneyEdit(), MoneyEdit(), MoneyEdit()
        self.form.addRow(tr("invoice.supplier"), self.supplier)
        self.form.addRow("", self.new_name)
        self.form.addRow(tr("invoice.number"), self.number)
        self.form.addRow(tr("invoice.date"), self.date)
        self.form.addRow(tr("invoice.due"), self.due)
        self.form.addRow(tr("invoice.vat_rate"), self.vat_rate)
        self.form.addRow(tr("invoice.net"), self.net)
        self.form.addRow(tr("invoice.vat"), self.vat)
        self.form.addRow(tr("invoice.gross"), self.gross)
        self.supplier.currentIndexChanged.connect(lambda _i: self.new_name.setVisible(self.supplier.currentData() is None))
        for w, f in ((self.number, "invoice_number"), (self.date, "document_date"), (self.due, "due_date"),
                     (self.net, "net_cents"), (self.vat, "vat_cents"), (self.gross, "gross_cents"), (self.supplier, "sender"),
                     (self.new_name, "sender")):
            self.track(w, f)

    def load(self, r: ReviewData) -> None:
        self.supplier.setCurrentIndex(max(0, self.supplier.findData(r.supplier_id)))
        self.new_name.setText(r.new_supplier_name)
        self.new_name.setVisible(self.supplier.currentData() is None)
        self.number.setText(r.invoice_number)
        set_date(self.date, r.document_date)
        set_date(self.due, r.due_date or r.document_date)
        self.vat_rate.setCurrentIndex(max(0, self.vat_rate.findData(r.vat_rate)))
        self.net.set_cents(r.net_cents)
        self.vat.set_cents(r.vat_cents)
        self.gross.set_cents(r.gross_cents)
        for w, f in ((self.number, "invoice_number"), (self.date, "document_date"), (self.due, "due_date"),
                     (self.net, "net_cents"), (self.vat, "vat_cents"), (self.gross, "gross_cents"),
                     (self.supplier, "sender"), (self.new_name, "sender")):
            mark(w, self.low(r, f))

    def apply(self, r: ReviewData) -> None:
        r.supplier_id = self.supplier.currentData()
        r.new_supplier_name = self.new_name.text().strip()
        r.invoice_number = self.number.text().strip()
        r.document_date, r.due_date = get_date(self.date), get_date(self.due)
        r.vat_rate = self.vat_rate.currentData()
        r.net_cents, r.vat_cents, r.gross_cents = self.net.cents(), self.vat.cents(), self.gross.cents()


class CreditForm(BaseForm):
    def __init__(self, svc, threshold, on_focus) -> None:
        super().__init__(svc, threshold, on_focus)
        self.supplier, _ = self.supplier_combo(allow_new=False)
        self.invoice = QComboBox()
        self.number = QLineEdit()
        self.date = make_date_edit()
        self.amount = MoneyEdit()
        self.form.addRow(tr("invoice.supplier"), self.supplier)
        self.form.addRow(tr("review.credit_for"), self.invoice)
        self.form.addRow(tr("review.credit_number"), self.number)
        self.form.addRow(tr("common.date"), self.date)
        self.form.addRow(tr("common.amount"), self.amount)
        self.supplier.currentIndexChanged.connect(lambda _i: self._fill_invoices(None))
        for w, f in ((self.number, "invoice_number"), (self.date, "document_date"), (self.amount, "gross_cents")):
            self.track(w, f)

    def _fill_invoices(self, select: int | None) -> None:
        self.invoice.clear()
        sid = self.supplier.currentData()
        for inv in self.svc.invoices.list(supplier_id=sid) if sid else []:
            if inv.status != InvoiceStatus.CANCELLED:
                self.invoice.addItem(f"{inv.invoice_number} ({format_cents(inv.gross_cents)})", inv.id)
        self.invoice.setCurrentIndex(max(0, self.invoice.findData(select)))

    def load(self, r: ReviewData) -> None:
        self.supplier.setCurrentIndex(max(0, self.supplier.findData(r.supplier_id)))
        self._fill_invoices(r.invoice_id)
        self.number.setText(r.invoice_number)
        set_date(self.date, r.document_date)
        self.amount.set_cents(r.gross_cents)
        mark(self.amount, self.low(r, "gross_cents"))
        mark(self.date, self.low(r, "document_date"))

    def apply(self, r: ReviewData) -> None:
        r.supplier_id = self.supplier.currentData()
        r.invoice_id = self.invoice.currentData()
        r.invoice_number = self.number.text().strip()
        r.document_date = get_date(self.date)
        r.gross_cents = self.amount.cents()


class NoticeForm(BaseForm):
    COLS = ("principal", "fees", "interest", "flat", "other", "total")

    def __init__(self, svc, threshold, on_focus) -> None:
        super().__init__(svc, threshold, on_focus)
        self.supplier, _ = self.supplier_combo(allow_new=False)
        self.sender = QComboBox()
        self.sender.addItem(tr("review.new_sender"), None)
        for p in svc.suppliers.list():
            self.sender.addItem(f"{p.name} ({tr('role.' + p.role.value)})", p.id)
        self.new_sender = QLineEdit()
        self.new_sender.setPlaceholderText(tr("review.new_sender_name"))
        self.new_role = QComboBox()
        for role in PartyRole:
            self.new_role.addItem(tr(f"role.{role.value}"), role)
        self.date = make_date_edit()
        self.level = QComboBox()
        for lv in DunningLevel:
            self.level.addItem(level_label(int(lv)), lv)
        self.deadline = make_date_edit()
        self.credited, self.total = MoneyEdit(), MoneyEdit()
        self.form.addRow(tr("review.notice_supplier"), self.supplier)
        self.form.addRow(tr("notice.sender"), self.sender)
        row = QHBoxLayout()
        row.addWidget(self.new_sender, 1)
        row.addWidget(self.new_role)
        holder = QWidget()
        holder.setLayout(row)
        row.setContentsMargins(0, 0, 0, 0)
        self.new_holder = holder
        self.form.addRow("", holder)
        self.form.addRow(tr("common.date"), self.date)
        self.form.addRow(tr("notice.level"), self.level)
        self.form.addRow(tr("notice.deadline"), self.deadline)
        self.claims = QTableWidget(0, 7)
        self.claims.setHorizontalHeaderLabels([tr("invoice.number"), tr("notice.principal"), tr("notice.fees"),
                                               tr("notice.interest"), tr("notice.flat"), tr("notice.other"), tr("notice.total")])
        self.claims.verticalHeader().setVisible(False)
        self.claims.setMinimumHeight(120)
        self.claims.setMaximumHeight(180)
        self.claims.horizontalHeader().setStretchLastSection(True)
        self.claims.setColumnWidth(0, 170)
        box = QVBoxLayout()
        box.addWidget(self.claims)
        tools = QHBoxLayout()
        tools.addWidget(button(tr("review.add_claim"), "flat", lambda: self._add_claim(None)))
        tools.addWidget(button(tr("review.remove_claim"), "flat", self._remove_claim))
        tools.addStretch(1)
        box.addLayout(tools)
        wrap = QWidget()
        wrap.setLayout(box)
        box.setContentsMargins(0, 0, 0, 0)
        self.form.addRow(tr("review.claims"), wrap)
        self.form.addRow(tr("notice.credited"), self.credited)
        self.form.addRow(tr("notice.total_claimed"), self.total)
        self.sender.currentIndexChanged.connect(self._sync_sender)
        self.supplier.currentIndexChanged.connect(self._supplier_changed)
        for w, f in ((self.date, "document_date"), (self.deadline, "due_date"), (self.total, "total_claimed_cents"),
                     (self.new_sender, "sender"), (self.sender, "sender")):
            self.track(w, f)

    def _sync_sender(self) -> None:
        self.new_holder.setVisible(self.sender.currentData() is None)

    def _supplier_changed(self) -> None:
        for r in range(self.claims.rowCount()):
            combo = self.claims.cellWidget(r, 0)
            cur = combo.currentData()
            self._fill_invoice_combo(combo, cur)

    def _fill_invoice_combo(self, combo: QComboBox, select: int | None) -> None:
        combo.blockSignals(True)
        combo.clear()
        sid = self.supplier.currentData()
        for inv in self.svc.invoices.list(supplier_id=sid) if sid else []:
            combo.addItem(inv.invoice_number, inv.id)
        combo.setCurrentIndex(max(0, combo.findData(select)))
        combo.blockSignals(False)

    def _add_claim(self, claim: ClaimInput | None) -> None:
        r = self.claims.rowCount()
        self.claims.insertRow(r)
        combo = QComboBox()
        self._fill_invoice_combo(combo, claim.invoice_id if claim else None)
        self.claims.setCellWidget(r, 0, combo)
        values = [claim.principal_cents, claim.fees_cents, claim.interest_cents, claim.flat_fee_cents,
                  claim.other_costs_cents, claim.total_cents] if claim else [None] * 6
        for c, v in enumerate(values, start=1):
            edit = MoneyEdit()
            edit.set_cents(v)
            self.claims.setCellWidget(r, c, edit)

    def _remove_claim(self) -> None:
        r = self.claims.currentRow()
        if r >= 0:
            self.claims.removeRow(r)

    def load(self, r: ReviewData) -> None:
        self.supplier.setCurrentIndex(max(0, self.supplier.findData(r.supplier_id)))
        self.sender.setCurrentIndex(max(0, self.sender.findData(r.sender_party_id)))
        self.new_sender.setText(r.new_sender_name)
        self.new_role.setCurrentIndex(max(0, self.new_role.findData(r.new_sender_role)))
        self._sync_sender()
        set_date(self.date, r.document_date)
        if r.level:
            self.level.setCurrentIndex(max(0, self.level.findData(r.level)))
        set_date(self.deadline, r.due_date or r.document_date)
        self.claims.setRowCount(0)
        for c in r.claims:
            self._add_claim(c)
        self.credited.set_cents(r.credited_cents or None)
        self.total.set_cents(r.total_claimed_cents or None)
        for w, f in ((self.date, "document_date"), (self.deadline, "due_date"), (self.total, "total_claimed_cents"),
                     (self.sender, "sender"), (self.new_sender, "sender")):
            mark(w, self.low(r, f))

    def apply(self, r: ReviewData) -> None:
        r.supplier_id = self.supplier.currentData()
        r.sender_party_id = self.sender.currentData()
        r.new_sender_name = self.new_sender.text().strip()
        r.new_sender_role = PartyRole(self.new_role.currentData())
        r.document_date, r.due_date = get_date(self.date), get_date(self.deadline)
        r.level = DunningLevel(self.level.currentData())
        claims: list[ClaimInput] = []
        for row in range(self.claims.rowCount()):
            vals = [int(self.claims.cellWidget(row, c).cents() or 0) for c in range(1, 7)]
            claims.append(ClaimInput(self.claims.cellWidget(row, 0).currentData(), *vals))
        r.claims = claims
        r.credited_cents = int(self.credited.cents() or 0)
        r.total_claimed_cents = int(self.total.cents() or 0)


class PaymentForm(BaseForm):
    def __init__(self, svc, threshold, on_focus) -> None:
        super().__init__(svc, threshold, on_focus)
        self.supplier, _ = self.supplier_combo(allow_new=False)
        self.date = make_date_edit()
        self.amount = MoneyEdit()
        self.method = QComboBox()
        for m in PaymentMethod:
            self.method.addItem(tr(f"method.{m.value}"), m)
        self.reference, self.iban = QLineEdit(), QLineEdit()
        self.invoices = QListWidget()
        self.invoices.setMaximumHeight(130)
        self.form.addRow(tr("payment.supplier"), self.supplier)
        self.form.addRow(tr("common.date"), self.date)
        self.form.addRow(tr("common.amount"), self.amount)
        self.form.addRow(tr("payment.method"), self.method)
        self.form.addRow(tr("payment.reference"), self.reference)
        self.form.addRow(tr("payment.iban"), self.iban)
        self.form.addRow(tr("payment.invoices"), self.invoices)
        self.supplier.currentIndexChanged.connect(lambda _i: self._fill(set()))
        for w, f in ((self.date, "document_date"), (self.amount, "payment_amount_cents")):
            self.track(w, f)

    def _fill(self, selected: set[int]) -> None:
        self.invoices.clear()
        sid = self.supplier.currentData()
        for s in self.svc.ledger.invoice_states(supplier_id=sid) if sid else []:
            if s.balance.balance_cents > 0 and s.invoice.status != InvoiceStatus.CANCELLED:
                it = QListWidgetItem(f"{s.invoice.invoice_number} · fällig {format_date(s.invoice.due_date)} · "
                                     f"offen {format_cents(s.balance.balance_cents)}")
                it.setData(Qt.ItemDataRole.UserRole, s.invoice.id)
                it.setFlags(it.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                it.setCheckState(Qt.CheckState.Checked if s.invoice.id in selected else Qt.CheckState.Unchecked)
                self.invoices.addItem(it)

    def load(self, r: ReviewData) -> None:
        self.supplier.setCurrentIndex(max(0, self.supplier.findData(r.supplier_id)))
        self._fill(set(r.payment_invoice_ids))
        set_date(self.date, r.document_date)
        self.amount.set_cents(r.payment_amount_cents)
        self.reference.setText(r.bank_reference)
        self.iban.setText(r.iban)
        mark(self.amount, self.low(r, "payment_amount_cents"))
        mark(self.date, self.low(r, "document_date"))

    def apply(self, r: ReviewData) -> None:
        r.supplier_id = self.supplier.currentData()
        r.document_date = get_date(self.date)
        r.payment_amount_cents = self.amount.cents()
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
