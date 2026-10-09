"""Invoice / case history: header with balances and references, chronological timeline with running balance,
notice rows with claimed vs. expected amounts, discrepancy warnings and a scan preview."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMenu,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from supplier_app.controllers.app_controller import AppController
from supplier_app.i18n import tr
from supplier_app.models.enums import CaseStatus, InvoiceStatus, LedgerEntryType
from supplier_app.services.history_service import HistoryItem, InvoiceHistory
from supplier_app.util.dates import format_date
from supplier_app.util.money import format_cents
from supplier_app.views.dialogs.amount_dialog import AmountDialog
from supplier_app.views.dialogs.notice_dialog import NoticeDialog
from supplier_app.views.dialogs.payment_dialog import PaymentDialog
from supplier_app.views.errors import confirm
from supplier_app.views.widgets.common import Badge, Card, button, status_tone
from supplier_app.views.widgets.data_table import Cell, DataTable, Row
from supplier_app.views.widgets.document_preview import DocumentPreview


class StatBox(QFrame):
    def __init__(self, title: str) -> None:
        super().__init__()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 2, 8, 2)
        lay.setSpacing(0)
        self.title = QLabel(title)
        self.title.setObjectName("KpiTitle")
        self.value = QLabel("–")
        self.value.setObjectName("KpiValue")
        self.value.setStyleSheet("font-size: 14pt;")
        lay.addWidget(self.title)
        lay.addWidget(self.value)

    def set_value(self, text: str) -> None:
        self.value.setText(text)


class InvoiceHistoryWidget(QWidget):
    def __init__(self, ctrl: AppController, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.ctrl = ctrl
        self.invoice_id: int | None = None
        self.history: InvoiceHistory | None = None
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(10)

        self.header = Card()
        top = QHBoxLayout()
        title_col = QVBoxLayout()
        self.title = QLabel(tr("history.none"))
        self.title.setObjectName("PageTitle")
        self.subtitle = QLabel()
        self.subtitle.setObjectName("Muted")
        self.subtitle.setWordWrap(True)
        title_col.addWidget(self.title)
        title_col.addWidget(self.subtitle)
        top.addLayout(title_col, 1)
        self.status_badge = Badge()
        top.addWidget(self.status_badge, 0, Qt.AlignmentFlag.AlignTop)
        self.header.layout_.addLayout(top)
        stats = QHBoxLayout()
        self.stat_gross = StatBox(tr("history.gross"))
        self.stat_charges = StatBox(tr("history.charges"))
        self.stat_paid = StatBox(tr("history.paid"))
        self.stat_open = StatBox(tr("history.open"))
        self.stat_deadline = StatBox(tr("history.deadline"))
        for s in (self.stat_gross, self.stat_charges, self.stat_paid, self.stat_open, self.stat_deadline):
            stats.addWidget(s)
        self.header.layout_.addLayout(stats)
        self.refs_label = QLabel()
        self.refs_label.setWordWrap(True)
        self.refs_label.setTextFormat(Qt.TextFormat.RichText)
        self.header.add(self.refs_label)
        case_row = QHBoxLayout()
        self.case_label = QLabel(tr("history.case"))
        self.case_label.setObjectName("Muted")
        self.case_status = QComboBox()
        for st in CaseStatus:
            self.case_status.addItem(tr(f"case.{st.value}"), st)
        self.case_status.activated.connect(self._case_status_changed)
        self.open_case_btn = button(tr("history.open_case"), "", self._open_case)
        self.note_btn = button(tr("history.add_note"), "", self._add_note)
        case_row.addWidget(self.case_label)
        case_row.addWidget(self.case_status)
        case_row.addWidget(self.open_case_btn)
        case_row.addWidget(self.note_btn)
        case_row.addStretch(1)
        self.header.layout_.addLayout(case_row)
        actions = QHBoxLayout()
        self.actions: dict[str, object] = {}
        for key, text, slot, kind in (
            ("pay", tr("action.payment"), self._pay, "primary"), ("notice", tr("history.add_notice"), self._notice, ""),
            ("credit", tr("history.credit_note"), self._credit, ""), ("adjust", tr("history.adjust"), self._adjust, ""),
            ("writeoff", tr("history.write_off"), self._write_off, ""), ("dispute", tr("history.dispute"), self._dispute, ""),
            ("cancel", tr("history.cancel"), self._cancel, "danger"),
        ):
            b = button(text, kind, slot)
            self.actions[key] = b
            actions.addWidget(b)
        actions.addStretch(1)
        self.header.layout_.addLayout(actions)
        root.addWidget(self.header)

        self.warning_box = QVBoxLayout()
        root.addLayout(self.warning_box)

        split = QSplitter(Qt.Orientation.Vertical)
        self.table = DataTable()
        self.table.row_selected.connect(self._row_selected)
        self.table.row_activated.connect(self._row_activated)
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._context_menu)
        split.addWidget(self.table)
        side = QWidget()
        side_lay = QHBoxLayout(side)
        side_lay.setContentsMargins(0, 0, 0, 0)
        info_col = QVBoxLayout()
        self.detail_label = QLabel()
        self.detail_label.setWordWrap(True)
        self.detail_label.setTextFormat(Qt.TextFormat.RichText)
        self.detail_label.setAlignment(Qt.AlignmentFlag.AlignTop)
        info_col.addWidget(self.detail_label)
        self.compare_table = DataTable(sortable=False)
        self.compare_table.setMaximumHeight(150)
        info_col.addWidget(self.compare_table)
        info_col.addStretch(1)
        side_lay.addLayout(info_col, 3)
        self.preview = DocumentPreview()
        side_lay.addWidget(self.preview, 2)
        split.addWidget(side)
        split.setSizes([420, 260])
        root.addWidget(split, 1)

    # -- loading -----------------------------------------------------------------------------------------
    def set_invoice(self, invoice_id: int | None) -> None:
        self.invoice_id = invoice_id
        self.refresh()

    def refresh(self) -> None:
        for i in reversed(range(self.warning_box.count())):
            w = self.warning_box.takeAt(i).widget()
            if w:
                w.deleteLater()
        if self.invoice_id is None:
            self.history = None
            self.title.setText(tr("history.none"))
            self.table.set_data([], [])
            return
        h = self.ctrl.ctx.services.history.invoice_history(self.invoice_id)
        self.history = h
        inv, bal = h.invoice, h.balance
        self.title.setText(f"{h.supplier_name} – {inv.invoice_number}")
        self.subtitle.setText(f"{tr('history.invoice_date')} {format_date(inv.invoice_date)} · "
                              f"{tr('history.due')} {format_date(inv.due_date)}")
        self.status_badge.set_badge(tr(f"status.{bal.status.value}"), status_tone(bal.status.value))
        self.stat_gross.set_value(format_cents(inv.gross_cents))
        self.stat_charges.set_value(format_cents(bal.charges_cents))
        self.stat_paid.set_value(format_cents(bal.paid_cents + bal.credits_cents))
        open_text = format_cents(bal.balance_cents)
        if bal.balance_cents < 0:
            open_text += f" ({tr('history.credit')})"
        self.stat_open.set_value(open_text)
        self.stat_deadline.set_value(format_date(h.next_deadline) if h.next_deadline else "–")
        refs = " &nbsp;·&nbsp; ".join(f"<b>{label}:</b> {value}" for label, value in h.references)
        self.refs_label.setText(f"<span style='color:gray'>{tr('history.refs')}:</span> {refs}" if refs else "")
        self._load_case(h)
        for msg in h.warnings:
            lab = QLabel("⚠ " + msg)
            lab.setObjectName("Warning")
            lab.setWordWrap(True)
            self.warning_box.addWidget(lab)
        self._fill_table(h)
        cancelled = bal.status == InvoiceStatus.CANCELLED
        for key in ("pay", "notice", "credit", "adjust", "writeoff", "dispute"):
            self.actions[key].setEnabled(not cancelled)  # type: ignore[attr-defined]
        self.actions["cancel"].setEnabled(not cancelled)  # type: ignore[attr-defined]
        self.actions["dispute"].setText(  # type: ignore[attr-defined]
            tr("history.undispute") if inv.status == InvoiceStatus.DISPUTED else tr("history.dispute"))
        self.detail_label.setText("")
        self.compare_table.set_data([], [])
        self.preview.clear()

    def _load_case(self, h: InvoiceHistory) -> None:
        has_case = h.case is not None
        self.case_status.setVisible(has_case)
        self.note_btn.setVisible(has_case)
        self.open_case_btn.setVisible(not has_case)
        self.case_label.setText(tr("history.case") if has_case else tr("history.no_case"))
        if h.case:
            self.case_status.setCurrentIndex(self.case_status.findData(h.case.status))

    def _fill_table(self, h: InvoiceHistory) -> None:
        rows: list[Row] = []
        for it in h.items:
            if it.kind == "notice":
                desc = f"{tr('history.claims')} {format_cents(it.claimed_cents or 0)} · {tr('history.expected')} " \
                       f"{format_cents(it.expected_cents or 0)}"
                diff = (it.claimed_cents or 0) - (it.expected_cents or 0)
                rows.append(Row([format_date(it.item_date), Cell(it.title, tone="warn" if it.warnings else ""), desc,
                                 Cell("", align="right"), Cell("", align="right"),
                                 Cell(f"⚠ {format_cents(diff, plus=True)}" if it.warnings else "✓", tone="bad" if it.warnings else "ok")],
                                it, "warn" if it.warnings else ""))
            else:
                tone = "muted" if it.reversed else ""
                label = it.title + (f" ({tr('history.reversed')})" if it.reversed else "")
                rows.append(Row([format_date(it.item_date), Cell(label, tone=tone), Cell(it.comment, tone=tone),
                                 Cell(format_cents(it.amount_cents, plus=True), it.amount_cents, "right",
                                      "bad" if it.amount_cents > 0 and it.entry_type != LedgerEntryType.INVOICE
                                      else "ok" if it.amount_cents < 0 else ""),
                                 Cell(format_cents(it.running_cents or 0), it.running_cents, "right"),
                                 Cell("📎" if it.document_id else "", align="center")], it))
        self.table.set_data([tr("common.date"), tr("history.col.kind"), tr("history.col.text"), tr("common.amount"),
                             tr("history.col.balance"), tr("history.col.note")], rows, [95, 220, 380, 120, 120, 70])
        self.table.setSortingEnabled(False)

    # -- selection ------------------------------------------------------------------------------------------------------
    def _row_selected(self, item: HistoryItem | None) -> None:
        if item is None:
            return
        svc = self.ctrl.ctx.services
        self.compare_table.set_data([], [])
        if item.kind == "notice" and item.notice_id:
            rows = svc.dunning.compare_with_calculation(item.notice_id)
            self.compare_table.set_data(
                [tr("history.item"), tr("history.claimed_by_sender"), tr("history.calculated"), tr("history.difference")],
                [Row([r.label, Cell(format_cents(r.claimed_cents), align="right"), Cell(format_cents(r.calculated_cents), align="right"),
                      Cell(format_cents(r.difference_cents, plus=True), align="right", tone="bad" if r.difference_cents else "ok")])
                 for r in rows])
            notice = svc.dunning.get(item.notice_id)
            lines = [f"<b>{item.title}</b> · {format_date(item.item_date)}"]
            if notice.new_deadline:
                lines.append(f"{tr('history.deadline')}: {format_date(notice.new_deadline)}")
            lines += [f"<span style='color:#d33'>⚠ {w}</span>" for w in item.warnings]
            self.detail_label.setText("<br>".join(lines))
        else:
            self.detail_label.setText(f"<b>{item.title}</b> · {format_date(item.item_date)}<br>{item.comment}")
        doc_id = item.document_id
        if doc_id:
            doc = svc.documents.get(doc_id)
            self.preview.show_file(svc.documents.file_path(doc))
        else:
            self.preview.clear(tr("history.no_document"))

    def _row_activated(self, item: HistoryItem | None) -> None:
        if item and item.document_id:
            self.ctrl.open_document.emit(item.document_id)

    def _context_menu(self, pos) -> None:
        item = self.table.selected_payload()
        if not isinstance(item, HistoryItem) or item.kind != "entry" or item.reversed or item.entry_id is None:
            return
        if item.entry_type in (LedgerEntryType.REVERSAL, LedgerEntryType.INVOICE):
            return
        menu = QMenu(self)
        entry = self.ctrl.ctx.services.repos.ledger.get(item.entry_id)
        if entry and entry.payment_id:
            menu.addAction(tr("history.reverse_payment"), lambda: self._reverse_payment(entry.payment_id))
        else:
            menu.addAction(tr("history.reverse_entry"), lambda: self._reverse_entry(item.entry_id))
        menu.exec(self.table.viewport().mapToGlobal(pos))

    # -- actions ------------------------------------------------------------------------------------------------------------
    def _supplier_id(self) -> int:
        assert self.history is not None
        return self.history.invoice.supplier_id

    def _pay(self) -> None:
        if self.history:
            PaymentDialog(self.ctrl, self._supplier_id(), self.invoice_id, self).exec()

    def _notice(self) -> None:
        if self.invoice_id:
            NoticeDialog(self.ctrl, self.invoice_id, self).exec()

    def _credit(self) -> None:
        self._amount_action(tr("history.credit_note"), self.ctrl.ctx.services.invoices.credit_note, False, False)

    def _write_off(self) -> None:
        self._amount_action(tr("history.write_off"), self.ctrl.ctx.services.invoices.write_off, False, False)

    def _adjust(self) -> None:
        self._amount_action(tr("history.adjust"), self.ctrl.ctx.services.invoices.adjustment, True, True)

    def _amount_action(self, title: str, action, signed: bool, comment_required: bool) -> None:
        if not self.invoice_id:
            return
        dlg = AmountDialog(title, signed=signed, comment_required=comment_required, parent=self)
        if dlg.exec():
            cents, day, comment = dlg.values()
            self.ctrl.run(action, self.invoice_id, cents, day, comment, parent=self)

    def _dispute(self) -> None:
        if self.history:
            disputed = self.history.invoice.status != InvoiceStatus.DISPUTED
            self.ctrl.run(self.ctrl.ctx.services.invoices.set_disputed, self.invoice_id, disputed, parent=self)

    def _cancel(self) -> None:
        if self.invoice_id and confirm(self, tr("history.cancel.confirm")):
            self.ctrl.run(self.ctrl.ctx.services.invoices.cancel_invoice, self.invoice_id, "", parent=self)

    def _reverse_entry(self, entry_id: int | None) -> None:
        if entry_id and confirm(self, tr("history.reverse.confirm")):
            self.ctrl.run(self.ctrl.ctx.services.ledger.reverse_entry, entry_id, "", None, parent=self)

    def _reverse_payment(self, payment_id: int | None) -> None:
        if payment_id and confirm(self, tr("history.reverse.confirm")):
            self.ctrl.run(self.ctrl.ctx.services.payments.reverse_payment, payment_id, "", None, parent=self)

    def _open_case(self) -> None:
        if self.invoice_id:
            self.ctrl.run(self.ctrl.ctx.services.cases.open_manual, self.invoice_id, parent=self)

    def _case_status_changed(self, _index: int) -> None:
        if self.history and self.history.case and self.history.case.id:
            self.ctrl.run(self.ctrl.ctx.services.cases.set_status, self.history.case.id,
                          CaseStatus(self.case_status.currentData()), parent=self)

    def _add_note(self) -> None:
        if self.history and self.history.case and self.history.case.id:
            text, ok = QInputDialog.getMultiLineText(self, tr("history.add_note"), tr("history.note"))
            if ok and text.strip():
                self.ctrl.run(self.ctrl.ctx.services.cases.add_note, self.history.case.id, text.strip(), parent=self)


