"""Preview of a stored document: first pages of a PDF / the image / the text file."""

from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import QLabel, QPlainTextEdit, QScrollArea, QStackedWidget, QVBoxLayout, QWidget

from supplier_app.i18n import tr

log = logging.getLogger(__name__)
MAX_TEXT_PREVIEW = 200_000


class DocumentPreview(QWidget):
    """Shows page 1 of a PDF, an image, or a text file; never raises on unreadable files."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.stack = QStackedWidget()
        lay.addWidget(self.stack)
        self.info = QLabel(tr("preview.none"))
        self.info.setObjectName("Muted")
        self.info.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.info.setWordWrap(True)
        self.stack.addWidget(self.info)
        self.image = QLabel()
        self.image.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignHCenter)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setWidget(self.image)
        self.stack.addWidget(self.scroll)
        self.text = QPlainTextEdit()
        self.text.setReadOnly(True)
        self.stack.addWidget(self.text)
        self._pixmap: QPixmap | None = None

    def clear(self, message: str = "") -> None:
        self._pixmap = None
        self.info.setText(message or tr("preview.none"))
        self.stack.setCurrentWidget(self.info)

    def show_file(self, path: Path) -> None:
        path = Path(path)
        if not path.is_file():
            self.clear(tr("preview.missing"))
            return
        try:
            suffix = path.suffix.lower()
            if suffix == ".txt":
                self.text.setPlainText(path.read_text(encoding="utf-8", errors="replace")[:MAX_TEXT_PREVIEW])
                self.stack.setCurrentWidget(self.text)
            elif suffix == ".pdf":
                self._show_pdf(path)
            else:
                pix = QPixmap(str(path))
                if pix.isNull():
                    self.clear(tr("preview.unreadable"))
                    return
                self._set_pixmap(pix)
        except Exception:  # noqa: BLE001 - a broken file must never break the screen
            log.exception("preview failed for %s", path)
            self.clear(tr("preview.unreadable"))

    def _show_pdf(self, path: Path) -> None:
        import pymupdf

        with pymupdf.open(path) as doc:
            if doc.needs_pass or doc.page_count == 0:
                self.clear(tr("preview.unreadable"))
                return
            pix = doc[0].get_pixmap(dpi=110)
            image = QImage(pix.samples, pix.width, pix.height, pix.stride, QImage.Format.Format_RGB888).copy()
        self._set_pixmap(QPixmap.fromImage(image))

    def _set_pixmap(self, pix: QPixmap) -> None:
        self._pixmap = pix
        self._fit()
        self.stack.setCurrentWidget(self.scroll)

    def _fit(self) -> None:
        if self._pixmap is None:
            return
        width = max(200, self.scroll.viewport().width() - 8)
        self.image.setPixmap(self._pixmap.scaledToWidth(width, Qt.TransformationMode.SmoothTransformation))

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt API
        super().resizeEvent(event)
        self._fit()
