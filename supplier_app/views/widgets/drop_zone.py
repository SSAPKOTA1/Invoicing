"""Drag & drop target for several files."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QFrame, QLabel, QVBoxLayout, QWidget

from supplier_app.i18n import tr
from supplier_app.views.theme import repolish


class DropZone(QFrame):
    files_dropped = Signal(list)  # list[Path]

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("DropZone")
        self.setAcceptDrops(True)
        self.setMinimumHeight(74)
        lay = QVBoxLayout(self)
        self.label = QLabel(tr("docs.drop"))
        self.label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.label.setObjectName("Muted")
        lay.addWidget(self.label)

    def _set_active(self, on: bool) -> None:
        self.setProperty("active", on)
        repolish(self)

    def dragEnterEvent(self, event) -> None:  # noqa: N802 - Qt API
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
            self._set_active(True)

    def dragLeaveEvent(self, event) -> None:  # noqa: N802 - Qt API
        self._set_active(False)

    def dropEvent(self, event) -> None:  # noqa: N802 - Qt API
        self._set_active(False)
        paths = [Path(u.toLocalFile()) for u in event.mimeData().urls() if u.isLocalFile()]
        files: list[Path] = []
        for p in paths:
            files.extend(sorted(x for x in p.iterdir() if x.is_file()) if p.is_dir() else [p])
        if files:
            event.acceptProposedAction()
            self.files_dropped.emit(files)
