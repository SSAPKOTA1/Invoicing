"""CSV / Excel / PDF export of :class:`ReportTable` (numbers are taken from the table's raw values)."""

from __future__ import annotations

import csv
from datetime import date, datetime
from pathlib import Path
from typing import Any

from supplier_app.util.dates import format_date
from supplier_app.util.money import format_cents, to_decimal_euros

from .models import ReportTable


def _csv_value(value: Any, money: bool) -> str:
    if value is None:
        return ""
    if money and isinstance(value, int):
        return format_cents(value, symbol=False)
    if isinstance(value, date):
        return format_date(value)
    return str(value)


def export_csv(table: ReportTable, path: Path) -> Path:
    """Semicolon separated, UTF-8 with BOM, German number format (opens correctly in Excel)."""
    path = Path(path)
    with path.open("w", newline="", encoding="utf-8-sig") as fh:
        w = csv.writer(fh, delimiter=";", quoting=csv.QUOTE_MINIMAL)
        w.writerow([table.title])
        w.writerow([table.subtitle])
        w.writerow(table.columns)
        for raw in table.raw_rows:
            w.writerow([_csv_value(v, i in table.money_columns) for i, v in enumerate(raw)])
        if table.totals is not None:
            w.writerow([table.totals_label if i == 0 and v is None else _csv_value(v, i in table.money_columns)
                        for i, v in enumerate(table.totals)])
    return path


def export_xlsx(table: ReportTable, path: Path) -> Path:
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter

    path = Path(path)
    wb = Workbook()
    ws = wb.active
    ws.title = _sheet_title(table.title)
    header_fill = PatternFill("solid", fgColor="1F2A44")

    def write(sheet, tbl: ReportTable) -> None:
        sheet["A1"] = tbl.title
        sheet["A1"].font = Font(bold=True, size=14)
        sheet["A2"] = tbl.subtitle
        for c, name in enumerate(tbl.columns, start=1):
            cell = sheet.cell(row=4, column=c, value=name)
            cell.font = Font(bold=True, color="FFFFFF")
            cell.fill = header_fill
            cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        r = 5
        for raw in tbl.raw_rows:
            for c, value in enumerate(raw, start=1):
                _write_cell(sheet, r, c, value, (c - 1) in tbl.money_columns)
            r += 1
        if tbl.totals is not None:
            for c, value in enumerate(tbl.totals, start=1):
                label = tbl.totals_label if (c == 1 and value is None) else value
                cell = _write_cell(sheet, r, c, label, (c - 1) in tbl.money_columns)
                cell.font = Font(bold=True)
        for c, name in enumerate(tbl.columns, start=1):
            width = max([len(str(name))] + [len(str(row[c - 1])) for row in tbl.rows[:200]]) + 2
            sheet.column_dimensions[get_column_letter(c)].width = min(max(width, 11), 60)
        sheet.freeze_panes = "A5"

    write(ws, table)
    for extra in table.extra:
        write(wb.create_sheet(_sheet_title(extra.title, used=[w.title for w in wb.worksheets])), extra)
    wb.save(path)
    return path


def _sheet_title(title: str, used: list[str] | None = None) -> str:
    """Excel sheet names: max 31 chars, none of ``[]:*?/\\``, unique within the workbook."""
    import re

    name = re.sub(r"[\[\]:*?/\\]", "-", title).strip("' ")[:28] or "Bericht"
    base, n = name, 2
    while used and name in used:
        name = f"{base[:25]}-{n}"
        n += 1
    return name


def _write_cell(sheet, row: int, col: int, value: Any, money: bool):
    from openpyxl.styles import Alignment

    cell = sheet.cell(row=row, column=col)
    if value is None:
        return cell
    if money and isinstance(value, int):
        cell.value = to_decimal_euros(value)
        cell.number_format = '#,##0.00 "€";[Red]-#,##0.00 "€"'
        cell.alignment = Alignment(horizontal="right")
    elif isinstance(value, date):
        cell.value = value
        cell.number_format = "DD.MM.YYYY"
    else:
        cell.value = value
    return cell


def export_pdf(table: ReportTable, path: Path) -> Path:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    path = Path(path)
    styles = getSampleStyleSheet()
    cell_style = ParagraphStyle("cell", parent=styles["BodyText"], fontSize=7.5, leading=9)
    right_style = ParagraphStyle("cellr", parent=cell_style, alignment=2)
    head_style = ParagraphStyle("head", parent=cell_style, textColor=colors.white, fontName="Helvetica-Bold")
    generated = datetime.now().strftime("%d.%m.%Y %H:%M")

    def footer(canvas, doc) -> None:
        canvas.saveState()
        canvas.setFont("Helvetica", 7.5)
        canvas.setFillGray(0.4)
        canvas.drawString(12 * mm, 8 * mm, f"Lieferantenkonto & Mahnungs-Tracker · erstellt {generated}")
        canvas.drawRightString(landscape(A4)[0] - 12 * mm, 8 * mm, f"Seite {doc.page}")
        canvas.restoreState()

    def build(tbl: ReportTable) -> list:
        flow: list = [Paragraph(tbl.title, styles["Title"]), Paragraph(tbl.subtitle, styles["Normal"]), Spacer(1, 6)]
        data = [[Paragraph(c, head_style) for c in tbl.columns]]
        for row in tbl.rows:
            data.append([Paragraph(str(v).replace("&", "&amp;"), right_style if i in tbl.money_columns else cell_style)
                         for i, v in enumerate(row)])
        if tbl.totals is not None:
            bold = ParagraphStyle("b", parent=cell_style, fontName="Helvetica-Bold")
            boldr = ParagraphStyle("br", parent=bold, alignment=2)
            line = []
            for i, v in enumerate(tbl.totals):
                if i == 0 and v is None:
                    text = tbl.totals_label
                elif v is None:
                    text = ""
                else:
                    text = format_cents(v) if (i in tbl.money_columns and isinstance(v, int)) else str(v)
                line.append(Paragraph(text.replace("&", "&amp;"), boldr if i in tbl.money_columns else bold))
            data.append(line)
        width = landscape(A4)[0] - 24 * mm
        t = Table(data, repeatRows=1, colWidths=[width / len(tbl.columns)] * len(tbl.columns))
        style = [("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1F2A44")), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                 ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#c9d0de")),
                 ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f2f5fa")])]
        if tbl.totals is not None:
            style += [("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#dfe6f3")), ("LINEABOVE", (0, -1), (-1, -1), 0.8, colors.black)]
        t.setStyle(TableStyle(style))
        flow.append(t)
        return flow

    story = build(table)
    for extra in table.extra:
        story += [PageBreak(), *build(extra)]
    doc = SimpleDocTemplate(str(path), pagesize=landscape(A4), leftMargin=12 * mm, rightMargin=12 * mm,
                            topMargin=12 * mm, bottomMargin=14 * mm, title=table.title, author="SupplierApp")
    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    return path


EXPORTERS = {"csv": export_csv, "xlsx": export_xlsx, "pdf": export_pdf}
