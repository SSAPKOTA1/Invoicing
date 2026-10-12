"""GUI start-up: choose the data location (local file or server), log in, open the main window."""

from __future__ import annotations

import os
import sys

from PySide6.QtWidgets import QApplication

from supplier_app.controllers.app_controller import AppController
from supplier_app.errors import SupplierAppError
from supplier_app.i18n import set_language, tr
from supplier_app.main import AppContext, build_context
from supplier_app.settings.connection import ConnectionConfig
from supplier_app.settings.local_prefs import saved_language
from supplier_app.settings.paths import AppPaths, default_paths
from supplier_app.views.dialogs.connection_dialog import ConnectionDialog
from supplier_app.views.dialogs.login_dialog import FirstAdminDialog, LoginDialog
from supplier_app.views.dialogs.pin_dialog import UnlockDialog
from supplier_app.views.errors import install_excepthook, show_error
from supplier_app.views.main_window import MainWindow
from supplier_app.views.theme import apply_theme


def open_context(paths: AppPaths) -> AppContext | None:
    """Open the configured data source. A server that cannot be reached leads to the connection dialog."""
    config = ConnectionConfig.load(paths.local)
    while True:
        try:
            return build_context(paths, config)
        except SupplierAppError as exc:
            if not config.is_multi_user:
                show_error(None, exc)
                return None
            text = exc.message + (f"\n{exc.hint}" if exc.hint else "")
            dlg = ConnectionDialog(config, error=text)
            if not dlg.exec() or dlg.result_config is None:
                return None
            config = dlg.result_config
            if not config.dsn_override:
                config.save(paths.local, keep_password=dlg.keep_password)


def sign_in(ctx: AppContext) -> str:
    """Multi-user mode: first administrator or login. Returns 'ok', 'quit' or 'connection' (user wants to change the server)."""
    users = ctx.services.users
    if users.needs_first_admin():
        return "ok" if FirstAdminDialog(users).exec() else "quit"
    dlg = LoginDialog(users, server_label=ctx.config.server_label)
    if dlg.exec():
        return "ok"
    return "connection" if dlg.change_connection else "quit"


def run_application() -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName("SupplierApp")
    paths = default_paths().ensure()
    set_language(os.environ.get("SUPPLIERAPP_LANGUAGE") or saved_language(paths.local) or "de")  # also for the first dialogs
    app.setApplicationDisplayName(tr("app.title"))
    install_excepthook()
    while True:
        ctx = open_context(paths)
        if ctx is None:
            return 2
        apply_theme(app, ctx.services.settings.theme)
        if not ctx.multi_user:
            pin = ctx.services.pin
            if pin.enabled and not UnlockDialog(pin).exec():
                ctx.close()
                return 0
            break
        outcome = sign_in(ctx)
        if outcome == "ok":
            break
        ctx.close()
        if outcome == "quit":
            return 0
        dlg = ConnectionDialog(ctx.config)  # "Verbindung ändern" on the login screen
        if not dlg.exec() or dlg.result_config is None:
            return 0
        dlg.result_config.save(paths.local, keep_password=dlg.keep_password)
    ctrl = AppController(ctx, app)
    window = MainWindow(ctrl)
    window.show()
    ctrl.restart_idle_timer()
    ctrl.start_polling()
    ctrl.start_recurring()
    code = app.exec()
    ctx.close()
    return code
