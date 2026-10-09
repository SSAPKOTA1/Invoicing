"""QtCharts helpers: themed bar / horizontal bar / trend / donut charts with click callbacks."""

from __future__ import annotations

from collections.abc import Callable, Sequence

from PySide6.QtCharts import (
    QBarCategoryAxis,
    QBarSeries,
    QBarSet,
    QChart,
    QChartView,
    QHorizontalBarSeries,
    QLineSeries,
    QPieSeries,
    QValueAxis,
)
from PySide6.QtCore import QMargins, Qt
from PySide6.QtGui import QBrush, QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QSizePolicy, QToolTip

from supplier_app.util.money import format_cents
from supplier_app.views.theme import tokens

PALETTE = ["#5b93ff", "#3ecf8e", "#f5b04c", "#ff6b6b", "#b48cff", "#4fd1d9", "#ff8fb1"]
LEVEL_COLORS = ["#8fb4ff", "#5b93ff", "#f5b04c", "#ff9a52", "#ff6b6b", "#c23b4b"]
AGING_COLORS = ["#3ecf8e", "#9bd36a", "#f5b04c", "#ff9a52", "#ff6b6b"]


def euros(cents: int) -> int:
    """Whole euros for chart axes (display only)."""
    return int(round(cents / 100))


def _style_chart(chart: QChart, theme: str, legend: bool) -> None:
    tk = tokens(theme)
    chart.setBackgroundVisible(False)
    chart.setPlotAreaBackgroundVisible(False)
    chart.setMargins(QMargins(4, 4, 4, 4))
    chart.layout().setContentsMargins(0, 0, 0, 0)
    chart.setAnimationOptions(QChart.AnimationOption.NoAnimation)
    chart.legend().setVisible(legend)
    chart.legend().setLabelColor(QColor(tk["muted"]))
    chart.legend().setAlignment(Qt.AlignmentFlag.AlignBottom)
    font = QFont("Segoe UI", 9)
    chart.setFont(font)


def _style_axis(axis, theme: str, grid: bool = True) -> None:
    tk = tokens(theme)
    axis.setLabelsColor(QColor(tk["muted"]))
    axis.setLinePen(QPen(QColor(tk["border"])))
    axis.setGridLinePen(QPen(QColor(tk["border"]), 0.6))
    axis.setGridLineVisible(grid)
    axis.setLabelsFont(QFont("Segoe UI", 8))


def make_view(chart: QChart, min_height: int = 240) -> QChartView:
    view = QChartView(chart)
    view.setRenderHint(QPainter.RenderHint.Antialiasing)
    view.setMinimumHeight(min_height)
    view.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
    view.setStyleSheet("background: transparent; border: none;")
    view.setBackgroundBrush(QBrush(Qt.GlobalColor.transparent))
    return view


def _money_axis(chart: QChart, series, horizontal: bool, theme: str, max_value: int) -> QValueAxis:
    axis = QValueAxis()
    axis.setLabelFormat("%.0f")
    axis.setRange(min(0, 0), max(10, int(max_value * 1.12) or 10))
    axis.setTickCount(5)
    _style_axis(axis, theme)
    chart.addAxis(axis, Qt.AlignmentFlag.AlignBottom if horizontal else Qt.AlignmentFlag.AlignLeft)
    series.attachAxis(axis)
    return axis


def bar_chart(
    categories: Sequence[str], values_cents: Sequence[int], colors: Sequence[str], theme: str,
    on_click: Callable[[int], None] | None = None, horizontal: bool = False, series_name: str = "",
) -> QChartView:
    """One bar per category, individually colored; hover tooltip shows the formatted amount."""
    chart = QChart()
    if horizontal:  # first entry on top
        categories, values_cents = list(reversed(categories)), list(reversed(values_cents))
    series = QHorizontalBarSeries() if horizontal else QBarSeries()
    series.setBarWidth(0.7)
    sets: list[QBarSet] = []
    for i, (cat, cents) in enumerate(zip(categories, values_cents, strict=False)):
        bar = QBarSet(cat)
        row = [0.0] * len(categories)
        row[i] = float(euros(cents))
        bar.append(row)
        bar.setColor(QColor(colors[i % len(colors)]))
        bar.setBorderColor(QColor(colors[i % len(colors)]))
        if on_click:
            bar.clicked.connect(lambda _idx, n=i: on_click(len(categories) - 1 - n if horizontal else n))
        series.append(bar)
        sets.append(bar)
    series.hovered.connect(lambda state, idx, barset: _hover(state, categories, values_cents, barset, sets))
    chart.addSeries(series)
    cat_axis = QBarCategoryAxis()
    cat_axis.append(list(categories))
    _style_axis(cat_axis, theme, grid=False)
    if horizontal:
        chart.addAxis(cat_axis, Qt.AlignmentFlag.AlignLeft)
    else:
        chart.addAxis(cat_axis, Qt.AlignmentFlag.AlignBottom)
    series.attachAxis(cat_axis)
    _money_axis(chart, series, horizontal, theme, max((euros(v) for v in values_cents), default=0))
    _style_chart(chart, theme, legend=False)
    view = make_view(chart)
    view.setToolTip(series_name)
    return view


def _hover(state: bool, categories, values_cents, barset: QBarSet, sets: list[QBarSet]) -> None:
    if state and barset in sets:
        i = sets.index(barset)
        QToolTip.showText(_cursor_pos(), f"{categories[i]}: {format_cents(values_cents[i])}")


def _cursor_pos():
    from PySide6.QtGui import QCursor
    return QCursor.pos()


def trend_chart(months: Sequence[str], invoiced: Sequence[int], paid: Sequence[int], balance: Sequence[int],
                theme: str, names: tuple[str, str, str] = ("Rechnungen", "Zahlungen", "Saldo")) -> QChartView:
    chart = QChart()
    bars = QBarSeries()
    inv_set, paid_set = QBarSet(names[0]), QBarSet(names[1])
    inv_set.append([float(euros(v)) for v in invoiced])
    paid_set.append([float(euros(v)) for v in paid])
    inv_set.setColor(QColor(PALETTE[0]))
    paid_set.setColor(QColor(PALETTE[1]))
    bars.append(inv_set)
    bars.append(paid_set)
    chart.addSeries(bars)
    line = QLineSeries()
    line.setName(names[2])
    pen = QPen(QColor(PALETTE[2]), 2.4)
    line.setPen(pen)
    for i, v in enumerate(balance):
        line.append(float(i), float(euros(v)))
    chart.addSeries(line)
    cat = QBarCategoryAxis()
    cat.append([m[2:] if len(m) == 7 else m for m in months])
    _style_axis(cat, theme, grid=False)
    chart.addAxis(cat, Qt.AlignmentFlag.AlignBottom)
    bars.attachAxis(cat)
    top = max([euros(v) for v in (*invoiced, *paid, *balance)] or [0])
    low = min([euros(v) for v in balance] or [0])
    val = QValueAxis()
    val.setLabelFormat("%.0f")
    val.setRange(min(0, low * 1.1), max(10, top * 1.12))
    val.setTickCount(5)
    _style_axis(val, theme)
    chart.addAxis(val, Qt.AlignmentFlag.AlignLeft)
    bars.attachAxis(val)
    line.attachAxis(val)
    x_axis = QValueAxis()
    x_axis.setRange(-0.5, len(months) - 0.5)
    x_axis.setVisible(False)
    chart.addAxis(x_axis, Qt.AlignmentFlag.AlignBottom)
    line.attachAxis(x_axis)
    _style_chart(chart, theme, legend=True)
    return make_view(chart, 260)


def donut_chart(labels: Sequence[str], values: Sequence[int], colors: Sequence[str], theme: str,
                on_click: Callable[[int], None] | None = None, money: bool = False) -> QChartView:
    chart = QChart()
    series = QPieSeries()
    series.setHoleSize(0.5)
    total = sum(values)
    for i, (label, value) in enumerate(zip(labels, values, strict=False)):
        shown = format_cents(value) if money else str(value)
        sl = series.append(f"{label}: {shown}", float(max(value, 0)))
        sl.setColor(QColor(colors[i % len(colors)]))
        sl.setBorderColor(QColor(tokens(theme)["surface"]))
        if on_click:
            sl.clicked.connect(lambda n=i: on_click(n))
    if total == 0:
        sl = series.append("keine Daten", 1.0)
        sl.setColor(QColor(tokens(theme)["surface3"]))
    chart.addSeries(series)
    _style_chart(chart, theme, legend=True)
    chart.legend().setAlignment(Qt.AlignmentFlag.AlignRight)
    return make_view(chart)
