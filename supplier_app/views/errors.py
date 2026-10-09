"""Friendly error dialogs (never raw tracebacks)."""

from __future__ import annotations

import logging
import sys
import traceback

from PySide6.QtWidgets import QMessageBox, QWidget

from supplier_app.errors import SupplierAppError
from supplier_app.i18n import tr

log = logging.getLogger(__name__)


def error_text(exc: BaseException) -> tuple[str, str]:
    """(message, hint) for any exception."""
    if isinstance(exc, SupplierAppError):
        return exc.message, exc.hint or ""
    return tr("error.unexpected"), tr("error.see_log")


def show_error(parent: QWidget | None, exc: BaseException) -> None:
    message, hint = error_text(exc)
    if not isinstance(exc, SupplierAppError):
        log.error("unexpected error: %s", "".join(traceback.format_exception(exc)))
    box = QMessageBox(parent)
    box.setIcon(QMessageBox.Icon.Warning)
    box.setWindowTitle(tr("app.title"))
    box.setText(message)
    if hint:
        box.setInformativeText(hint)
    box.exec()


def install_excepthook() -> None:
    """Show unexpected exceptions in a dialog and log them."""
    def hook(exc_type, exc, tb) -> None:
        log.error("uncaught exception", exc_info=(exc_type, exc, tb))
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc, tb)
            return
        show_error(None, exc)

    sys.excepthook = hook


def confirm(parent: QWidget | None, text: str, informative: str = "") -> bool:
    box = QMessageBox(parent)
    box.setIcon(QMessageBox.Icon.Question)
    box.setWindowTitle(tr("app.title"))
    box.setText(text)
    if informative:
        box.setInformativeText(informative)
    yes = box.addButton(tr("common.yes"), QMessageBox.ButtonRole.AcceptRole)
    box.addButton(tr("common.no"), QMessageBox.ButtonRole.RejectRole)
    box.exec()
    return box.clickedButton() is yes


def info(parent: QWidget | None, text: str, informative: str = "") -> None:
    box = QMessageBox(parent)
    box.setIcon(QMessageBox.Icon.Information)
    box.setWindowTitle(tr("app.title"))
    box.setText(text)
    if informative:
        box.setInformativeText(informative)
    box.exec()
