"""GUI start-up."""

from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication

from supplier_app.controllers.app_controller import AppController
from supplier_app.errors import SupplierAppError
from supplier_app.i18n import tr
from supplier_app.main import build_context
from supplier_app.views.dialogs.pin_dialog import UnlockDialog
from supplier_app.views.errors import install_excepthook, show_error
from supplier_app.views.main_window import MainWindow
from supplier_app.views.theme import apply_theme


def run_application() -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName("SupplierApp")
    app.setApplicationDisplayName(tr("app.title"))
    install_excepthook()
    try:
        ctx = build_context()
    except SupplierAppError as exc:
        show_error(None, exc)
        return 2
    apply_theme(app, ctx.services.settings.theme)
    pin = ctx.services.pin
    if pin.enabled and not UnlockDialog(pin).exec():
        ctx.close()
        return 0
    ctrl = AppController(ctx, app)
    window = MainWindow(ctrl)
    window.show()
    ctrl.restart_idle_timer()
    code = app.exec()
    ctx.close()
    return code
