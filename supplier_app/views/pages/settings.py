"""Settings: theme, PIN, paths, Tesseract, rates, allocation rule, reference keywords, backup / restore, demo data."""

from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path

from PySide6.QtCore import QDate, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QComboBox,
    QDateEdit,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from supplier_app.controllers.app_controller import AppController
from supplier_app.errors import SupplierAppError
from supplier_app.i18n import tr
from supplier_app.models.enums import AllocationRule, ReferenceType
from supplier_app.util.dates import format_date
from supplier_app.views.dialogs.pin_dialog import ChangePinDialog
from supplier_app.views.errors import confirm, info, show_error
from supplier_app.views.pages.base import Page
from supplier_app.views.widgets.common import Card, button, muted, page_title, scroll_wrap
from supplier_app.views.widgets.data_table import Cell, DataTable, Row


class SettingsPage(Page):
    key = "settings"
    title = "nav.settings"

    def __init__(self, ctrl: AppController) -> None:
        super().__init__(ctrl)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        content = QWidget()
        outer.addWidget(scroll_wrap(content))
        root = QVBoxLayout(content)
        root.setContentsMargins(24, 20, 24, 24)
        root.setSpacing(14)
        root.addWidget(page_title(tr("nav.settings")))
        for builder in (self._appearance, self._security, self._paths, self._tesseract, self._interest, self._allocation,
                        self._references, self._backup, self._demo):
            root.addWidget(builder())
        root.addStretch(1)

    # -- cards ------------------------------------------------------------------------------------------------
    def _appearance(self) -> Card:
        card = Card(tr("settings.appearance"))
        self.theme = QComboBox()
        self.theme.addItem(tr("settings.theme.dark"), "dark")
        self.theme.addItem(tr("settings.theme.light"), "light")
        self.theme.activated.connect(lambda _i: self.ctrl.set_theme(self.theme.currentData()))
        card.add(self.theme)
        return card

    def _security(self) -> Card:
        card = Card(tr("settings.security"))
        self.pin_state = QLabel()
        card.add(self.pin_state)
        row = QHBoxLayout()
        self.btn_set = button(tr("pin.set.title"), "", lambda: self._pin("set"))
        self.btn_change = button(tr("pin.change.title"), "", lambda: self._pin("change"))
        self.btn_disable = button(tr("pin.disable.title"), "danger", lambda: self._pin("disable"))
        for b in (self.btn_set, self.btn_change, self.btn_disable):
            row.addWidget(b)
        row.addStretch(1)
        card.layout_.addLayout(row)
        form = QFormLayout()
        self.idle = QSpinBox()
        self.idle.setRange(0, 240)
        self.idle.setSuffix(" min")
        self.idle.editingFinished.connect(self._save_idle)
        form.addRow(tr("settings.idle"), self.idle)
        card.layout_.addLayout(form)
        card.add(muted(tr("settings.pin.recovery")))
        return card

    def _paths(self) -> Card:
        card = Card(tr("settings.paths"))
        p = self.ctrl.ctx.paths
        card.add(QLabel(f"{tr('settings.paths.data')}: {p.root}"))
        card.add(QLabel(f"{tr('settings.paths.docs')}: {p.documents}"))
        card.add(QLabel(f"{tr('settings.paths.backups')}: {p.backups}"))
        card.add(button(tr("settings.paths.open"), "", lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(p.root)))))
        return card

    def _tesseract(self) -> Card:
        card = Card(tr("settings.tesseract"))
        self.tess_path = QLineEdit()
        self.tess_path.setPlaceholderText(tr("settings.tesseract.path_hint"))
        row = QHBoxLayout()
        row.addWidget(self.tess_path, 1)
        row.addWidget(button(tr("common.browse"), "", self._browse_tess))
        row.addWidget(button(tr("settings.tesseract.check"), "primary", self.check_tesseract))
        card.layout_.addLayout(row)
        self.tess_info = QLabel()
        self.tess_info.setWordWrap(True)
        card.add(self.tess_info)
        return card

    def _interest(self) -> Card:
        card = Card(tr("settings.interest"))
        card.add(muted(tr("settings.interest.disclaimer")))
        form = QFormLayout()
        self.debtor = QComboBox()
        self.debtor.addItem(tr("settings.debtor.b2b"), "b2b")
        self.debtor.addItem(tr("settings.debtor.b2c"), "b2c")
        self.margin_b2b, self.margin_b2c = QLineEdit(), QLineEdit()
        self.flat_b2b, self.flat_b2c = QLineEdit(), QLineEdit()
        self.pay_days = QSpinBox()
        self.pay_days.setRange(0, 365)
        form.addRow(tr("settings.debtor"), self.debtor)
        form.addRow(tr("settings.margin_b2b"), self.margin_b2b)
        form.addRow(tr("settings.margin_b2c"), self.margin_b2c)
        form.addRow(tr("settings.flat_b2b"), self.flat_b2b)
        form.addRow(tr("settings.flat_b2c"), self.flat_b2c)
        form.addRow(tr("settings.pay_days"), self.pay_days)
        card.layout_.addLayout(form)
        card.add(button(tr("common.save"), "primary", self._save_interest))
        card.add(QLabel(tr("settings.rates")))
        self.rates = DataTable(sortable=False)
        self.rates.setMaximumHeight(210)
        card.add(self.rates)
        row = QHBoxLayout()
        self.rate_date = QDateEdit(QDate.currentDate())
        self.rate_date.setCalendarPopup(True)
        self.rate_date.setDisplayFormat("dd.MM.yyyy")
        self.rate_value = QLineEdit()
        self.rate_value.setPlaceholderText("z. B. 1,27")
        row.addWidget(QLabel(tr("settings.rate.valid_from")))
        row.addWidget(self.rate_date)
        row.addWidget(QLabel(tr("settings.rate.base")))
        row.addWidget(self.rate_value)
        row.addWidget(button(tr("settings.rate.add"), "", self._add_rate))
        row.addWidget(button(tr("settings.rate.delete"), "danger", self._delete_rate))
        row.addStretch(1)
        card.layout_.addLayout(row)
        return card

    def _allocation(self) -> Card:
        card = Card(tr("settings.allocation"))
        self.rule = QComboBox()
        for r in AllocationRule:
            self.rule.addItem(tr(f"rule.{r.value}"), r)
        self.rule.activated.connect(lambda _i: self.svc.settings.set("allocation_rule", AllocationRule(self.rule.currentData()).value))
        card.add(self.rule)
        return card

    def _references(self) -> Card:
        card = Card(tr("settings.references"))
        card.add(muted(tr("settings.references.hint")))
        self.ref_edits: dict[ReferenceType, QLineEdit] = {}
        form = QFormLayout()
        for t in ReferenceType:
            edit = QLineEdit()
            edit.setPlaceholderText(tr("settings.references.placeholder"))
            self.ref_edits[t] = edit
            form.addRow(tr(f"ref.{t.value}"), edit)
        card.layout_.addLayout(form)
        card.add(button(tr("common.save"), "primary", self._save_refs))
        return card

    def _backup(self) -> Card:
        card = Card(tr("settings.backup"))
        row = QHBoxLayout()
        row.addWidget(button(tr("settings.backup.create"), "primary", self.create_backup))
        row.addWidget(button(tr("settings.backup.restore"), "danger", self.restore_backup))
        row.addStretch(1)
        card.layout_.addLayout(row)
        card.add(muted(tr("settings.backup.hint")))
        return card

    def _demo(self) -> Card:
        card = Card(tr("settings.demo"))
        card.add(muted(tr("settings.demo.hint")))
        card.add(button(tr("action.demo"), "", self.load_demo))
        self.about = QLabel(tr("settings.about"))
        self.about.setObjectName("Muted")
        self.about.setWordWrap(True)
        card.add(self.about)
        return card

    # -- state -----------------------------------------------------------------------------------------------------
    def refresh(self) -> None:
        s = self.svc.settings
        self.theme.setCurrentIndex(self.theme.findData(s.theme))
        enabled = self.svc.pin.enabled
        self.pin_state.setText(tr("settings.pin.on") if enabled else tr("settings.pin.off"))
        self.btn_set.setEnabled(not enabled)
        self.btn_change.setEnabled(enabled)
        self.btn_disable.setEnabled(enabled)
        self.idle.setValue(s.get_int("idle_lock_minutes"))
        self.tess_path.setText(s.get("tesseract_path"))
        self.debtor.setCurrentIndex(self.debtor.findData(s.debtor_type))
        self.margin_b2b.setText(s.get("margin_b2b").replace(".", ","))
        self.margin_b2c.setText(s.get("margin_b2c").replace(".", ","))
        from supplier_app.util.money import format_cents
        self.flat_b2b.setText(format_cents(s.get_int("flat_fee_b2b_cents"), symbol=False))
        self.flat_b2c.setText(format_cents(s.get_int("flat_fee_b2c_cents"), symbol=False))
        self.pay_days.setValue(s.default_payment_days)
        self.rule.setCurrentIndex(self.rule.findData(s.allocation_rule))
        rules = s.reference_rules()
        for t, edit in self.ref_edits.items():
            edit.setText(", ".join(rules.get(t.value, [])))
        self._fill_rates()
        if not self.tess_info.text():
            self.check_tesseract()

    def _fill_rates(self) -> None:
        rows = [Row([Cell(format_date(r.valid_from), r.valid_from.toordinal()), Cell(f"{r.base_rate} %".replace(".", ","), align="right")],
                    r.valid_from) for r in reversed(self.svc.repos.rates.list())]
        self.rates.set_data([tr("settings.rate.valid_from"), tr("settings.rate.base")], rows, [160, 120])

    # -- actions ----------------------------------------------------------------------------------------------------------
    def _pin(self, mode: str) -> None:
        if ChangePinDialog(self.svc.pin, mode, self).exec():
            self.ctrl.restart_idle_timer()
            self.refresh()

    def _save_idle(self) -> None:
        self.svc.settings.set("idle_lock_minutes", str(self.idle.value()))
        self.ctrl.restart_idle_timer()

    def _browse_tess(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, tr("settings.tesseract"), "", "tesseract* (tesseract*);;*")
        if path:
            self.tess_path.setText(path)
            self.check_tesseract()

    def check_tesseract(self) -> None:
        self.svc.settings.set("tesseract_path", self.tess_path.text().strip())
        runner = self.ctrl.ctx.services.ingest.extractor.runner
        runner.configured_path = self.tess_path.text().strip()
        text = runner.info(refresh=True).describe()
        info_ = runner.info()
        if info_.available and not info_.has_german:
            text += "\n" + tr("settings.tesseract.no_german")
        self.tess_info.setText(text)
        self.tess_info.setObjectName("Muted" if info_.available else "Warning")
        self.tess_info.style().unpolish(self.tess_info)
        self.tess_info.style().polish(self.tess_info)

    def _save_interest(self) -> None:
        from supplier_app.util.money import parse_amount
        s = self.svc.settings
        try:
            for key, edit in (("margin_b2b", self.margin_b2b), ("margin_b2c", self.margin_b2c)):
                s.set(key, str(Decimal(edit.text().strip().replace(",", ".") or "0")))
            s.set("flat_fee_b2b_cents", str(parse_amount(self.flat_b2b.text() or "0")))
            s.set("flat_fee_b2c_cents", str(parse_amount(self.flat_b2c.text() or "0")))
        except (InvalidOperation, SupplierAppError) as exc:
            show_error(self, exc if isinstance(exc, SupplierAppError) else SupplierAppError(tr("error.number")))
            return
        s.set("debtor_type", self.debtor.currentData())
        s.set("default_payment_days", str(self.pay_days.value()))
        self.ctrl.status.emit(tr("settings.saved"))
        self.ctrl.notify_changed()

    def _add_rate(self) -> None:
        try:
            value = Decimal(self.rate_value.text().strip().replace(",", "."))
        except InvalidOperation:
            show_error(self, SupplierAppError(tr("error.number")))
            return
        qd = self.rate_date.date()
        self.svc.settings.set_rate(date(qd.year(), qd.month(), qd.day()), value)
        self._fill_rates()
        self.ctrl.notify_changed()

    def _delete_rate(self) -> None:
        valid_from = self.rates.selected_payload()
        if valid_from:
            self.svc.repos.rates.delete(valid_from)
            self._fill_rates()
            self.ctrl.notify_changed()

    def _save_refs(self) -> None:
        rules = {t.value: [w.strip() for w in e.text().split(",") if w.strip()] for t, e in self.ref_edits.items()}
        self.svc.settings.set_reference_rules({k: v for k, v in rules.items() if v})
        self.ctrl.status.emit(tr("settings.saved"))

    def create_backup(self) -> None:
        stamp = date.today().strftime("%Y%m%d")
        path, _ = QFileDialog.getSaveFileName(self, tr("settings.backup.create"),
                                              str(self.ctrl.ctx.paths.backups / f"SupplierApp-Backup-{stamp}.zip"), "ZIP (*.zip)")
        if path:
            result = self.ctrl.run(self.svc.backup.create_backup, Path(path), parent=self, notify=False)
            if result:
                info(self, tr("settings.backup.done"), str(path))

    def restore_backup(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, tr("settings.backup.restore"), str(self.ctrl.ctx.paths.backups), "ZIP (*.zip)")
        if path and confirm(self, tr("settings.backup.confirm")):
            result = self.ctrl.run(self.svc.backup.restore_backup, Path(path), parent=self)
            if result and result is not True:
                info(self, tr("settings.backup.restored"), tr("settings.backup.safety", path=str(result.safety_backup)))

    def load_demo(self) -> None:
        if self.ctrl.ctx.demo.has_data() and not confirm(self, tr("settings.demo.confirm")):
            return
        if self.ctrl.run(self.ctrl.ctx.demo.load, parent=self, success=tr("settings.demo.done")):
            self.ctrl.navigate.emit("dashboard")


