"""Generate dark.qss / light.qss from one template so both themes stay in sync.

Run:  python scripts/make_themes.py
"""

from __future__ import annotations

from pathlib import Path

from supplier_app.views.theme_tokens import TOKENS

TEMPLATE = """
* { font-family: "Segoe UI", "Inter", "Noto Sans", "DejaVu Sans", sans-serif; font-size: 10pt; }
QWidget { background: %(bg)s; color: %(text)s; }
QMainWindow, QDialog { background: %(bg)s; }
QLabel { background: transparent; }
QToolTip { background: %(surface3)s; color: %(text)s; border: 1px solid %(border)s; padding: 4px 6px; }

#Sidebar { background: %(sidebar)s; border: none; }
#Sidebar QLabel { background: transparent; color: %(sidebar_text)s; }
#Sidebar #AppTitle { color: #ffffff; font-size: 12pt; font-weight: 700; padding: 0 4px; }
#Sidebar QPushButton { background: transparent; color: %(sidebar_text)s; text-align: left; padding: 10px 14px;
    border: none; border-radius: 8px; font-size: 10.5pt; }
#Sidebar QPushButton:hover { background: %(sidebar_active)s; color: #ffffff; }
#Sidebar QPushButton:checked { background: %(accent)s; color: %(accent_text)s; font-weight: 600; }
#Header { background: %(surface)s; border-bottom: 1px solid %(border)s; }
#Header QLineEdit { min-width: 340px; padding: 8px 12px; border-radius: 18px; }

QFrame#Card, QWidget#Card { background: %(surface)s; border: 1px solid %(border)s; border-radius: 10px; }
QFrame#Card QLabel, QWidget#Card QLabel { background: transparent; }
QFrame#KpiCard { background: %(surface)s; border: 1px solid %(border)s; border-radius: 10px; }
QFrame#KpiCard:hover { border-color: %(accent)s; background: %(surface2)s; }
QFrame#KpiCard QLabel { background: transparent; }
QLabel#KpiTitle { color: %(muted)s; font-size: 9pt; }
QLabel#KpiValue { font-size: 18pt; font-weight: 700; }
QLabel#KpiDelta { font-size: 9pt; color: %(muted)s; }
QLabel#KpiDelta[tone="good"] { color: %(ok)s; }
QLabel#KpiDelta[tone="bad"] { color: %(danger)s; }
QLabel#SectionTitle { font-size: 11pt; font-weight: 600; }
QLabel#PageTitle { font-size: 16pt; font-weight: 700; }
QLabel#Muted, QLabel[muted="true"] { color: %(muted)s; }
QLabel#Badge { padding: 2px 10px; border-radius: 10px; background: %(surface3)s; font-size: 9pt; font-weight: 600; }
QLabel#Badge[tone="ok"] { background: %(ok_bg)s; color: %(ok)s; }
QLabel#Badge[tone="warn"] { background: %(warn_bg)s; color: %(warn)s; }
QLabel#Badge[tone="bad"] { background: %(danger_bg)s; color: %(danger)s; }
QLabel#Warning { background: %(warn_bg)s; color: %(warn)s; border-radius: 6px; padding: 6px 10px; }
QLabel#Danger { background: %(danger_bg)s; color: %(danger)s; border-radius: 6px; padding: 6px 10px; }
QLabel#EmptyTitle { font-size: 15pt; font-weight: 700; }

QPushButton { background: %(surface2)s; border: 1px solid %(border)s; border-radius: 7px; padding: 7px 14px; }
QPushButton:hover { background: %(surface3)s; }
QPushButton:pressed { background: %(border)s; }
QPushButton:disabled { color: %(muted)s; background: %(surface)s; }
QPushButton[kind="primary"] { background: %(accent)s; color: %(accent_text)s; border: 1px solid %(accent)s; font-weight: 600; }
QPushButton[kind="primary"]:hover { background: %(accent_hover)s; }
QPushButton[kind="danger"] { color: %(danger)s; }
QPushButton[kind="flat"] { background: transparent; border: none; color: %(accent)s; padding: 4px 8px; }
QPushButton[kind="flat"]:hover { background: %(surface2)s; }
QToolButton { background: transparent; border: none; padding: 6px; border-radius: 6px; }
QToolButton:hover { background: %(surface3)s; }

QLineEdit, QTextEdit, QPlainTextEdit, QComboBox, QDateEdit, QSpinBox, QDoubleSpinBox {
    background: %(surface)s; border: 1px solid %(border)s; border-radius: 7px; padding: 6px 8px;
    selection-background-color: %(selection)s; selection-color: %(text)s; }
QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus, QComboBox:focus, QDateEdit:focus, QSpinBox:focus {
    border: 1px solid %(accent)s; }
QLineEdit:disabled, QComboBox:disabled, QDateEdit:disabled { color: %(muted)s; background: %(surface2)s; }
QLineEdit[lowConfidence="true"], QComboBox[lowConfidence="true"], QDateEdit[lowConfidence="true"] {
    border: 1px solid %(warn)s; background: %(warn_bg)s; }
QLineEdit[invalid="true"] { border: 1px solid %(danger)s; }
QComboBox::drop-down { border: none; width: 22px; }
QComboBox QAbstractItemView { background: %(surface)s; border: 1px solid %(border)s; selection-background-color: %(selection)s; }
QCheckBox, QRadioButton { spacing: 8px; background: transparent; }
QCheckBox::indicator, QRadioButton::indicator { width: 16px; height: 16px; border: 1px solid %(border)s; border-radius: 4px;
    background: %(surface)s; }
QRadioButton::indicator { border-radius: 9px; }
QCheckBox::indicator:checked, QRadioButton::indicator:checked { background: %(accent)s; border-color: %(accent)s; }

QTableView, QTreeView, QListView, QListWidget { background: %(surface)s; alternate-background-color: %(surface2)s;
    border: 1px solid %(border)s; border-radius: 8px; gridline-color: %(border)s;
    selection-background-color: %(selection)s; selection-color: %(text)s; outline: 0; }
QTableView::item, QTreeView::item { padding: 4px 6px; }
QListWidget::item { padding: 6px 8px; border-radius: 6px; }
QListWidget::item:hover { background: %(surface2)s; }
QHeaderView::section { background: %(surface2)s; color: %(muted)s; border: none; border-bottom: 1px solid %(border)s;
    padding: 7px 8px; font-weight: 600; }
QTableCornerButton::section { background: %(surface2)s; border: none; }
QScrollArea { border: none; background: transparent; }
QScrollBar:vertical { background: transparent; width: 11px; margin: 0; }
QScrollBar::handle:vertical { background: %(surface3)s; border-radius: 5px; min-height: 28px; }
QScrollBar::handle:vertical:hover { background: %(muted)s; }
QScrollBar:horizontal { background: transparent; height: 11px; margin: 0; }
QScrollBar::handle:horizontal { background: %(surface3)s; border-radius: 5px; min-width: 28px; }
QScrollBar::add-line, QScrollBar::sub-line { width: 0; height: 0; }

QTabWidget::pane { border: 1px solid %(border)s; border-radius: 8px; top: -1px; background: %(surface)s; }
QTabBar::tab { background: transparent; padding: 8px 16px; margin-right: 2px; color: %(muted)s; border-bottom: 2px solid transparent; }
QTabBar::tab:selected { color: %(text)s; border-bottom: 2px solid %(accent)s; font-weight: 600; }
QTabBar::tab:hover { color: %(text)s; }
QGroupBox { border: 1px solid %(border)s; border-radius: 8px; margin-top: 14px; padding: 12px 8px 8px 8px; background: transparent; }
QGroupBox::title { subcontrol-origin: margin; left: 12px; padding: 0 6px; color: %(muted)s; font-weight: 600; }
QSplitter::handle { background: %(border)s; }
QSplitter::handle:horizontal { width: 3px; }
QSplitter::handle:vertical { height: 3px; }
QMenu { background: %(surface)s; border: 1px solid %(border)s; padding: 4px; }
QMenu::item { padding: 7px 22px; border-radius: 5px; }
QMenu::item:selected { background: %(selection)s; }
QProgressBar { border: 1px solid %(border)s; border-radius: 6px; text-align: center; background: %(surface2)s; height: 16px; }
QProgressBar::chunk { background: %(accent)s; border-radius: 5px; }
QStatusBar { background: %(surface)s; border-top: 1px solid %(border)s; color: %(muted)s; }
QStatusBar QLabel { color: %(muted)s; }
QFrame#DropZone { border: 2px dashed %(border)s; border-radius: 10px; background: %(surface)s; }
QFrame#DropZone[active="true"] { border-color: %(accent)s; background: %(surface2)s; }
QFrame[frameShape="4"], QFrame[frameShape="5"] { color: %(border)s; }
"""


def main() -> None:
    out = Path(__file__).resolve().parents[1] / "supplier_app" / "views" / "themes"
    out.mkdir(parents=True, exist_ok=True)
    for name, tokens in TOKENS.items():
        (out / f"{name}.qss").write_text(f"/* generated by scripts/make_themes.py - {name} */" + TEMPLATE % tokens, encoding="utf-8")
        print("written", out / f"{name}.qss")


if __name__ == "__main__":
    main()
