"""GUI start-up: connect to the PostgreSQL server, sign in, open the main window."""

from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication

from supplier_app.controllers.app_controller import AppController
from supplier_app.errors import SupplierAppError
from supplier_app.i18n import tr
from supplier_app.main import AppContext, build_context
from supplier_app.settings.connection import ConnectionConfig
from supplier_app.settings.paths import AppPaths, default_paths
from supplier_app.views.dialogs.connection_dialog import ConnectionDialog
from supplier_app.views.dialogs.login_dialog import FirstAdminDialog, LoginDialog
from supplier_app.views.errors import install_excepthook
from supplier_app.views.main_window import MainWindow
from supplier_app.views.theme import apply_theme


def open_context(paths: AppPaths) -> AppContext | None:
    """Connect to the server. Missing or wrong settings (first start, server not reachable) open the connection dialog."""
    config = ConnectionConfig.load(paths.root)
    error = ""
    while True:
        if not config.is_configured or error:
            dlg = ConnectionDialog(config, error=error)
            if not dlg.exec() or dlg.result_config is None:
                return None
            config = dlg.result_config
            config.save(paths.root, keep_password=dlg.keep_password)
        try:
            return build_context(paths, config)
        except SupplierAppError as exc:
            error = exc.message + (f"\n{exc.hint}" if exc.hint else "")
            if config.dsn_override:  # settings come from the environment: nothing to edit here
                from supplier_app.views.errors import show_error

                show_error(None, exc)
                return None


def sign_in(ctx: AppContext) -> str:
    """First administrator or login. Returns 'ok', 'quit' or 'connection' (the user wants to change the server)."""
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
    app.setApplicationDisplayName(tr("app.title"))
    install_excepthook()
    paths = default_paths().ensure()
    while True:
        ctx = open_context(paths)
        if ctx is None:
            return 2
        apply_theme(app, ctx.services.settings.theme)
        outcome = sign_in(ctx)
        if outcome == "ok":
            break
        ctx.close()
        if outcome == "quit":
            return 0
        dlg = ConnectionDialog(ctx.config)  # "Verbindung ändern" on the login screen
        if not dlg.exec() or dlg.result_config is None:
            return 0
        dlg.result_config.save(paths.root, keep_password=dlg.keep_password)
    ctrl = AppController(ctx, app)
    window = MainWindow(ctrl)
    window.show()
    ctrl.restart_idle_timer()
    ctrl.start_polling()
    code = app.exec()
    ctx.close()
    return code
