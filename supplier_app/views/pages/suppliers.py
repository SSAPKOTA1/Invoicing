"""Suppliers: list with balances, Kontoblatt (running balance, open items, aging), invoices, notices."""

from __future__ import annotations

from datetime import date, timedelta

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QSplitter,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from supplier_app.controllers.app_controller import AppController
from supplier_app.i18n import level_label, tr
from supplier_app.models.enums import InvoiceStatus, LedgerEntryType
from supplier_app.services.ledger import AGING_BUCKETS
from supplier_app.util.dates import format_date
from supplier_app.util.money import format_cents
from supplier_app.views.dialogs.invoice_dialog import InvoiceDialog
from supplier_app.views.dialogs.payment_dialog import PaymentDialog
from supplier_app.views.dialogs.supplier_dialog import SupplierDialog
from supplier_app.views.errors import confirm
from supplier_app.views.pages.base import Page
from supplier_app.views.widgets.common import button, page_title, status_tone
from supplier_app.views.widgets.data_table import Cell, DataTable, Row
from supplier_app.views.widgets.inputs import get_date, make_date_edit


class SuppliersPage(Page):
    key = "suppliers"
    title = "nav.suppliers"

    def __init__(self, ctrl: AppController) -> None:
        super().__init__(ctrl)
        self.supplier_id: int | None = None
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 20)
        head = QHBoxLayout()
        head.addWidget(page_title(tr("nav.suppliers")))
        head.addStretch(1)
        head.addWidget(button(tr("supplier.new"), "primary", self.new_supplier))
        root.addLayout(head)
        split = QSplitter(Qt.Orientation.Horizontal)
        left = QWidget()
        left_lay = QVBoxLayout(left)
        left_lay.setContentsMargins(0, 0, 0, 0)
        self.filter = QLineEdit()
        self.filter.setPlaceholderText(tr("common.filter"))
        self.filter.textChanged.connect(lambda t: self.list.set_filter_text(t))
        left_lay.addWidget(self.filter)
        self.list = DataTable()
        self.list.row_selected.connect(self._selected)
        left_lay.addWidget(self.list, 1)
        split.addWidget(left)
        right = QWidget()
        r_lay = QVBoxLayout(right)
        r_lay.setContentsMargins(0, 0, 0, 0)
        self.header = QLabel(tr("suppliers.select"))
        self.header.setObjectName("SectionTitle")
        r_lay.addWidget(self.header)
        actions = QHBoxLayout()
        self.btn_edit = button(tr("common.edit"), "", self.edit_supplier)
        self.btn_invoice = button(tr("invoice.new"), "", self.new_invoice)
        self.btn_pay = button(tr("action.payment"), "primary", self.new_payment)
        self.btn_delete = button(tr("common.delete"), "danger", self.delete_supplier)
        for b in (self.btn_edit, self.btn_invoice, self.btn_pay, self.btn_delete):
            actions.addWidget(b)
        actions.addStretch(1)
        r_lay.addLayout(actions)
        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_statement_tab(), tr("suppliers.tab.statement"))
        self.invoices = DataTable()
        self.invoices.row_activated.connect(lambda iid: iid and self.ctrl.open_invoice.emit(iid))
        self.tabs.addTab(self.invoices, tr("suppliers.tab.invoices"))
        self.notices = DataTable()
        self.notices.row_activated.connect(lambda iid: iid and self.ctrl.open_invoice.emit(iid))
        self.tabs.addTab(self.notices, tr("suppliers.tab.notices"))
        self.documents = DataTable()
        self.documents.row_activated.connect(lambda did: did and self.ctrl.open_document.emit(did))
        self.tabs.addTab(self.documents, tr("suppliers.tab.documents"))
        self.master = QLabel()
        self.master.setWordWrap(True)
        self.master.setTextFormat(Qt.TextFormat.RichText)
        self.master.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.master.setContentsMargins(14, 14, 14, 14)
        self.tabs.addTab(self.master, tr("suppliers.tab.master"))
        r_lay.addWidget(self.tabs, 1)
        split.addWidget(right)
        split.setSizes([560, 800])
        split.setChildrenCollapsible(False)
        root.addWidget(split, 1)
        self._set_enabled(False)

    def _build_statement_tab(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(8, 8, 8, 8)
        bar = QHBoxLayout()
        self.use_period = QCheckBox(tr("suppliers.period"))
        self.from_edit = make_date_edit(date.today() - timedelta(days=365))
        self.to_edit = make_date_edit(date.today())
        self.only_open = QCheckBox(tr("suppliers.only_open"))
        for c in (self.use_period, self.only_open):
            c.stateChanged.connect(lambda _s: self.refresh())
        for e in (self.from_edit, self.to_edit):
            e.dateChanged.connect(lambda _d: self.refresh() if self.use_period.isChecked() else None)
        bar.addWidget(self.use_period)
        bar.addWidget(self.from_edit)
        bar.addWidget(QLabel("–"))
        bar.addWidget(self.to_edit)
        bar.addSpacing(16)
        bar.addWidget(self.only_open)
        bar.addStretch(1)
        lay.addLayout(bar)
        self.statement = DataTable(sortable=False)
        self.statement.row_activated.connect(lambda iid: iid and self.ctrl.open_invoice.emit(iid))
        lay.addWidget(self.statement, 1)
        self.totals = QLabel()
        self.totals.setTextFormat(Qt.TextFormat.RichText)
        lay.addWidget(self.totals)
        self.aging_label = QLabel()
        self.aging_label.setTextFormat(Qt.TextFormat.RichText)
        lay.addWidget(self.aging_label)
        return w

    def _set_enabled(self, on: bool) -> None:
        for b in (self.btn_edit, self.btn_invoice, self.btn_pay, self.btn_delete):
            b.setEnabled(on)

    # -- data -----------------------------------------------------------------------------------------------
    def refresh(self) -> None:
        svc = self.svc
        states = svc.ledger.invoice_states()
        today = date.today()
        open_by: dict[int, int] = {}
        overdue_by: dict[int, int] = {}
        for s in states:
            if s.balance.balance_cents > 0 and s.invoice.status != InvoiceStatus.CANCELLED:
                sid = s.invoice.supplier_id
                open_by[sid] = open_by.get(sid, 0) + s.balance.balance_cents
                if s.invoice.due_date and s.invoice.due_date < today:
                    overdue_by[sid] = overdue_by.get(sid, 0) + s.balance.balance_cents
        balances = svc.ledger.supplier_balances()
        rows = []
        for p in svc.suppliers.list():
            bal = balances.get(p.id or 0)
            credit = -(bal.total_cents) if bal and bal.total_cents < 0 else 0
            rows.append(Row([p.name, tr(f"role.{p.role.value}"),
                             Cell(format_cents(open_by.get(p.id or 0, 0)), open_by.get(p.id or 0, 0), "right"),
                             Cell(format_cents(overdue_by.get(p.id or 0, 0)), overdue_by.get(p.id or 0, 0), "right",
                                  "bad" if overdue_by.get(p.id or 0) else ""),
                             Cell(format_cents(credit) if credit else "", credit, "right", "ok" if credit else "")], p.id))
        keep = self.supplier_id
        self.list.set_data([tr("supplier.name"), tr("supplier.role"), tr("suppliers.open"), tr("suppliers.overdue"),
                            tr("suppliers.credit")], rows, [230, 110, 110, 110, 90])
        self.list.sortByColumn(0, Qt.SortOrder.AscendingOrder)
        if keep is None or not self.list.select_payload(keep):
            first = self.list.payload_at(0) if self.list.row_count() else None
            self.supplier_id = first
            if first is not None:
                self.list.select_payload(first)
        self._load_detail()

    def select_supplier(self, supplier_id: int) -> None:
        self.filter.clear()
        if self.list.select_payload(supplier_id):
            self.supplier_id = supplier_id
        else:
            self.refresh()
            self.list.select_payload(supplier_id)

    def _selected(self, supplier_id) -> None:
        self.supplier_id = supplier_id
        self._load_detail()

    def _load_detail(self) -> None:
        sid = self.supplier_id
        self._set_enabled(sid is not None)
        if sid is None:
            self.header.setText(tr("suppliers.select"))
            for t in (self.statement, self.invoices, self.notices, self.documents):
                t.set_data([], [])
            self.totals.setText("")
            self.aging_label.setText("")
            self.master.setText("")
            return
        svc = self.svc
        party = svc.suppliers.get(sid)
        bal = svc.ledger.supplier_balance(sid)
        self.header.setText(f"{party.name} · {tr('suppliers.balance')}: {format_cents(bal.total_cents)}")
        self.btn_invoice.setEnabled(party.role.value != "collection_agency")
        self.btn_pay.setEnabled(party.role.value != "collection_agency")
        self._load_statement(sid)
        self._load_invoices(sid)
        self._load_notices(sid)
        self._load_documents(sid)
        self._load_master(sid)

    def _load_statement(self, sid: int) -> None:
        svc = self.svc
        d_from = get_date(self.from_edit) if self.use_period.isChecked() else None
        d_to = get_date(self.to_edit) if self.use_period.isChecked() else None
        st = svc.ledger.supplier_statement(sid, d_from, d_to)
        open_ids = {s.invoice.id for s in svc.ledger.invoice_states(supplier_id=sid)
                    if s.balance.balance_cents > 0 and s.invoice.status != InvoiceStatus.CANCELLED}
        rows: list[Row] = []
        debit = credit = 0
        if d_from:
            rows.append(Row([format_date(d_from), "", Cell(tr("suppliers.carry"), tone="muted"), "", "", "",
                             Cell(format_cents(st.opening_cents), align="right")]))
        for r in st.rows:
            e = r.entry
            if self.only_open.isChecked() and e.invoice_id not in open_ids:
                continue
            d_amt = e.amount_cents if e.amount_cents > 0 else 0
            c_amt = -e.amount_cents if e.amount_cents < 0 else 0
            debit, credit = debit + d_amt, credit + c_amt
            label = tr(f"entry.{e.entry_type.value}")
            if e.entry_type == LedgerEntryType.REVERSAL:
                label += f" ({tr('entry.' + e.category_type.value)})"
            tone = "muted" if r.reversed else ""
            rows.append(Row([format_date(e.entry_date), Cell(r.invoice_number, tone=tone), Cell(label, tone=tone),
                             Cell(e.comment, tone=tone), Cell(format_cents(d_amt) if d_amt else "", d_amt, "right"),
                             Cell(format_cents(c_amt) if c_amt else "", c_amt, "right", "ok" if c_amt else ""),
                             Cell(format_cents(r.running_cents), r.running_cents, "right")], e.invoice_id))
        self.statement.set_data([tr("common.date"), tr("invoice.number"), tr("history.col.kind"), tr("history.col.text"),
                                 tr("report.col.debit"), tr("report.col.credit"), tr("history.col.balance")], rows,
                                [90, 150, 170, 280, 105, 105, 110])
        self.totals.setText(
            f"<b>{tr('suppliers.total_debit')}:</b> {format_cents(debit)} &nbsp; <b>{tr('suppliers.total_paid')}:</b> "
            f"{format_cents(credit)} &nbsp; <b>{tr('suppliers.closing')}:</b> {format_cents(st.closing_cents)}")
        aging = svc.ledger.aging(supplier_id=sid)
        self.aging_label.setText("<span style='color:gray'>" + tr("dash.chart.aging") + ":</span> " + " &nbsp;·&nbsp; ".join(
            f"{tr('aging.' + b)}: <b>{format_cents(aging[b])}</b>" for b in AGING_BUCKETS))

    def _load_invoices(self, sid: int) -> None:
        rows = []
        for s in sorted(self.svc.ledger.invoice_states(supplier_id=sid), key=lambda s: s.invoice.invoice_date, reverse=True):
            b, inv = s.balance, s.invoice
            overdue = b.balance_cents > 0 and inv.due_date is not None and inv.due_date < date.today()
            rows.append(Row([inv.invoice_number, Cell(format_date(inv.invoice_date), inv.invoice_date.toordinal()),
                             Cell(format_date(inv.due_date), inv.due_date.toordinal() if inv.due_date else 0,
                                  tone="bad" if overdue else ""),
                             Cell(format_cents(inv.gross_cents), inv.gross_cents, "right"),
                             Cell(format_cents(b.charges_cents), b.charges_cents, "right"),
                             Cell(format_cents(b.paid_cents + b.credits_cents), b.paid_cents, "right"),
                             Cell(format_cents(b.balance_cents), b.balance_cents, "right", "bad" if overdue else ""),
                             Cell(tr(f"status.{b.status.value}"), tone={"ok": "ok", "warn": "warn", "bad": "bad"}.get(status_tone(b.status.value), ""))],
                            inv.id))
        self.invoices.set_data([tr("invoice.number"), tr("invoice.date"), tr("invoice.due"), tr("invoice.gross"),
                                tr("history.charges"), tr("history.paid"), tr("invoice.open"), tr("invoice.status")], rows,
                               [150, 95, 95, 105, 100, 105, 105, 130])

    def _load_notices(self, sid: int) -> None:
        svc = self.svc
        rows = []
        for n in svc.dunning.list(supplier_id=sid):
            rec = svc.dunning.reconcile(n.id or 0)
            sender = svc.repos.parties.get(n.sender_party_id)
            numbers = ", ".join(svc.invoices.get(c.invoice_id).invoice_number for c in n.claims)
            diff = rec.difference_cents
            rows.append(Row([Cell(format_date(n.notice_date), n.notice_date.toordinal()), sender.name if sender else "",
                             level_label(int(n.level)), numbers, Cell(format_cents(rec.claimed_total_cents), rec.claimed_total_cents, "right"),
                             Cell(format_cents(rec.expected_total_cents), rec.expected_total_cents, "right"),
                             Cell(format_cents(diff, plus=True) if diff else "✓", diff, "right", "bad" if diff else "ok")],
                            n.claims[0].invoice_id if n.claims else None, "warn" if diff else ""))
        self.notices.set_data([tr("common.date"), tr("notice.sender"), tr("notice.level"), tr("invoice.number"),
                               tr("history.claims"), tr("history.expected"), tr("history.difference")], rows,
                              [95, 220, 130, 150, 110, 110, 100])

    def _load_documents(self, sid: int) -> None:
        rows = [Row([d.original_name, tr(f"doctype.{d.doc_type.value}"), f"{int(d.confidence * 100)} %",
                     tr(f"review.{d.review_status.value}")], d.id) for d in self.svc.repos.documents.list(supplier_id=sid)]
        self.documents.set_data([tr("doc.name"), tr("doc.type"), tr("doc.confidence"), tr("doc.status")], rows, [320, 160, 90, 120])

    def _load_master(self, sid: int) -> None:
        p = self.svc.suppliers.get(sid)
        rep = ""
        if p.represents_supplier_id:
            rep_p = self.svc.repos.parties.get(p.represents_supplier_id)
            rep = f"<tr><td>{tr('supplier.represents')}</td><td><b>{rep_p.name if rep_p else ''}</b></td></tr>"
        agencies = [a.name for a in self.svc.suppliers.list() if a.represents_supplier_id == sid]
        rows = [(tr("supplier.role"), tr(f"role.{p.role.value}")), (tr("supplier.aliases"), ", ".join(p.aliases)),
                (tr("supplier.ibans"), ", ".join(p.ibans)), (tr("supplier.vat"), p.vat_id), (tr("supplier.tax"), p.tax_number),
                (tr("supplier.address"), p.address.replace("\n", ", ")), (tr("supplier.email"), p.email),
                (tr("supplier.phone"), p.phone), (tr("supplier.contact"), p.contact), (tr("supplier.terms"), p.payment_terms),
                (tr("supplier.agencies"), ", ".join(agencies)), (tr("supplier.notes"), p.notes)]
        body = "".join(f"<tr><td style='color:gray;padding-right:18px'>{k}</td><td>{v}</td></tr>" for k, v in rows if v)
        self.master.setText(f"<table cellspacing='6'>{body}{rep}</table>")

    # -- actions -----------------------------------------------------------------------------------------------
    def new_supplier(self) -> None:
        dlg = SupplierDialog(self.ctrl, parent=self)
        if dlg.exec() and dlg.saved_id:
            self.select_supplier(dlg.saved_id)

    def edit_supplier(self) -> None:
        if self.supplier_id:
            SupplierDialog(self.ctrl, self.svc.suppliers.get(self.supplier_id), self).exec()

    def delete_supplier(self) -> None:
        if self.supplier_id and confirm(self, tr("supplier.delete.confirm")):
            if self.ctrl.run(self.svc.suppliers.delete, self.supplier_id, parent=self):
                self.supplier_id = None
                self.refresh()

    def new_invoice(self) -> None:
        InvoiceDialog(self.ctrl, self.supplier_id, self).exec()

    def new_payment(self) -> None:
        PaymentDialog(self.ctrl, self.supplier_id, parent=self).exec()


