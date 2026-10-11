"""Application controller: signals that connect screens, theme switching, idle lock. No business logic."""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from PySide6.QtCore import QEvent, QObject, QTimer, Signal
from PySide6.QtWidgets import QApplication

from supplier_app.main import AppContext
from supplier_app.models.scope import ALL, Scope
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
    scope_changed = Signal(object)  # Scope
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
    user_changed = Signal()  # login / logout / user switch (multi-user mode)

    def __init__(self, ctx: AppContext, app: QApplication) -> None:
        super().__init__()
        self.ctx = ctx
        self.app = app
        self._scope: Scope = ctx.services.organization.scope_from_key(ctx.services.settings.get("active_scope"))
        self._idle = QTimer(self)
        self._idle.setSingleShot(True)
        self._idle.timeout.connect(self._idle_timeout)
        app.installEventFilter(self)
        self._last_version: int | None = None
        self._poll = QTimer(self)
        self._poll.timeout.connect(self.poll_changes)

    def start_polling(self, interval_ms: int = 3000) -> None:
        """Look every few seconds whether a colleague changed data and refresh then."""
        self._last_version = self._read_version()
        self._poll.start(interval_ms)

    def _read_version(self) -> int | None:
        try:
            return self.ctx.storage.db.data_version()
        except Exception:  # noqa: BLE001 - a lost connection is reported by the next real operation
            log.debug("change counter not readable", exc_info=True)
            return None

    def poll_changes(self) -> bool:
        """Refresh all screens when someone else changed the data. Returns True when a refresh happened."""
        version = self._read_version()
        if version is None or version == self._last_version:
            return False
        self._last_version = version
        who = ""
        try:
            who = str(self.ctx.storage.db.data_changed_by())
        except Exception:  # noqa: BLE001
            who = ""
        if who and who != self.ctx.services.session.username:
            self.status.emit(f"Daten wurden von {who} aktualisiert.")
        self.data_changed.emit()
        return True

    def shutdown(self) -> None:
        """Detach from the application (tests and clean exit)."""
        self._idle.stop()
        self._poll.stop()
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

    # -- scope (Gesellschaft / Hotel filter, global) ----------------------------------------------------
    @property
    def scope(self) -> Scope:
        return self._scope

    def set_scope(self, scope: Scope) -> None:
        if scope == self._scope:
            return
        self._scope = scope
        self.ctx.services.settings.set("active_scope", scope.key())
        self.scope_changed.emit(scope)
        self.notify_changed()

    def reload_scope(self) -> Scope:
        """Re-validate the active scope after companies/hotels changed (deleted entries fall back to 'all')."""
        org = self.ctx.services.organization
        valid = org.scope_from_key(self._scope.key()) if not self._scope.is_all else ALL
        if valid != self._scope:
            self.set_scope(valid)
        else:
            self.scope_changed.emit(self._scope)
        return self._scope

    # -- data -----------------------------------------------------------------------------------
    def notify_changed(self) -> None:
        """Call after any booking: all visible numbers are re-read from the ledger."""
        self._last_version = self._read_version()  # our own change is not a reason for a second refresh
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
        if minutes > 0:
            self._idle.start(minutes * 60_000)
        else:
            self._idle.stop()

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:  # noqa: N802 - Qt API
        if event.type() in _ACTIVITY_EVENTS and self._idle.isActive():
            self.restart_idle_timer()
        return False

    def _idle_timeout(self) -> None:
        self.lock_requested.emit()
