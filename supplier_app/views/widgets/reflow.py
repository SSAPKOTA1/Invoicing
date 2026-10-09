"""Grid that re-flows its items into as many columns as fit the width."""

from __future__ import annotations

from PySide6.QtWidgets import QGridLayout, QWidget


class ReflowGrid(QWidget):
    def __init__(self, min_item_width: int = 240, max_cols: int = 6, spacing: int = 12,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._items: list[QWidget] = []
        self._min = min_item_width
        self._max = max_cols
        self._cols = 0
        self._grid = QGridLayout(self)
        self._grid.setContentsMargins(0, 0, 0, 0)
        self._grid.setSpacing(spacing)

    def add(self, widget: QWidget) -> None:
        self._items.append(widget)
        self._relayout(force=True)

    def clear(self) -> None:
        for w in self._items:
            self._grid.removeWidget(w)
            w.setParent(None)
            w.deleteLater()
        self._items.clear()
        self._cols = 0

    def columns_for(self, width: int) -> int:
        return max(1, min(self._max, width // self._min))

    def _relayout(self, force: bool = False) -> None:
        cols = self.columns_for(max(self.width(), self._min))
        if cols == self._cols and not force:
            return
        self._cols = cols
        for w in self._items:
            self._grid.removeWidget(w)
        for i, w in enumerate(self._items):
            self._grid.addWidget(w, i // cols, i % cols)
        for c in range(cols):
            self._grid.setColumnStretch(c, 1)
        for c in range(cols, self._max + 1):
            self._grid.setColumnStretch(c, 0)

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt API
        super().resizeEvent(event)
        self._relayout()
