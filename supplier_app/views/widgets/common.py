"""Small building blocks used by many screens."""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from supplier_app.views.theme import repolish


class Card(QFrame):
    """Rounded surface with an optional title."""

    def __init__(self, title: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("Card")
        self.layout_ = QVBoxLayout(self)
        self.layout_.setContentsMargins(16, 14, 16, 14)
        self.layout_.setSpacing(10)
        self.title_label: QLabel | None = None
        if title:
            self.title_label = QLabel(title)
            self.title_label.setObjectName("SectionTitle")
            self.layout_.addWidget(self.title_label)

    def add(self, widget: QWidget, stretch: int = 0) -> None:
        self.layout_.addWidget(widget, stretch)


def page_title(text: str) -> QLabel:
    label = QLabel(text)
    label.setObjectName("PageTitle")
    return label


def muted(text: str = "") -> QLabel:
    label = QLabel(text)
    label.setObjectName("Muted")
    label.setWordWrap(True)
    return label


def button(text: str, kind: str = "", callback: Callable[[], None] | None = None, tooltip: str = "") -> QPushButton:
    b = QPushButton(text)
    if kind:
        b.setProperty("kind", kind)
    if tooltip:
        b.setToolTip(tooltip)
    if callback:
        b.clicked.connect(lambda _checked=False: callback())
    return b


class Badge(QLabel):
    """Colored status pill (tone: '', ok, warn, bad)."""

    def __init__(self, text: str = "", tone: str = "", parent: QWidget | None = None) -> None:
        super().__init__(text, parent)
        self.setObjectName("Badge")
        self.set_tone(tone)
        self.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)

    def set_tone(self, tone: str) -> None:
        self.setProperty("tone", tone)
        repolish(self)

    def set_badge(self, text: str, tone: str) -> None:
        self.setText(text)
        self.set_tone(tone)


def status_tone(status: str) -> str:
    return {"paid": "ok", "partially_paid": "warn", "open": "", "disputed": "bad", "cancelled": ""}.get(status, "")


class ClickableFrame(QFrame):
    """Frame that emits ``clicked`` on a left click."""

    clicked = Signal()

    def mousePressEvent(self, event) -> None:  # noqa: N802 - Qt API
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)


def hbox(*widgets: QWidget | int, spacing: int = 8, margins: tuple[int, int, int, int] = (0, 0, 0, 0)) -> QHBoxLayout:
    """Layout helper: widgets, ``0`` entries become stretches."""
    lay = QHBoxLayout()
    lay.setSpacing(spacing)
    lay.setContentsMargins(*margins)
    for w in widgets:
        if isinstance(w, int):
            lay.addStretch(w or 1)
        else:
            lay.addWidget(w)
    return lay


def scroll_wrap(widget: QWidget) -> QScrollArea:
    area = QScrollArea()
    area.setWidgetResizable(True)
    area.setWidget(widget)
    area.setFrameShape(QFrame.Shape.NoFrame)
    return area
