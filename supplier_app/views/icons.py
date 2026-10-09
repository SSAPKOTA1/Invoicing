"""Vector icons drawn with QPainter (no image assets needed)."""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap

SIZE = 64


def _pen(color: QColor, width: float = 5.0) -> QPen:
    pen = QPen(color, width)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    return pen


def _draw(name: str, p: QPainter, color: QColor) -> None:
    p.setPen(_pen(color))
    p.setBrush(Qt.BrushStyle.NoBrush)
    if name == "dashboard":
        for x, y in ((10, 10), (36, 10), (10, 36), (36, 36)):
            p.drawRoundedRect(QRectF(x, y, 18, 18), 4, 4)
    elif name == "suppliers":
        p.drawEllipse(QRectF(20, 8, 24, 24))
        path = QPainterPath(QPointF(10, 56))
        path.cubicTo(10, 36, 54, 36, 54, 56)
        p.drawPath(path)
    elif name == "cases":
        p.drawRoundedRect(QRectF(8, 18, 48, 36), 5, 5)
        p.drawLine(QPointF(8, 28), QPointF(56, 28))
        p.drawLine(QPointF(14, 10), QPointF(30, 10))
        p.drawLine(QPointF(14, 10), QPointF(14, 18))
        p.drawLine(QPointF(30, 10), QPointF(34, 18))
    elif name == "documents":
        path = QPainterPath(QPointF(14, 6))
        for pt in ((38, 6), (50, 18), (50, 58), (14, 58)):
            path.lineTo(QPointF(*pt))
        path.closeSubpath()
        p.drawPath(path)
        for y in (30, 40, 50):
            p.drawLine(QPointF(22, y), QPointF(42, y))
    elif name == "transactions":
        for y in (16, 32, 48):
            p.drawLine(QPointF(8, y), QPointF(14, y))
            p.drawLine(QPointF(22, y), QPointF(56, y))
    elif name == "reports":
        p.drawLine(QPointF(8, 8), QPointF(8, 56))
        p.drawLine(QPointF(8, 56), QPointF(58, 56))
        for x, h in ((18, 18), (32, 30), (46, 40)):
            p.drawRect(QRectF(x, 56 - h, 8, h))
    elif name == "settings":
        p.drawEllipse(QRectF(22, 22, 20, 20))
        for dx, dy in ((0, -22), (0, 22), (22, 0), (-22, 0)):
            p.drawLine(QPointF(32 + dx * 0.55, 32 + dy * 0.55), QPointF(32 + dx * 0.95, 32 + dy * 0.95))
    elif name == "search":
        p.drawEllipse(QRectF(10, 10, 32, 32))
        p.drawLine(QPointF(38, 38), QPointF(54, 54))
    elif name == "lock":
        p.drawRoundedRect(QRectF(14, 28, 36, 28), 5, 5)
        path = QPainterPath(QPointF(22, 28))
        path.lineTo(22, 20)
        path.cubicTo(22, 6, 42, 6, 42, 20)
        path.lineTo(42, 28)
        p.drawPath(path)
    elif name == "theme":
        p.drawEllipse(QRectF(16, 16, 32, 32))
        p.setBrush(color)
        path = QPainterPath()
        path.moveTo(32, 16)
        path.arcTo(QRectF(16, 16, 32, 32), 90, 180)
        path.closeSubpath()
        p.drawPath(path)
    elif name == "refresh":
        path = QPainterPath()
        path.arcMoveTo(QRectF(12, 12, 40, 40), 40)
        path.arcTo(QRectF(12, 12, 40, 40), 40, 280)
        p.drawPath(path)
        p.drawLine(QPointF(44, 8), QPointF(48, 20))
        p.drawLine(QPointF(48, 20), QPointF(36, 20))
    else:
        p.drawEllipse(QRectF(14, 14, 36, 36))


def make_icon(name: str, color: str | QColor = "#ffffff") -> QIcon:
    pixmap = QPixmap(SIZE, SIZE)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    _draw(name, painter, QColor(color))
    painter.end()
    return QIcon(pixmap)
