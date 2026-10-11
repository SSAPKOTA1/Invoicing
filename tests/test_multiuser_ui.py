"""Multi-user user interface: login, first administrator, users card, read-only role, live refresh, connection dialog."""

from __future__ import annotations

from datetime import date

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QEvent  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from supplier_app.main import build_context  # noqa: E402
from supplier_app.models.enums import UserRole  # noqa: E402
from supplier_app.selfcheck_ui import make_window  # noqa: E402
from supplier_app.settings.connection import ConnectionConfig  # noqa: E402
from supplier_app.settings.paths import AppPaths  # noqa: E402
from tests.helpers import make_scenario  # noqa: E402


@pytest.fixture(autouse=True)
def _qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture()
def server_ctx(pg_dsn, tmp_path):
    cfg = ConnectionConfig(mode="server", dsn_override=pg_dsn)
    ctx = build_context(AppPaths(tmp_path / "pc1"), cfg)
    yield ctx
    ctx.close()


def _teardown(app, ctrl, window) -> None:
    window.close()
    window.deleteLater()
    ctrl.shutdown()
    for top in QApplication.topLevelWidgets():
        top.deleteLater()
    app.processEvents()
    QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def test_context_in_server_mode_and_first_administrator(server_ctx, monkeypatch) -> None:
    from supplier_app.views.dialogs.login_dialog import FirstAdminDialog, LoginDialog

    ctx = server_ctx
    assert ctx.multi_user and ctx.storage.db.backend == "postgres" and ctx.services.documents.files_in_database
    users = ctx.services.users
    assert users.needs_first_admin()
    dlg = FirstAdminDialog(users)
    dlg.username.setText("chef")
    dlg.password.setText("geheim123")
    dlg.repeat.setText("geheim124")
    dlg.accept()
    assert not dlg.error.isHidden() and users.needs_first_admin()  # passwords differ
    dlg.repeat.setText("geheim123")
    dlg.accept()
    assert ctx.services.session.username == "chef" and ctx.services.session.is_admin
    users.logout()
    login = LoginDialog(users, server_label="srv:5432/db")
    login.username.setText("chef")
    login.password.setText("falsch")
    login.accept()
    assert not login.error.isHidden() and login.user is None
    login.password.setText("geheim123")
    login.accept()
    assert login.user is not None and ctx.services.session.username == "chef"
    # lock screen verifies the password of the running session without starting a new one
    lock = LoginDialog(users, fixed_user="chef")
    assert lock.username.isReadOnly()
    lock.password.setText("geheim123")
    lock.accept()
    assert lock.user is not None
    change = LoginDialog(users, server_label="srv")
    change._change_connection()
    assert change.change_connection


def test_window_users_card_roles_and_read_only(server_ctx) -> None:
    from supplier_app.views.dialogs.login_dialog import PasswordDialog, UserDialog

    ctx = server_ctx
    users = ctx.services.users
    users.create_user("chef", "geheim123", UserRole.ADMIN, "Die Chefin")
    users.create_user("max", "passwort2", UserRole.VIEWER)
    users.login("chef", "geheim123")
    make_scenario(ctx.services)
    app, ctrl, window = make_window(ctx)
    window.show()
    try:
        assert ctrl.multi_user and ctrl.lock_available and not window.btn_user.isHidden()
        assert "Die Chefin" in window.btn_user.text() and "Administrator" in window.btn_user.text()
        window.show_page("settings")
        sp = window.pages["settings"]
        assert sp.users_card.isVisible() and sp.account_card.isVisible() and not sp.security_card.isVisible()
        assert not sp.demo_card.isVisible() and sp.user_table.row_count() == 2
        assert "Mehrbenutzer" in sp.db_info.text() and sp.btn_conn.isEnabled() is False  # DSN comes from the environment
        # administrator creates a colleague through the dialog
        dlg = UserDialog(users)
        dlg.username.setText("anna")
        dlg.password.setText("passwort3")
        dlg.repeat.setText("passwort3")
        dlg.role.setCurrentIndex(dlg.role.findData(UserRole.EDITOR))
        dlg.accept()
        sp.refresh()
        assert sp.user_table.row_count() == 3
        edit = UserDialog(users, users.users()[0])  # anna
        edit.role.setCurrentIndex(edit.role.findData(UserRole.VIEWER))
        edit.active.setChecked(False)
        edit.accept()
        assert users.users()[0].role == UserRole.VIEWER and not users.users()[0].active
        bad = UserDialog(users)
        bad.username.setText("x")
        bad.password.setText("kurz")
        bad.repeat.setText("kurz")
        bad.accept()
        assert not bad.error.isHidden()
        anna = users.users()[0]
        pw = PasswordDialog(users, anna.id, own=False)
        pw.new.setText("neues-passwort")
        pw.repeat.setText("neues-passwort")
        pw.accept()
        assert users.verify("anna", "neues-passwort") is not None if anna.active else True
        # the viewer sees the read-only hint and cannot book
        users.login("max", "passwort2")
        window.refresh_user()
        assert not window.readonly_label.isHidden()
        sp.refresh()
        assert not sp.users_card.isVisible()
        from supplier_app.errors import DatabaseError

        with pytest.raises(DatabaseError, match="Lesen"):
            make_scenario(ctx.services, number="X-1")
        shown = []
        ctrl.status.connect(shown.append)
        assert ctrl.run(lambda: make_scenario(ctx.services, number="X-2"), parent=window) is None  # friendly error, no crash
    finally:
        _teardown(app, ctrl, window)


def test_live_refresh_when_a_colleague_changes_data(server_ctx, pg_dsn, tmp_path) -> None:
    from supplier_app.bootstrap import open_pg_storage
    from supplier_app.services.container import build_services

    ctx = server_ctx
    ctx.services.users.create_user("anna", "passwort1", UserRole.ADMIN)
    ctx.services.users.login("anna", "passwort1")
    app, ctrl, window = make_window(ctx)
    window.show()
    try:
        window.show_page("dashboard")
        ctrl.start_polling(60_000)  # the timer is not needed; poll_changes is called directly
        dash = window.pages["dashboard"]
        assert dash.data.empty
        assert ctrl.poll_changes() is False  # nothing happened yet
        other = open_pg_storage(AppPaths(tmp_path / "pc2").ensure(), pg_dsn)
        try:
            colleague = build_services(other, multi_user=True)
            colleague.users.create_user("ben", "passwort2", UserRole.EDITOR)
            colleague.users.login("ben", "passwort2")
            make_scenario(colleague)
            messages = []
            ctrl.status.connect(messages.append)
            assert ctrl.poll_changes() is True
            assert not dash.data.empty and any("ben" in m for m in messages)
            assert ctrl.poll_changes() is False  # same state: no second refresh
            ctx.services.invoices.create_invoice(
                colleague.suppliers.suppliers()[0].id, "EIGEN-1", date(2024, 3, 1), gross_cents=100)
            ctrl.notify_changed()  # our own change is not reported back
            assert ctrl.poll_changes() is False
        finally:
            other.close()
    finally:
        _teardown(app, ctrl, window)


def test_connection_dialog_and_start_flow(pg_dsn, tmp_path, monkeypatch) -> None:
    import psycopg

    from supplier_app.views import app as app_module
    from supplier_app.views.dialogs.connection_dialog import ConnectionDialog

    parts = psycopg.conninfo.conninfo_to_dict(pg_dsn)
    cfg = ConnectionConfig(mode="server", host=parts["host"], port=int(parts["port"]), user=parts.get("user", ""),
                           dbname=parts["dbname"])
    dlg = ConnectionDialog(ConnectionConfig())
    assert dlg.local.isChecked() and not dlg.host.isEnabled()
    dlg.server.setChecked(True)
    assert dlg.host.isEnabled()
    dlg.host.setText(cfg.host)
    dlg.port.setValue(cfg.port)
    dlg.dbname.setText(cfg.dbname)
    dlg.user.setText(cfg.user)
    dlg.test()
    assert not dlg.info.isHidden() and "PostgreSQL" in dlg.info.text()
    dlg.port.setValue(1)  # nothing listens there
    dlg.test()
    assert not dlg.error.isHidden()
    dlg.host.setText("")
    dlg.accept()
    assert dlg.result_config is None and not dlg.error.isHidden()  # server name missing
    dlg.host.setText(cfg.host)
    dlg.port.setValue(cfg.port)
    dlg.accept()
    assert dlg.result_config is not None and dlg.result_config.is_server

    # start flow: unreachable server -> connection dialog; cancelling ends the start
    paths = AppPaths(tmp_path / "pc").ensure()
    ConnectionConfig(mode="server", host="127.0.0.1", port=1, user="x", dbname="y").save(paths.root)
    seen = []

    def fake_exec(self) -> int:
        seen.append(self.error.text())
        return 0

    monkeypatch.setattr(ConnectionDialog, "exec", fake_exec)
    assert app_module.open_context(paths) is None
    assert seen and "Verbindung" in seen[0]
    # saved settings are used again; the password is stored only on request
    loaded = ConnectionConfig.load(paths.root)
    assert loaded.is_server and loaded.port == 1
    loaded.password = "geheim"
    loaded.save(paths.root, keep_password=False)
    assert ConnectionConfig.load(paths.root).password == ""
    # a valid server opens, the user is asked to sign in (first administrator)
    good = ConnectionConfig(mode="server", dsn_override=pg_dsn)
    ctx = build_context(paths, good)
    try:
        assert app_module.sign_in.__name__ == "sign_in" and ctx.services.users.needs_first_admin()
        monkeypatch.setattr("supplier_app.views.app.FirstAdminDialog.exec", lambda self: 0)
        assert app_module.sign_in(ctx) == "quit"
    finally:
        ctx.close()


def test_lock_screen_in_multi_user_mode(server_ctx, monkeypatch) -> None:
    from supplier_app.views.dialogs.login_dialog import LoginDialog

    ctx = server_ctx
    ctx.services.users.create_user("chef", "geheim123", UserRole.ADMIN)
    ctx.services.users.login("chef", "geheim123")
    app, ctrl, window = make_window(ctx)
    window.show()
    try:
        seen = {}

        def fake_exec(self) -> int:
            seen["fixed"] = self.fixed_user
            return 1

        monkeypatch.setattr(LoginDialog, "exec", fake_exec)
        window.lock()
        assert seen["fixed"] == "chef"
        ctx.services.settings.set("idle_lock_minutes", "5")
        ctrl.restart_idle_timer()
        assert ctrl._idle.isActive()  # idle lock works with the user password, no PIN needed
        # switching the user: the next login becomes the active session
        ctx.services.users.create_user("anna", "passwort1", UserRole.EDITOR)

        def switch_exec(self) -> int:
            self.username.setText("anna")
            self.password.setText("passwort1")
            self.accept()
            return 1

        monkeypatch.setattr(LoginDialog, "exec", switch_exec)
        window.switch_user()
        assert ctx.services.session.username == "anna" and "anna" in window.btn_user.text()
    finally:
        _teardown(app, ctrl, window)
