"""Base class of the navigation screens."""

from __future__ import annotations

from PySide6.QtWidgets import QWidget

from supplier_app.controllers.app_controller import AppController
from supplier_app.services.container import Services


class Page(QWidget):
    """A screen. ``refresh`` re-reads everything from the services (called after any booking)."""

    key = ""
    title = ""

    def __init__(self, ctrl: AppController) -> None:
        super().__init__()
        self.ctrl = ctrl
        self.setObjectName(f"Page_{self.key}")

    @property
    def svc(self) -> Services:
        return self.ctrl.ctx.services

    def refresh(self) -> None:
        """Reload data; overridden by screens."""

    def on_theme_changed(self, theme: str) -> None:
        """Re-render theme dependent content (charts)."""
        self.refresh()
