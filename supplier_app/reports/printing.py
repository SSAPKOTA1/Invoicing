"""Printing of a :class:`ReportTable`: HTML layout, paged output with header/footer, preview and PDF through Qt."""

from __future__ import annotations

from datetime import datetime
from html import escape
from pathlib import Path

from PySide6.QtCore import QMarginsF, QRectF, QSizeF, Qt
from PySide6.QtGui import QColor, QFont, QPageLayout, QPageSize, QPainter, QTextDocument
from PySide6.QtPrintSupport import QPrinter

from supplier_app.util.money import format_cents

from .models import ReportTable

APP_NAME = "Lieferantenkonto & Mahnungs-Tracker"
FOOTER_MM = 9.0


def _cell(value: object, right: bool, bold: bool = False, header: bool = False) -> str:
    text = escape("" if value is None else str(value))
    style = "text-align:right;" if right else "text-align:left;"
    if header:
        style += "background-color:#1f2a44;color:#ffffff;font-weight:bold;"
    elif bold:
        style += "font-weight:bold;background-color:#e8ebf2;"
    return f"<td style='{style}padding:3px 5px;'>{text}</td>"


def _table_html(table: ReportTable) -> str:
    head = "".join(_cell(c, i in table.money_columns, header=True) for i, c in enumerate(table.columns))
    body = []
    for row in table.rows:
        body.append("<tr>" + "".join(_cell(v, i in table.money_columns) for i, v in enumerate(row)) + "</tr>")
    if table.totals is not None:
        cells = []
        for i, v in enumerate(table.totals):
            if i == 0 and v is None:
                text = table.totals_label
            elif v is None:
                text = ""
            else:
                text = format_cents(v) if (i in table.money_columns and isinstance(v, int)) else str(v)
            cells.append(_cell(text, i in table.money_columns, bold=True))
        body.append("<tr>" + "".join(cells) + "</tr>")
    return (f"<table width='100%' cellspacing='0' cellpadding='0' border='1' style='border-collapse:collapse;'>"
            f"<thead><tr>{head}</tr></thead><tbody>{''.join(body)}</tbody></table>")


def report_html(table: ReportTable, printed_at: datetime | None = None, font_pt: float = 8.0) -> str:
    """The complete printable page as HTML (title, filter line, table, optional extra tables)."""
    stamp = (printed_at or datetime.now()).strftime("%d.%m.%Y %H:%M")
    parts = [f"<html><body style='font-family:Arial,Helvetica,sans-serif;font-size:{font_pt}pt;'>",
             f"<h2 style='margin:0 0 2px 0;'>{escape(table.title)}</h2>",
             f"<p style='margin:0 0 8px 0;color:#444444;'>{escape(table.subtitle)} &nbsp;·&nbsp; "
             f"Ausdruck vom {stamp} &nbsp;·&nbsp; {len(table.rows)} Zeilen</p>",
             _table_html(table)]
    for extra in table.extra:
        parts.append(f"<h3 style='margin:14px 0 2px 0;'>{escape(extra.title)}</h3>")
        parts.append(f"<p style='margin:0 0 4px 0;color:#444444;'>{escape(extra.subtitle)}</p>")
        parts.append(_table_html(extra))
    parts.append("</body></html>")
    return "".join(parts)


def default_landscape(table: ReportTable) -> bool:
    """Wide tables are printed in landscape format by default."""
    return len(table.columns) > 6


def make_printer(landscape: bool = True) -> QPrinter:
    printer = QPrinter(QPrinter.PrinterMode.HighResolution)
    printer.setPageSize(QPageSize(QPageSize.PageSizeId.A4))
    printer.setPageOrientation(QPageLayout.Orientation.Landscape if landscape else QPageLayout.Orientation.Portrait)
    printer.setPageMargins(QMarginsF(12, 12, 12, 12), QPageLayout.Unit.Millimeter)
    return printer


def render(table: ReportTable, printer: QPrinter) -> int:
    """Paint the report page by page (header row repeats, footer with page numbers). Returns the page count."""
    doc = QTextDocument()
    doc.documentLayout().setPaintDevice(printer)
    doc.setDefaultFont(QFont("Arial"))
    doc.setHtml(report_html(table))
    full = printer.pageRect(QPrinter.Unit.DevicePixel)
    dpmm = printer.resolution() / 25.4
    footer_h = FOOTER_MM * dpmm
    body_h = full.height() - footer_h
    doc.setPageSize(QSizeF(full.width(), body_h))
    pages = max(1, doc.pageCount())
    painter = QPainter()
    if not painter.begin(printer):
        raise OSError("Der Drucker konnte nicht geöffnet werden.")
    try:
        stamp = datetime.now().strftime("%d.%m.%Y %H:%M")
        for page in range(pages):
            if page:
                printer.newPage()
            painter.save()
            painter.translate(0, -page * body_h)
            doc.drawContents(painter, QRectF(0, page * body_h, full.width(), body_h))
            painter.restore()
            painter.save()
            font = QFont("Arial")
            font.setPointSizeF(7.0)
            painter.setFont(font)
            painter.setPen(QColor(100, 100, 100))
            area = QRectF(0, body_h + footer_h * 0.35, full.width(), footer_h * 0.65)
            painter.drawText(area, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, f"{APP_NAME} · {stamp}")
            painter.drawText(area, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, f"Seite {page + 1} von {pages}")
            painter.restore()
    finally:
        painter.end()
    return pages


def print_to_pdf(table: ReportTable, path: Path | str, landscape: bool | None = None) -> int:
    """Render through the same code path as the printer into a PDF file (used for "Als PDF drucken" and tests)."""
    printer = make_printer(default_landscape(table) if landscape is None else landscape)
    printer.setOutputFormat(QPrinter.OutputFormat.PdfFormat)
    printer.setOutputFileName(str(path))
    return render(table, printer)
