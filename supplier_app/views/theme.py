"""Theme loading (QSS files) and palette access."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import QApplication

from .theme_tokens import TOKENS

THEMES_DIR = Path(__file__).parent / "themes"


def tokens(theme: str) -> dict[str, str]:
    return TOKENS["light" if theme == "light" else "dark"]


def color(theme: str, name: str) -> QColor:
    return QColor(tokens(theme)[name])


def apply_theme(app: QApplication, theme: str) -> None:
    """Apply dark.qss or light.qss and the base font; callable at runtime."""
    theme = "light" if theme == "light" else "dark"
    font = QFont("Segoe UI", 10)
    font.setStyleStrategy(QFont.StyleStrategy.PreferAntialias)
    app.setFont(font)
    qss = (THEMES_DIR / f"{theme}.qss").read_text(encoding="utf-8")
    app.setStyleSheet(qss)
    app.setProperty("themeName", theme)


def current_theme(app: QApplication) -> str:
    return str(app.property("themeName") or "dark")


def repolish(widget) -> None:
    """Re-evaluate dynamic properties (e.g. ``tone``) after changing them."""
    style = widget.style()
    style.unpolish(widget)
    style.polish(widget)
    widget.update()
