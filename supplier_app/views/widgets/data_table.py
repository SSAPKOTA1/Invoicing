"""Sortable read-only table on top of QStandardItemModel."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from PySide6.QtCore import QModelIndex, QSortFilterProxyModel, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QStandardItem, QStandardItemModel
from PySide6.QtWidgets import QAbstractItemView, QHeaderView, QTableView, QWidget

from supplier_app.views.theme import current_theme, tokens

SORT_ROLE = Qt.ItemDataRole.UserRole + 1
PAYLOAD_ROLE = Qt.ItemDataRole.UserRole + 2


@dataclass
class Cell:
    text: str
    sort: Any = None
    align: str = "left"  # left | right | center
    tone: str = ""  # ok | warn | bad | muted
    tooltip: str = ""


@dataclass
class Row:
    cells: list[Cell | str]
    payload: Any = None
    tone: str = ""  # row background: warn | bad | ok


def money_cell(cents: int, text: str, tone: str = "") -> Cell:
    return Cell(text, cents, "right", tone)


class DataTable(QTableView):
    """Read-only table; ``row_activated`` fires with the row payload on double click / Enter."""

    row_activated = Signal(object)
    row_selected = Signal(object)

    def __init__(self, parent: QWidget | None = None, *, sortable: bool = True, stretch_last: bool = True) -> None:
        super().__init__(parent)
        self._model = QStandardItemModel(self)
        self._proxy = QSortFilterProxyModel(self)
        self._proxy.setSourceModel(self._model)
        self._proxy.setSortRole(SORT_ROLE)
        self._proxy.setFilterCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self._proxy.setFilterKeyColumn(-1)
        self.setModel(self._proxy)
        self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.setAlternatingRowColors(True)
        self.setSortingEnabled(sortable)
        self.setShowGrid(False)
        self.verticalHeader().setVisible(False)
        self.verticalHeader().setDefaultSectionSize(30)
        self.horizontalHeader().setStretchLastSection(stretch_last)
        self.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self.setWordWrap(False)
        self.setTextElideMode(Qt.TextElideMode.ElideRight)
        self.doubleClicked.connect(self._on_double_click)
        self.selectionModel().selectionChanged.connect(self._on_selection)
        self._sortable = sortable

    # -- data -----------------------------------------------------------------------
    def set_data(self, headers: list[str], rows: list[Row], widths: list[int] | None = None) -> None:
        tk = tokens(current_theme(self._app()))
        tone_fg = {"ok": QColor(tk["ok"]), "warn": QColor(tk["warn"]), "bad": QColor(tk["danger"]),
                   "muted": QColor(tk["muted"])}
        tone_bg = {"ok": QColor(tk["ok_bg"]), "warn": QColor(tk["warn_bg"]), "bad": QColor(tk["danger_bg"])}
        sorting = self._sortable
        self.setSortingEnabled(False)
        self._model.clear()
        self._model.setHorizontalHeaderLabels(headers)
        align = {"left": Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                 "right": Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                 "center": Qt.AlignmentFlag.AlignCenter}
        for row in rows:
            items: list[QStandardItem] = []
            for i, raw in enumerate(row.cells):
                cell = raw if isinstance(raw, Cell) else Cell(str(raw))
                item = QStandardItem(cell.text)
                item.setEditable(False)
                item.setData(cell.sort if cell.sort is not None else cell.text.lower(), SORT_ROLE)
                item.setTextAlignment(align[cell.align])
                if cell.tone in tone_fg:
                    item.setForeground(QBrush(tone_fg[cell.tone]))
                if row.tone in tone_bg:
                    item.setBackground(QBrush(tone_bg[row.tone]))
                if cell.tooltip:
                    item.setToolTip(cell.tooltip)
                elif cell.text and len(cell.text) > 28:
                    item.setToolTip(cell.text)
                if i == 0:
                    item.setData(row.payload, PAYLOAD_ROLE)
                items.append(item)
            self._model.appendRow(items)
        self.setSortingEnabled(sorting)
        if widths:
            for i, w in enumerate(widths):
                if w:
                    self.setColumnWidth(i, w)

    @staticmethod
    def _app():
        from PySide6.QtWidgets import QApplication
        return QApplication.instance()

    def row_count(self) -> int:
        return self._model.rowCount()

    def set_filter_text(self, text: str) -> None:
        self._proxy.setFilterFixedString(text)

    def payload_at(self, proxy_row: int) -> Any:
        idx = self._proxy.index(proxy_row, 0)
        return self._proxy.data(idx, PAYLOAD_ROLE)

    def selected_payload(self) -> Any:
        rows = self.selectionModel().selectedRows()
        return self._proxy.data(rows[0], PAYLOAD_ROLE) if rows else None

    def select_payload(self, payload: Any) -> bool:
        for r in range(self._proxy.rowCount()):
            if self.payload_at(r) == payload:
                self.selectRow(r)
                return True
        return False

    def all_payloads(self) -> list[Any]:
        return [self.payload_at(r) for r in range(self._proxy.rowCount())]

    # -- signals -----------------------------------------------------------------------
    def _on_double_click(self, index: QModelIndex) -> None:
        self.row_activated.emit(self._proxy.data(self._proxy.index(index.row(), 0), PAYLOAD_ROLE))

    def _on_selection(self, *_args) -> None:
        self.row_selected.emit(self.selected_payload())

    def keyPressEvent(self, event) -> None:  # noqa: N802 - Qt API
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            payload = self.selected_payload()
            if payload is not None:
                self.row_activated.emit(payload)
                return
        super().keyPressEvent(event)


@dataclass
class TableSpec:
    headers: list[str]
    rows: list[Row] = field(default_factory=list)
    widths: list[int] = field(default_factory=list)
