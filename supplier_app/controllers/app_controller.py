"""Application controller: signals that connect screens, theme switching, idle lock. No business logic."""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from PySide6.QtCore import QEvent, QObject, QTimer, Signal
from PySide6.QtWidgets import QApplication

from supplier_app.main import AppContext
from supplier_app.views.theme import apply_theme

log = logging.getLogger(__name__)

_ACTIVITY_EVENTS = {
    QEvent.Type.MouseMove, QEvent.Type.MouseButtonPress, QEvent.Type.KeyPress, QEvent.Type.Wheel,
    QEvent.Type.TouchBegin,
}


class AppController(QObject):
    """Central hub: screens emit requests here, the main window reacts."""

    data_changed = Signal()
    theme_changed = Signal(str)
    navigate = Signal(str)
    open_invoice = Signal(int)
    open_supplier = Signal(int)
    open_document = Signal(int)
    open_case = Signal(int)
    drill = Signal(object, object)  # DrillTarget, DashboardFilter
    focus_search = Signal()
    import_requested = Signal()
    payment_requested = Signal(object)  # optional (supplier_id, invoice_id)
    supplier_requested = Signal()
    lock_requested = Signal()
    status = Signal(str)

    def __init__(self, ctx: AppContext, app: QApplication) -> None:
        super().__init__()
        self.ctx = ctx
        self.app = app
        self._idle = QTimer(self)
        self._idle.setSingleShot(True)
        self._idle.timeout.connect(self._idle_timeout)
        app.installEventFilter(self)

    def shutdown(self) -> None:
        """Detach from the application (tests and clean exit)."""
        self._idle.stop()
        self.app.removeEventFilter(self)

    # -- theme -----------------------------------------------------------------------------
    @property
    def theme(self) -> str:
        return self.ctx.services.settings.theme

    def set_theme(self, name: str) -> None:
        self.ctx.services.settings.set_theme(name)
        apply_theme(self.app, name)
        self.theme_changed.emit(name)

    def toggle_theme(self) -> None:
        self.set_theme("light" if self.theme == "dark" else "dark")

    # -- data -----------------------------------------------------------------------------------
    def notify_changed(self) -> None:
        """Call after any booking: all visible numbers are re-read from the ledger."""
        self.data_changed.emit()

    def run(self, action: Callable[..., Any], *args: Any, parent: Any = None, success: str = "", notify: bool = True) -> Any:
        """Run a service call; friendly dialog on failure, refresh on success. Returns None on failure."""
        from supplier_app.views.errors import show_error
        try:
            result = action(*args)
        except Exception as exc:  # noqa: BLE001 - every error is shown to the user, never a traceback
            show_error(parent, exc)
            return None
        if success:
            self.status.emit(success)
        if notify:
            self.notify_changed()
        return result if result is not None else True

    # -- idle lock -----------------------------------------------------------------------------------
    def restart_idle_timer(self) -> None:
        minutes = self.ctx.services.settings.get_int("idle_lock_minutes")
        if self.ctx.services.pin.enabled and minutes > 0:
            self._idle.start(minutes * 60_000)
        else:
            self._idle.stop()

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:  # noqa: N802 - Qt API
        if event.type() in _ACTIVITY_EVENTS and self._idle.isActive():
            self.restart_idle_timer()
        return False

    def _idle_timeout(self) -> None:
        if self.ctx.services.pin.enabled:
            self.lock_requested.emit()
