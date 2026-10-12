"""Compact list of 'needs attention' items inside a card; rows are clickable."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QBrush, QColor, QPixmap
from PySide6.QtWidgets import QLabel, QListWidget, QListWidgetItem, QSizePolicy

from supplier_app.i18n import tr
from supplier_app.services.dashboard_models import AttentionItem
from supplier_app.views.theme import tokens
from supplier_app.views.widgets.common import Card

_TONE = {"critical": "danger", "warn": "warn", "info": "accent"}


class AttentionList(Card):
    item_clicked = Signal(object)  # AttentionItem

    def __init__(self, title: str) -> None:
        super().__init__(title)
        self.list = QListWidget()
        self.list.setWordWrap(True)
        self.list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.list.setMinimumHeight(120)
        self.list.setMaximumHeight(210)
        self.list.setFrameShape(QListWidget.Shape.NoFrame)
        self.list.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.list.itemClicked.connect(self._clicked)
        self.empty = QLabel(tr("dash.attention.empty"))
        self.empty.setObjectName("Muted")
        self.add(self.list)
        self.add(self.empty)

    def set_items(self, items: list[AttentionItem], theme: str) -> None:
        tk = tokens(theme)
        self.list.clear()
        for it in items:
            line2 = it.subtitle
            if it.days_left is not None:
                line2 = f"{tr('dash.attention.days_left', n=it.days_left)} · {line2}"
            li = QListWidgetItem(f"{it.title}\n{line2}" if line2 else it.title)
            pix = QPixmap(10, 28)
            pix.fill(QColor(tk[_TONE.get(it.severity, "accent")]))
            li.setIcon(pix)
            li.setData(Qt.ItemDataRole.UserRole, it)
            li.setForeground(QBrush(QColor(tk["text"])))
            self.list.addItem(li)
        self.list.setVisible(bool(items))
        self.empty.setVisible(not items)

    def _clicked(self, item: QListWidgetItem) -> None:
        self.item_clicked.emit(item.data(Qt.ItemDataRole.UserRole))
