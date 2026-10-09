"""Header search: debounced live results, grouped by Suppliers / Invoices / Cases / Documents."""

from __future__ import annotations

from PySide6.QtCore import QEvent, QObject, Qt, QTimer, Signal
from PySide6.QtWidgets import QFrame, QLabel, QLineEdit, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget

from supplier_app.errors import SupplierAppError
from supplier_app.i18n import tr
from supplier_app.services.search_service import SearchHit, SearchResults, SearchService


class SearchPopup(QFrame):
    """Result list shown below the search box; ``hit_chosen`` fires with a :class:`SearchHit`."""

    hit_chosen = Signal(object)

    def __init__(self, parent: QWidget, search: SearchService, box: QLineEdit) -> None:
        super().__init__(parent)
        self.search_service = search
        self.box = box
        self.setObjectName("Card")
        self.setVisible(False)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 8, 8, 8)
        self.info = QLabel()
        self.info.setObjectName("Muted")
        lay.addWidget(self.info)
        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setRootIsDecorated(False)
        self.tree.setIndentation(14)
        self.tree.setFrameShape(QFrame.Shape.NoFrame)
        self.tree.itemClicked.connect(self._chosen)
        lay.addWidget(self.tree)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(220)
        self._timer.timeout.connect(self.run_search)
        box.textChanged.connect(lambda _t: self._timer.start())
        box.installEventFilter(self)
        self.results: SearchResults | None = None

    def run_search(self) -> None:
        text = self.box.text().strip()
        if not text:
            self.hide()
            return
        try:
            self.results = self.search_service.search(text)
        except SupplierAppError as exc:
            self.results = None
            self.info.setText(exc.message)
            self.tree.clear()
            self._place()
            return
        self._fill(self.results)
        self._place()

    def _fill(self, res: SearchResults) -> None:
        self.tree.clear()
        groups = ((tr("search.group.suppliers"), res.suppliers), (tr("search.group.invoices"), res.invoices),
                  (tr("search.group.cases"), res.cases), (tr("search.group.documents"), res.documents))
        for title, hits in groups:
            if not hits:
                continue
            parent = QTreeWidgetItem([f"{title} ({len(hits)})"])
            parent.setFlags(Qt.ItemFlag.ItemIsEnabled)
            font = parent.font(0)
            font.setBold(True)
            parent.setFont(0, font)
            self.tree.addTopLevelItem(parent)
            for h in hits[:12]:
                text = f"{h.title}\n{h.subtitle} · {h.reason}" + (f"\n{h.snippet}" if h.snippet else "")
                child = QTreeWidgetItem([text])
                child.setData(0, Qt.ItemDataRole.UserRole, h)
                parent.addChild(child)
            parent.setExpanded(True)
        self.info.setText(tr("search.count", n=res.total) if res.total else tr("search.none"))

    def _place(self) -> None:
        host = self.parentWidget()
        pos = self.box.mapTo(host, self.box.rect().bottomLeft())
        width = max(560, self.box.width())
        self.setGeometry(pos.x(), pos.y() + 6, width, min(host.height() - pos.y() - 40, 520))
        self.show()
        self.raise_()

    def _chosen(self, item: QTreeWidgetItem) -> None:
        hit = item.data(0, Qt.ItemDataRole.UserRole)
        if isinstance(hit, SearchHit):
            self.hide()
            self.hit_chosen.emit(hit)

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:  # noqa: N802 - Qt API
        if obj is self.box and event.type() == QEvent.Type.KeyPress and self.isVisible():
            key = event.key()
            if key == Qt.Key.Key_Escape:
                self.hide()
                return True
            if key in (Qt.Key.Key_Down, Qt.Key.Key_Up):
                self._move(1 if key == Qt.Key.Key_Down else -1)
                return True
            if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and self.tree.currentItem():
                self._chosen(self.tree.currentItem())
                return True
        if obj is self.box and event.type() == QEvent.Type.KeyPress and event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.run_search()
            return True
        return False

    def _move(self, step: int) -> None:
        leaves = [self.tree.topLevelItem(i).child(j) for i in range(self.tree.topLevelItemCount())
                  for j in range(self.tree.topLevelItem(i).childCount())]
        if not leaves:
            return
        cur = self.tree.currentItem()
        idx = leaves.index(cur) if cur in leaves else -1
        self.tree.setCurrentItem(leaves[(idx + step) % len(leaves)])
