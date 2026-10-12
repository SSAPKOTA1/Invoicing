"""Offscreen UI check used by ``--selfcheck``: builds every screen in dark and light mode."""

from __future__ import annotations

import os

from supplier_app.main import AppContext

THEMES = ("dark", "light")


def make_window(ctx: AppContext):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from supplier_app.controllers.app_controller import AppController
    from supplier_app.views.main_window import MainWindow
    from supplier_app.views.theme import apply_theme

    app = QApplication.instance() or QApplication([])
    apply_theme(app, ctx.services.settings.theme)
    ctrl = AppController(ctx, app)
    window = MainWindow(ctrl)
    window.resize(1480, 900)
    return app, ctrl, window


def check_all_screens(ctx: AppContext) -> int:
    """Open every page in both themes; any exception propagates. Returns the number of combinations built."""
    app, ctrl, window = make_window(ctx)
    count = 0
    for theme in THEMES:
        ctrl.set_theme(theme)
        window.show()
        for key in window.pages:
            window.show_page(key)
            app.processEvents()
            window.grab()
            count += 1
    window.close()
    window.deleteLater()
    ctrl.shutdown()
    app.processEvents()
    from PySide6.QtCore import QEvent

    app.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    return count
