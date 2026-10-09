"""KPI card: title, big value, change vs. previous period; clickable for drill-down."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from supplier_app.views.theme import repolish
from supplier_app.views.widgets.common import ClickableFrame


class KpiCard(ClickableFrame):
    """``clicked`` is emitted on click (the dashboard maps it to a drill-down)."""

    clicked_key = Signal(str)

    def __init__(self, key: str, title: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.key = key
        self.setObjectName("KpiCard")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumHeight(92)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 10, 14, 10)
        lay.setSpacing(2)
        self.title = QLabel(title)
        self.title.setObjectName("KpiTitle")
        self.title.setWordWrap(True)
        self.value = QLabel("–")
        self.value.setObjectName("KpiValue")
        self.delta = QLabel("")
        self.delta.setObjectName("KpiDelta")
        lay.addWidget(self.title)
        lay.addWidget(self.value)
        lay.addWidget(self.delta)
        self.clicked.connect(lambda: self.clicked_key.emit(self.key))

    def set_content(self, value: str, delta_text: str = "", tone: str = "", tooltip: str = "") -> None:
        self.value.setText(value)
        self.delta.setText(delta_text)
        self.delta.setProperty("tone", tone)
        repolish(self.delta)
        self.setToolTip(tooltip)
