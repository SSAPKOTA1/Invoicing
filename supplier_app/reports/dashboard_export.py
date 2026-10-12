"""Dashboard export as PNG or multi-page PDF (rendered from the live widget)."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QMarginsF, QRectF
from PySide6.QtGui import QPageLayout, QPageSize, QPainter, QPdfWriter
from PySide6.QtWidgets import QWidget


def export_png(widget: QWidget, path: Path) -> Path:
    path = Path(path)
    if not widget.grab().save(str(path), "PNG"):
        raise OSError(f"PNG konnte nicht geschrieben werden: {path}")
    return path


def export_pdf(widget: QWidget, path: Path, title: str = "Übersicht") -> Path:
    """Render the widget scaled to the width of an A4 landscape page, split over as many pages as needed."""
    path = Path(path)
    pixmap = widget.grab()
    writer = QPdfWriter(str(path))
    writer.setPageSize(QPageSize(QPageSize.PageSizeId.A4))
    writer.setPageOrientation(QPageLayout.Orientation.Landscape)
    writer.setPageMargins(QMarginsF(10, 10, 10, 10), QPageLayout.Unit.Millimeter)
    writer.setTitle(title)
    painter = QPainter(writer)
    try:
        page_w, page_h = writer.width(), writer.height()
        scale = page_w / pixmap.width()
        slice_h = int(page_h / scale)
        y = 0
        first = True
        while y < pixmap.height():
            if not first:
                writer.newPage()
            part = pixmap.copy(0, y, pixmap.width(), min(slice_h, pixmap.height() - y))
            painter.drawPixmap(QRectF(0, 0, page_w, part.height() * scale), part, QRectF(part.rect()))
            y += slice_h
            first = False
    finally:
        painter.end()
    if not path.exists() or path.stat().st_size == 0:
        raise OSError(f"PDF konnte nicht geschrieben werden: {path}")
    return path
