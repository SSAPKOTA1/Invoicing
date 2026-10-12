"""Bank statements: import, recognised supplier/invoices per transaction, correct, book (now or later)."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QScrollArea,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from supplier_app.ai.result_types import PartyCandidate
from supplier_app.controllers.app_controller import AppController
from supplier_app.errors import AccountRequiredError, DuplicateError, SupplierAppError
from supplier_app.i18n import tr, tx
from supplier_app.models.entities import BankTransaction
from supplier_app.models.enums import BankTxStatus, InvoiceStatus
from supplier_app.services.bank_service import SURE_CONFIDENCE
from supplier_app.util.dates import format_date
from supplier_app.util.money import format_cents
from supplier_app.views.dialogs.bank_dialogs import AccountChooserDialog, BankAccountsDialog
from supplier_app.views.errors import confirm, info, show_error
from supplier_app.views.pages.base import Page
from supplier_app.views.widgets.common import button, page_title, wrapped_label
from supplier_app.views.widgets.data_table import Cell, DataTable, Row
from supplier_app.views.widgets.drop_zone import DropZone
from supplier_app.views.widgets.party_picker import PartyPicker

FILTERS = ["open", "matched", "new", "booked", "ignored", "all"]
STATUS_TONE = {BankTxStatus.NEW: "warn", BankTxStatus.MATCHED: "ok", BankTxStatus.BOOKED: "muted", BankTxStatus.IGNORED: "muted"}
FILE_PATTERN = "*.csv *.xml *.sta *.mt940 *.940 *.swi *.camt *.txt *.pdf"


class BankPage(Page):
    key = "bank"
    title = "nav.bank"

    def __init__(self, ctrl: AppController) -> None:
        super().__init__(ctrl)
        self.tx_id: int | None = None
        self._loading = False
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 20)
        head = QHBoxLayout()
        head.addWidget(page_title(tr("nav.bank")))
        head.addStretch(1)
        head.addWidget(button(tr("bank.accounts.open"), "", self.manage_accounts))
        self.btn_sure = button(tr("bank.book_sure"), "", self.book_sure, tr("bank.book_sure.tip"))
        head.addWidget(self.btn_sure)
        head.addWidget(button(tr("bank.import.button"), "primary", self.choose_files))
        root.addLayout(head)
        self.summary = QLabel()
        self.summary.setObjectName("Muted")
        root.addWidget(self.summary)

        split = QSplitter(Qt.Orientation.Horizontal)
        left = QWidget()
        l_lay = QVBoxLayout(left)
        l_lay.setContentsMargins(0, 0, 0, 0)
        self.drop = DropZone()
        self.drop.label.setText(tr("bank.drop"))
        self.drop.files_dropped.connect(self.import_files)
        l_lay.addWidget(self.drop)
        bar = QHBoxLayout()
        self.status = QComboBox()
        for f in FILTERS:
            self.status.addItem(tr(f"bank.filter.{f}"), f)
        self.status.currentIndexChanged.connect(lambda _i: self.refresh())
        self.account = QComboBox()
        self.account.currentIndexChanged.connect(lambda _i: self.refresh())
        self.filter = QLineEdit()
        self.filter.setPlaceholderText(tr("common.filter"))
        self.filter.textChanged.connect(lambda t: self.table.set_filter_text(t))
        bar.addWidget(self.status)
        bar.addWidget(self.account)
        bar.addWidget(self.filter, 1)
        l_lay.addLayout(bar)
        self.table = DataTable()
        self.table.row_selected.connect(self._selected)
        l_lay.addWidget(self.table, 1)
        left.setMinimumWidth(480)
        split.addWidget(left)
        split.addWidget(self._build_detail())
        split.setSizes([900, 520])
        split.setChildrenCollapsible(False)
        root.addWidget(split, 1)
        self._fill_accounts()
        self._show(None)

    # -- detail ---------------------------------------------------------------------------------------------
    def _build_detail(self) -> QWidget:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        inner = QWidget()
        scroll.setWidget(inner)
        lay = QVBoxLayout(inner)
        lay.setContentsMargins(8, 0, 8, 0)
        lay.setSpacing(8)
        self.title = QLabel(tr("bank.detail"))
        self.title.setObjectName("SectionTitle")
        lay.addWidget(self.title)
        self.facts = wrapped_label("", "", 6)
        self.facts.setTextFormat(Qt.TextFormat.RichText)
        lay.addWidget(self.facts)
        self.note_label = wrapped_label("", "Warning", 3)
        lay.addWidget(self.note_label)
        lay.addWidget(QLabel(tr("bank.supplier")))
        self.picker = PartyPicker(self.svc.suppliers.suppliers(), allow_new=False, new_label=tr("bank.no_supplier"))
        self.picker.changed.connect(self._supplier_changed)
        lay.addWidget(self.picker)
        lay.addWidget(QLabel(tr("bank.invoices")))
        self.invoices = QTableWidget(0, 5)
        self.invoices.setHorizontalHeaderLabels(["", tr("invoice.number"), tr("invoice.date"), tr("invoice.due"), tr("invoice.open")])
        self.invoices.verticalHeader().setVisible(False)
        self.invoices.verticalHeader().setDefaultSectionSize(34)
        self.invoices.setColumnWidth(0, 34)
        self.invoices.setColumnWidth(1, 110)
        self.invoices.setColumnWidth(2, 112)
        self.invoices.setColumnWidth(3, 104)
        self.invoices.horizontalHeader().setStretchLastSection(True)
        self.invoices.setMinimumHeight(170)
        self.invoices.setMaximumHeight(280)
        self.invoices.itemChanged.connect(lambda _i: self._update_sum())
        lay.addWidget(self.invoices)
        self.sum_label = wrapped_label("", "Muted", 2)
        lay.addWidget(self.sum_label)
        self.note = QLineEdit()
        self.note.setPlaceholderText(tr("bank.note"))
        lay.addWidget(self.note)
        self.learn = QCheckBox(tr("bank.learn"))
        self.learn.setChecked(True)
        lay.addWidget(self.learn)
        self.error = QLabel()
        self.error.setObjectName("Danger")
        self.error.setWordWrap(True)
        self.error.setVisible(False)
        lay.addWidget(self.error)
        bar = QHBoxLayout()
        self.btn_book = button(tr("bank.book"), "primary", self.book)
        self.btn_later = button(tr("bank.later"), "", self.save_later, tr("bank.later.tip"))
        self.btn_ignore = button(tr("bank.ignore"), "", self.ignore)
        self.btn_reopen = button(tr("bank.reopen"), "", self.reopen)
        self.btn_payment = button(tr("bank.open_payment"), "", self.open_payment)
        for b in (self.btn_book, self.btn_later, self.btn_ignore, self.btn_reopen, self.btn_payment):
            bar.addWidget(b)
        bar.addStretch(1)
        lay.addLayout(bar)
        lay.addStretch(1)
        return scroll

    # -- list -----------------------------------------------------------------------------------------------
    def _fill_accounts(self) -> None:
        keep = self.account.currentData() if self.account.count() else None
        self.account.blockSignals(True)
        self.account.clear()
        self.account.addItem(tr("bank.all_accounts"), None)
        for a in self.svc.bank.accounts():
            self.account.addItem(a.name, a.id)
        self.account.setCurrentIndex(max(0, self.account.findData(keep)))
        self.account.blockSignals(False)

    def refresh(self) -> None:
        svc = self.svc
        self._fill_accounts()
        self.picker.parties = svc.suppliers.suppliers()
        mode = self.status.currentData()
        txs = svc.bank.transactions(account_id=self.account.currentData())
        counts = svc.bank.counts()
        open_n = counts.get("new", 0) + counts.get("matched", 0)
        self.summary.setText(tr("bank.summary", open=open_n, matched=counts.get("matched", 0), booked=counts.get("booked", 0),
                                ignored=counts.get("ignored", 0)))
        self.btn_sure.setEnabled(counts.get("matched", 0) > 0 and svc.session.can_write)
        wanted = {"open": {BankTxStatus.NEW, BankTxStatus.MATCHED}, "matched": {BankTxStatus.MATCHED}, "new": {BankTxStatus.NEW},
                  "booked": {BankTxStatus.BOOKED}, "ignored": {BankTxStatus.IGNORED}}.get(mode)
        names = {p.id: p.name for p in svc.suppliers.list()}
        accounts = {a.id: a.name for a in svc.bank.accounts()}
        rows = []
        for t in txs:
            if wanted is not None and t.status not in wanted:
                continue
            rows.append(Row([Cell(format_date(t.booking_date), t.booking_date.toordinal()), t.counterparty_name,
                             t.purpose, Cell(format_cents(t.amount_cents), t.amount_cents, "right", "bad" if t.amount_cents < 0 else "ok"),
                             accounts.get(t.account_id, ""), names.get(t.supplier_id, "") if t.supplier_id else "",
                             Cell(f"{int(t.confidence * 100)} %" if t.confidence else "", t.confidence, "right"),
                             Cell(tr(f"bank.status.{t.status.value}"), tone=STATUS_TONE[t.status])], t.id))
        keep = self.tx_id
        self.table.set_data([tr("common.date"), tr("bank.col.counterparty"), tr("bank.col.purpose"), tr("bank.col.amount"),
                             tr("bank.col.account"), tr("bank.col.supplier"), tr("bank.col.confidence"), tr("doc.status")],
                            rows, [86, 150, 150, 100, 92, 140, 70, 104])
        if keep is not None and self.table.select_payload(keep):
            self._show(keep)
        else:
            self._show(None)

    def _selected(self, tx_id) -> None:
        self._show(int(tx_id) if tx_id else None)

    # -- one transaction --------------------------------------------------------------------------------------
    def _show(self, tx_id: int | None) -> None:
        self.tx_id = tx_id
        self.error.setVisible(False)
        enabled = tx_id is not None
        for w in (self.picker, self.invoices, self.note, self.learn, self.btn_book, self.btn_later, self.btn_ignore,
                  self.btn_reopen, self.btn_payment):
            w.setEnabled(enabled)
        if tx_id is None:
            self.title.setText(tr("bank.detail"))
            self.facts.setText(tr("bank.select"))
            self.note_label.setVisible(False)
            self.sum_label.setText("")
            self.invoices.setRowCount(0)
            self.picker.set_candidates([], None)
            self.note.clear()
            for b in (self.btn_book, self.btn_later, self.btn_ignore, self.btn_reopen, self.btn_payment):
                b.setEnabled(False)
            return
        svc = self.svc
        t = svc.bank.get(tx_id)
        self._loading = True
        try:
            account = svc.repos.bank.get_account(t.account_id) if t.account_id else None
            self.title.setText(f"{format_date(t.booking_date)} · {format_cents(t.amount_cents)}")
            rows = [(tr("bank.col.counterparty"), t.counterparty_name or "–"), (tr("bank.col.iban"), t.counterparty_iban or "–"),
                    (tr("bank.col.purpose"), t.purpose or "–"), (tr("bank.col.account"), account.name if account else "–")]
            self.facts.setText("<table cellspacing='4'>" + "".join(
                f"<tr><td style='color:gray;padding-right:14px;vertical-align:top'>{k}</td><td>{self._esc(v)}</td></tr>" for k, v in rows) + "</table>")
            self.note_label.setText(tx(t.note) if t.note else "")
            self.note_label.setVisible(bool(t.note))
            self.note.setText(t.note if t.status != BankTxStatus.BOOKED else "")
            candidates = [PartyCandidate(e.supplier_id, svc.suppliers.get(e.supplier_id).name, e.score, e.texts)
                          for e in svc.bank.candidates(tx_id)][:4] if t.status != BankTxStatus.BOOKED else []
            self.picker.set_candidates(candidates, t.supplier_id, suggested=t.status == BankTxStatus.NEW)
            self._fill_invoices(t.supplier_id, set(t.invoice_ids), t)
            booked = t.status == BankTxStatus.BOOKED
            incoming = t.amount_cents > 0
            can = svc.session.can_write
            self.picker.setEnabled(not booked and not incoming)
            self.invoices.setEnabled(not booked and not incoming)
            self.btn_book.setEnabled(can and not booked and not incoming)
            self.btn_later.setEnabled(can and not booked and not incoming)
            self.btn_ignore.setEnabled(can and not booked and t.status != BankTxStatus.IGNORED)
            self.btn_reopen.setEnabled(can and t.status == BankTxStatus.IGNORED)
            self.btn_payment.setEnabled(booked)
            self.btn_payment.setVisible(booked)
        finally:
            self._loading = False
        self._update_sum()

    @staticmethod
    def _esc(text: str) -> str:
        return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    def _fill_invoices(self, supplier_id: int | None, checked: set[int], tx: BankTransaction) -> None:
        self.invoices.blockSignals(True)
        self.invoices.setRowCount(0)
        if supplier_id:
            booked = tx.status == BankTxStatus.BOOKED
            for s in sorted(self.svc.ledger.invoice_states(supplier_id=supplier_id),
                            key=lambda s: (s.invoice.due_date or s.invoice.invoice_date, s.invoice.id or 0)):
                inv = s.invoice
                if inv.status == InvoiceStatus.CANCELLED or (s.balance.balance_cents <= 0 and inv.id not in checked):
                    continue
                r = self.invoices.rowCount()
                self.invoices.insertRow(r)
                box = QTableWidgetItem()
                box.setFlags(Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled if not booked else Qt.ItemFlag.ItemIsEnabled)
                box.setCheckState(Qt.CheckState.Checked if inv.id in checked else Qt.CheckState.Unchecked)
                box.setData(Qt.ItemDataRole.UserRole, inv.id)
                box.setData(Qt.ItemDataRole.UserRole + 1, s.balance.balance_cents)
                self.invoices.setItem(r, 0, box)
                amount = QTableWidgetItem(format_cents(s.balance.balance_cents))
                amount.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                for col, text in ((1, inv.invoice_number), (2, format_date(inv.invoice_date)), (3, format_date(inv.due_date))):
                    cell = QTableWidgetItem(text)
                    cell.setFlags(Qt.ItemFlag.ItemIsEnabled)
                    self.invoices.setItem(r, col, cell)
                amount.setFlags(Qt.ItemFlag.ItemIsEnabled)
                self.invoices.setItem(r, 4, amount)
        self.invoices.blockSignals(False)

    def _selected_invoices(self) -> tuple[list[int], int]:
        ids, total = [], 0
        for r in range(self.invoices.rowCount()):
            item = self.invoices.item(r, 0)
            if item.checkState() == Qt.CheckState.Checked:
                ids.append(int(item.data(Qt.ItemDataRole.UserRole)))
                total += int(item.data(Qt.ItemDataRole.UserRole + 1))
        return ids, total

    def _update_sum(self) -> None:
        if self.tx_id is None:
            return
        tx = self.svc.bank.get(self.tx_id)
        ids, total = self._selected_invoices()
        amount = abs(tx.amount_cents)
        if tx.status == BankTxStatus.BOOKED or tx.amount_cents > 0:
            self.sum_label.setText("")
            return
        if not ids:
            text, name = tr("bank.sum.none", amount=format_cents(amount)), "Warning"
        elif total == amount:
            text, name = tr("bank.sum.exact", amount=format_cents(amount)), "Muted"
        else:
            text, name = tr("bank.sum.differs", selected=format_cents(total), amount=format_cents(amount),
                            diff=format_cents(amount - total, plus=True)), "Warning"
        self.sum_label.setText(text)
        self.sum_label.setObjectName(name)
        from supplier_app.views.theme import repolish
        repolish(self.sum_label)

    def _supplier_changed(self) -> None:
        if self._loading or self.tx_id is None:
            return
        sid = self.picker.party_id()
        tx = self.svc.bank.get(self.tx_id)
        proposed = set(self.svc.bank.propose(self.tx_id, sid)) if sid else set()
        self._fill_invoices(sid, proposed, tx)
        self._update_sum()

    # -- actions --------------------------------------------------------------------------------------------
    def _fail(self, exc: Exception) -> None:
        if isinstance(exc, SupplierAppError):
            self.error.setText(exc.message)
            self.error.setVisible(True)
        else:
            show_error(self, exc)

    def _save_assignment(self) -> bool:
        if self.tx_id is None:
            return False
        ids, _total = self._selected_invoices()
        try:
            self.svc.bank.assign(self.tx_id, self.picker.party_id(), ids, self.note.text().strip())
        except Exception as exc:  # noqa: BLE001
            self._fail(exc)
            return False
        return True

    def save_later(self) -> None:
        if self._save_assignment():
            self.ctrl.notify_changed()
            self.ctrl.status.emit(tr("bank.saved"))

    def book(self) -> None:
        if self.tx_id is None:
            return
        self.error.setVisible(False)
        if self.picker.party_id() is None:
            self.error.setText(tr("bank.need_supplier"))
            self.error.setVisible(True)
            return
        ids, total = self._selected_invoices()
        amount = abs(self.svc.bank.get(self.tx_id).amount_cents)
        if ids and total != amount and not confirm(self, tr("bank.confirm.differs.title"),
                                                   tr("bank.confirm.differs", selected=format_cents(total), amount=format_cents(amount))):
            return
        if not ids and not confirm(self, tr("bank.confirm.credit.title"), tr("bank.confirm.credit", amount=format_cents(amount))):
            return
        if not self._save_assignment():
            return
        try:
            try:
                self.svc.bank.book(self.tx_id, learn=self.learn.isChecked())
            except DuplicateError as exc:
                if not confirm(self, tr("bank.confirm.duplicate.title"), exc.message):
                    return
                self.svc.bank.book(self.tx_id, learn=self.learn.isChecked(), force=True)
        except Exception as exc:  # noqa: BLE001
            self._fail(exc)
            return
        self.ctrl.notify_changed()
        self.ctrl.status.emit(tr("bank.booked"))
        self._next_open()

    def _next_open(self) -> None:
        """After a decision, continue with the next row of the list."""
        row = self.table.currentIndex().row()
        self.refresh()
        if self.table.row_count():
            self.table.selectRow(min(max(row, 0), self.table.row_count() - 1))

    def ignore(self) -> None:
        if self.tx_id is not None:
            self.ctrl.run(self.svc.bank.ignore, self.tx_id, self.note.text().strip(), parent=self)
            self._next_open()

    def reopen(self) -> None:
        if self.tx_id is not None:
            self.ctrl.run(self.svc.bank.reopen, self.tx_id, parent=self)

    def open_payment(self) -> None:
        if self.tx_id is None:
            return
        tx = self.svc.bank.get(self.tx_id)
        if tx.payment_id:
            ids = [a.invoice_id for a in self.svc.repos.payments.allocations(payment_id=tx.payment_id)]
            if ids:
                self.ctrl.open_invoice.emit(ids[0])
            elif tx.supplier_id:
                self.ctrl.open_supplier.emit(tx.supplier_id)

    def book_sure(self) -> None:
        n = sum(1 for t in self.svc.bank.transactions(BankTxStatus.MATCHED) if t.confidence >= SURE_CONFIDENCE)
        if not n:
            info(self, tr("bank.book_sure.none"))
            return
        if not confirm(self, tr("bank.book_sure.confirm", n=n)):
            return
        report = self.ctrl.run(self.svc.bank.book_sure, parent=self)
        if report is None or report is True:
            return
        msg = tr("bank.book_sure.done", n=len(report.booked))
        if report.failed:
            msg += "\n\n" + "\n".join(f"• {tx(m)}" for _i, m in report.failed[:8])
        info(self, msg)

    # -- import -----------------------------------------------------------------------------------------------
    def manage_accounts(self) -> None:
        BankAccountsDialog(self.ctrl, self).exec()
        self.refresh()

    def choose_files(self) -> None:
        files, _ = QFileDialog.getOpenFileNames(self, tr("bank.import.button"), "", f"{tr('bank.file_filter')} ({FILE_PATTERN});;*")
        if files:
            self.import_files([Path(f) for f in files])

    def import_files(self, paths: list[Path]) -> None:
        created = duplicates = matched = 0
        problems: list[str] = []
        new_accounts: list[str] = []
        for path in paths:
            account_id = None
            while True:
                try:
                    res = self.svc.bank.import_file(path, account_id)
                except AccountRequiredError:
                    dlg = AccountChooserDialog(self.ctrl, path.name, self)
                    if not dlg.exec() or dlg.account_id is None:
                        problems.append(f"{path.name}: {tr('bank.import.cancelled')}")
                        break
                    account_id = dlg.account_id
                    continue
                except SupplierAppError as exc:
                    problems.append(f"{path.name}: {exc.message}")
                    break
                except Exception as exc:  # noqa: BLE001
                    show_error(self, exc)
                    break
                created, duplicates, matched = created + res.created, duplicates + res.duplicates, matched + res.matched
                problems += [f"{path.name}: {tx(w)}" for w in res.warnings]
                if res.account_created:
                    new_accounts.append(f"{res.account.name} ({res.account.iban})")
                break
        self.ctrl.notify_changed()
        lines = [tr("bank.import.done", created=created, matched=matched, duplicates=duplicates)]
        if new_accounts:
            lines.append(tr("bank.import.new_account", accounts=", ".join(new_accounts)))
        lines += [f"⚠ {p}" for p in problems]
        info(self, "\n\n".join(lines[:1]), "\n".join(lines[1:]))
