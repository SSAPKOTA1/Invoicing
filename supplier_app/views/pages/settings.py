"""Settings: theme, PIN, paths, Tesseract, rates, allocation rule, reference keywords, backup / restore, demo data."""

from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path

from PySide6.QtCore import QDate, Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QComboBox,
    QDateEdit,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from supplier_app.ai.vocab import EXTRA_VOCAB_KEYS
from supplier_app.controllers.app_controller import AppController
from supplier_app.errors import SupplierAppError
from supplier_app.i18n import LANGUAGES, current_language, tr
from supplier_app.models.enums import AllocationRule, ReferenceType
from supplier_app.util.dates import format_date
from supplier_app.views.dialogs.connection_dialog import ConnectionDialog
from supplier_app.views.dialogs.login_dialog import PasswordDialog, UserDialog
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
        self._pending_language = ""  # chosen, but active only after the restart
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        content = QWidget()
        outer.addWidget(scroll_wrap(content))
        root = QVBoxLayout(content)
        root.setContentsMargins(24, 20, 24, 24)
        root.setSpacing(14)
        root.addWidget(page_title(tr("nav.settings")))
        for builder in (self._appearance, self._organization, self._database, self._account, self._users, self._security, self._paths, self._tesseract, self._interest, self._allocation,
                        self._references, self._vocabulary, self._backup, self._demo):
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
        self.language = QComboBox()
        for code, name in LANGUAGES.items():
            self.language.addItem(name, code)
        self.language.activated.connect(lambda _i: self._language_chosen())
        form = QFormLayout()
        form.addRow(tr("settings.language"), self.language)
        card.layout_.addLayout(form)
        card.add(muted(tr("settings.language.hint")))
        return card

    def _language_chosen(self) -> None:
        code = str(self.language.currentData())
        if code == current_language():
            self._pending_language = ""
            return
        self._pending_language = code
        self.ctrl.set_language(code)
        if confirm(self, tr("settings.language.restart")):
            self.ctrl.restart_application()
        else:
            info(self, tr("settings.language.later"))

    def _organization(self) -> Card:
        card = Card(tr("org.title"))
        card.add(muted(tr("org.hint")))
        self.org_table = DataTable(sortable=False)
        self.org_table.setMaximumHeight(230)
        card.add(self.org_table)
        row = QHBoxLayout()
        row.addWidget(button(tr("org.add_company"), "primary", self.add_company))
        row.addWidget(button(tr("org.add_hotel"), "", self.add_hotel))
        row.addWidget(button(tr("org.rename"), "", self.rename_org))
        row.addWidget(button(tr("common.delete"), "danger", self.delete_org))
        row.addStretch(1)
        card.layout_.addLayout(row)
        return card

    # -- multi-user mode ----------------------------------------------------------------------------------------
    def _database(self) -> Card:
        card = Card(tr("settings.database"))
        self.db_info = QLabel()
        self.db_info.setWordWrap(True)
        self.db_info.setTextFormat(Qt.TextFormat.RichText)
        card.add(self.db_info)
        row = QHBoxLayout()
        self.btn_conn = button(tr("settings.database.change"), "", self.change_connection)
        self.btn_transfer = button(tr("settings.database.transfer"), "", self.transfer_to_server)
        self.btn_transfer_shared = button(tr("settings.database.transfer_shared"), "", self.transfer_to_shared)
        self.btn_all = button(tr("settings.database.all_pcs"), "", self.save_for_all_pcs)
        row.addWidget(self.btn_conn)
        row.addWidget(self.btn_all)
        row.addWidget(self.btn_transfer_shared)
        row.addWidget(self.btn_transfer)
        row.addStretch(1)
        card.layout_.addLayout(row)
        card.add(muted(tr("settings.database.hint")))
        self.database_card = card
        return card

    def _account(self) -> Card:
        card = Card(tr("settings.account"))
        self.account_info = QLabel()
        card.add(self.account_info)
        card.add(button(tr("user.password.change"), "", self.change_own_password))
        self.account_card = card
        return card

    def _users(self) -> Card:
        card = Card(tr("settings.users"))
        card.add(muted(tr("settings.users.hint")))
        self.user_table = DataTable(sortable=False)
        self.user_table.setMaximumHeight(230)
        card.add(self.user_table)
        row = QHBoxLayout()
        row.addWidget(button(tr("user.new"), "primary", self.new_user))
        row.addWidget(button(tr("user.edit"), "", self.edit_user))
        row.addWidget(button(tr("user.password.reset"), "", self.reset_user_password))
        row.addWidget(button(tr("common.delete"), "danger", self.delete_user))
        row.addStretch(1)
        card.layout_.addLayout(row)
        self.users_card = card
        return card

    def _security(self) -> Card:
        card = Card(tr("settings.security"))
        self.security_card = card
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

    def _vocabulary(self) -> Card:
        card = Card(tr("settings.vocab"))
        card.add(muted(tr("settings.vocab.hint")))
        self.vocab_edits: dict[str, QLineEdit] = {}
        form = QFormLayout()
        for key in EXTRA_VOCAB_KEYS:
            edit = QLineEdit()
            edit.setPlaceholderText(tr("settings.references.placeholder"))
            self.vocab_edits[key] = edit
            form.addRow(tr(f"settings.vocab.{key}"), edit)
        card.layout_.addLayout(form)
        card.add(button(tr("common.save"), "primary", self._save_vocab))
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
        self.demo_card = card
        card.add(muted(tr("settings.demo.hint")))
        card.add(button(tr("action.demo"), "", self.load_demo))
        self.about = QLabel(tr("settings.about"))
        self.about.setObjectName("Muted")
        self.about.setWordWrap(True)
        card.add(self.about)
        return card

    # -- state -----------------------------------------------------------------------------------------------------
    def _refresh_multi_user(self) -> None:
        multi = self.ctrl.multi_user
        session = self.svc.session
        admin = session.is_admin
        self.security_card.setVisible(not multi)  # the PIN lock is replaced by the user passwords
        self.account_card.setVisible(multi)
        self.users_card.setVisible(multi and admin)
        cfg = self.ctrl.ctx.config
        if multi and cfg.is_shared:
            registry = self.ctrl.ctx.registry
            others = registry.others_label() if registry is not None else []
            text = tr("settings.database.shared", path=cfg.shared_path)
            if others:
                text += "<br>" + tr("settings.database.shared.others", names=", ".join(others))
            self.db_info.setText(text)
        elif multi:
            self.db_info.setText(tr("settings.database.server", server=cfg.server_label))
        if multi:
            self.account_info.setText(tr("settings.account.info", name=session.label, role=tr(f"role.user.{session.role.value}")))
        else:
            self.db_info.setText(tr("settings.database.local", path=str(self.ctrl.ctx.paths.root)))
        self.btn_conn.setEnabled(admin and not cfg.dsn_override)
        self.demo_card.setVisible(not multi)  # never fill a shared company database with sample data
        self.btn_all.setVisible(multi and cfg.is_shared)
        self.btn_all.setEnabled(admin)
        self.btn_transfer.setVisible(not multi)
        self.btn_transfer.setEnabled(admin)
        self.btn_transfer_shared.setVisible(not multi)
        self.btn_transfer_shared.setEnabled(admin)
        if multi and admin:
            rows = [Row([u.username, u.display_name, tr(f"role.user.{u.role.value}"),
                         tr("user.active") if u.active else tr("user.locked"), u.last_login.replace("T", " ")], u.id)
                    for u in self.svc.users.users()]
            self.user_table.set_data([tr("login.username"), tr("user.display_name"), tr("user.role"), tr("user.status"),
                                      tr("user.last_login")], rows, [150, 200, 140, 90, 160])

    def _selected_user(self):  # type: ignore[no-untyped-def]
        uid = self.user_table.selected_payload()
        return self.svc.users.get(uid) if uid else None

    def new_user(self) -> None:
        if UserDialog(self.svc.users, parent=self).exec():
            self._refresh_multi_user()

    def edit_user(self) -> None:
        user = self._selected_user()
        if user is not None and UserDialog(self.svc.users, user, self).exec():
            self._refresh_multi_user()
            self.ctrl.notify_changed()

    def reset_user_password(self) -> None:
        user = self._selected_user()
        if user is not None and user.id is not None and PasswordDialog(self.svc.users, user.id, own=False, parent=self).exec():
            self.ctrl.status.emit(tr("user.password.done"))

    def delete_user(self) -> None:
        user = self._selected_user()
        if user is None or not confirm(self, tr("user.delete.confirm", name=user.username)):
            return
        if self.ctrl.run(self.svc.users.delete_user, user.id, parent=self, notify=False):
            self._refresh_multi_user()

    def change_own_password(self) -> None:
        user = self.svc.session.user
        if user is not None and user.id is not None:
            PasswordDialog(self.svc.users, user.id, own=True, parent=self).exec()

    def change_connection(self) -> None:
        dlg = ConnectionDialog(self.ctrl.ctx.config, self)
        if dlg.exec() and dlg.result_config is not None:
            dlg.result_config.save(self.ctrl.ctx.paths.local, keep_password=dlg.keep_password)
            info(self, tr("settings.database.restart"))
            self.ctrl.app.quit()

    def save_for_all_pcs(self) -> None:
        path = self.ctrl.run(self.ctrl.ctx.config.save_for_all_pcs, parent=self, notify=False)
        if path:
            info(self, tr("settings.database.all_pcs.done", path=str(path)))

    def transfer_to_shared(self) -> None:
        """Local data -> empty shared folder; afterwards the application works from that folder."""
        from supplier_app.backup.transfer import transfer_to_shared
        from supplier_app.settings.connection import MODE_SHARED, ConnectionConfig

        dlg = ConnectionDialog(ConnectionConfig(mode=MODE_SHARED), self)
        if not dlg.exec() or dlg.result_config is None or not dlg.result_config.is_shared:
            return
        target = dlg.result_config
        if not confirm(self, tr("settings.database.transfer_shared.confirm", path=target.shared_path)):
            return
        files = self.ctrl.run(transfer_to_shared, self.ctrl.ctx.storage, target.shared_path, parent=self, notify=False)
        if files:
            target.save(self.ctrl.ctx.paths.local, keep_password=dlg.keep_password)
            info(self, tr("settings.database.transfer_shared.done", n=files))
            self.ctrl.app.quit()

    def transfer_to_server(self) -> None:
        """Local data -> empty server database; afterwards the application starts in the multi-user mode."""
        from supplier_app.backup.transfer import transfer_to_server
        from supplier_app.settings.connection import MODE_SERVER, ConnectionConfig

        cfg = ConnectionConfig(mode=MODE_SERVER)
        dlg = ConnectionDialog(cfg, self)
        if not dlg.exec() or dlg.result_config is None or not dlg.result_config.is_server:
            return
        target = dlg.result_config
        if not confirm(self, tr("settings.database.transfer.confirm", server=target.server_label)):
            return
        rows = self.ctrl.run(transfer_to_server, self.ctrl.ctx.storage, target, parent=self, notify=False)
        if rows:
            target.save(self.ctrl.ctx.paths.local, keep_password=dlg.keep_password)
            info(self, tr("settings.database.transfer.done", n=rows))
            self.ctrl.app.quit()

    def refresh(self) -> None:
        self._refresh_multi_user()
        s = self.svc.settings
        self.theme.setCurrentIndex(self.theme.findData(s.theme))
        self.language.setCurrentIndex(self.language.findData(self._pending_language or current_language()))
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
        vocab = s.custom_vocab()
        for key, edit in self.vocab_edits.items():
            edit.setText(", ".join(vocab.get(key, [])))
        self._fill_rates()
        self._fill_organization()
        if not self.tess_info.text():
            self.check_tesseract()

    def _fill_organization(self) -> None:
        org = self.svc.organization
        rows = []
        for company in org.companies():
            rows.append(Row([Cell(company.name, tone="muted"), tr("org.company"),
                             str(len(org.hotels(company.id)))], ("c", company.id)))
            for hotel in org.hotels(company.id):
                rows.append(Row([Cell("      " + hotel.name), tr("org.hotel"), ""], ("h", hotel.id)))
        self.org_table.set_data([tr("org.name"), tr("org.kind"), tr("org.hotel_count")], rows, [320, 140, 100])

    def _ask_name(self, title: str, text: str = "") -> str:
        name, ok = QInputDialog.getText(self, title, tr("org.name"), text=text)
        return name.strip() if ok else ""

    def _org_changed(self) -> None:
        self.ctrl.reload_scope()
        self.ctrl.notify_changed()

    def add_company(self) -> None:
        name = self._ask_name(tr("org.add_company"))
        if name and self.ctrl.run(self.svc.organization.create_company, name, parent=self, notify=False):
            self._org_changed()

    def _selected_org(self) -> tuple[str, int] | None:
        payload = self.org_table.selected_payload()
        return payload if payload else None

    def add_hotel(self) -> None:
        sel = self._selected_org()
        if sel is None:
            info(self, tr("org.select_company"))
            return
        kind, ident = sel
        company_id = ident if kind == "c" else self.svc.organization.hotel(ident).company_id
        name = self._ask_name(tr("org.add_hotel"))
        if name and self.ctrl.run(self.svc.organization.create_hotel, company_id, name, parent=self, notify=False):
            self._org_changed()

    def rename_org(self) -> None:
        sel = self._selected_org()
        if sel is None:
            return
        kind, ident = sel
        org = self.svc.organization
        current = org.company(ident).name if kind == "c" else org.hotel(ident).name
        name = self._ask_name(tr("org.rename"), current)
        if not name:
            return
        action = org.rename_company if kind == "c" else org.rename_hotel
        if self.ctrl.run(action, ident, name, parent=self, notify=False):
            self._org_changed()

    def delete_org(self) -> None:
        sel = self._selected_org()
        if sel is None or not confirm(self, tr("org.delete.confirm")):
            return
        kind, ident = sel
        org = self.svc.organization
        action = org.delete_company if kind == "c" else org.delete_hotel
        if self.ctrl.run(action, ident, parent=self, notify=False):
            self._org_changed()

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

    def _save_vocab(self) -> None:
        vocab = {k: [w.strip() for w in e.text().split(",") if w.strip()] for k, e in self.vocab_edits.items()}
        self.svc.settings.set_custom_vocab(vocab)
        self.ctrl.status.emit(tr("settings.saved"))

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


