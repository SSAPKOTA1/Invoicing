"""Main window: sidebar navigation, header with global search, page stack, status bar, shortcuts."""

from __future__ import annotations

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (
    QButtonGroup,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QPushButton,
    QStackedWidget,
    QStatusBar,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from supplier_app.controllers.app_controller import AppController
from supplier_app.i18n import tr
from supplier_app.services.dashboard_models import DashboardFilter, DrillTarget
from supplier_app.services.search_service import SearchHit
from supplier_app.views.dialogs.drill_dialog import DrillDialog
from supplier_app.views.dialogs.history_dialog import InvoiceHistoryDialog
from supplier_app.views.dialogs.payment_dialog import PaymentDialog
from supplier_app.views.dialogs.pin_dialog import UnlockDialog
from supplier_app.views.dialogs.supplier_dialog import SupplierDialog
from supplier_app.views.icons import make_icon
from supplier_app.views.pages.base import Page
from supplier_app.views.pages.cases import CasesPage
from supplier_app.views.pages.dashboard import DashboardPage
from supplier_app.views.pages.documents import DocumentsPage
from supplier_app.views.pages.reports import ReportsPage
from supplier_app.views.pages.settings import SettingsPage
from supplier_app.views.pages.suppliers import SuppliersPage
from supplier_app.views.pages.transactions import TransactionsPage
from supplier_app.views.search_popup import SearchPopup
from supplier_app.views.theme import tokens

PAGES = [DashboardPage, SuppliersPage, CasesPage, DocumentsPage, TransactionsPage, ReportsPage, SettingsPage]


class MainWindow(QMainWindow):
    def __init__(self, ctrl: AppController) -> None:
        super().__init__()
        self.ctrl = ctrl
        self.setWindowTitle(tr("app.title"))
        self.setMinimumSize(1280, 720)
        self.resize(1480, 880)
        self._dirty: set[str] = set()
        self._history_dialogs: list[InvoiceHistoryDialog] = []
        central = QWidget()
        self.setCentralWidget(central)
        outer = QHBoxLayout(central)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        outer.addWidget(self._build_sidebar())
        right = QWidget()
        r_lay = QVBoxLayout(right)
        r_lay.setContentsMargins(0, 0, 0, 0)
        r_lay.setSpacing(0)
        r_lay.addWidget(self._build_header())
        self.stack = QStackedWidget()
        r_lay.addWidget(self.stack, 1)
        outer.addWidget(right, 1)
        self.pages: dict[str, Page] = {}
        for cls in PAGES:
            page = cls(ctrl)
            self.pages[page.key] = page
            self.stack.addWidget(page)
        self.setStatusBar(QStatusBar())
        self.search_popup = SearchPopup(central, ctrl.ctx.services.search, self.search_box)
        self.search_popup.hit_chosen.connect(self._open_hit)
        self._connect()
        self._shortcuts()
        self.show_page("dashboard")
        self.apply_theme_icons()

    # -- construction ---------------------------------------------------------------------------------------------
    def _build_sidebar(self) -> QWidget:
        side = QWidget()
        side.setObjectName("Sidebar")
        side.setFixedWidth(220)
        lay = QVBoxLayout(side)
        lay.setContentsMargins(12, 16, 12, 12)
        lay.setSpacing(4)
        title = QLabel(tr("app.short"))
        title.setObjectName("AppTitle")
        lay.addWidget(title)
        lay.addSpacing(14)
        self.nav_group = QButtonGroup(self)
        self.nav_buttons: dict[str, QPushButton] = {}
        for cls in PAGES:
            btn = QPushButton(" " + tr(cls.title))
            btn.setCheckable(True)
            btn.setIconSize(QSize(20, 20))
            btn.clicked.connect(lambda _c=False, k=cls.key: self.show_page(k))
            self.nav_group.addButton(btn)
            self.nav_buttons[cls.key] = btn
            lay.addWidget(btn)
        lay.addStretch(1)
        version = QLabel(tr("app.version"))
        version.setObjectName("Muted")
        lay.addWidget(version)
        return side

    def _build_header(self) -> QWidget:
        header = QWidget()
        header.setObjectName("Header")
        header.setFixedHeight(58)
        lay = QHBoxLayout(header)
        lay.setContentsMargins(20, 8, 20, 8)
        self.search_box = QLineEdit()
        self.search_box.setPlaceholderText(tr("search.placeholder"))
        self.search_box.setClearButtonEnabled(True)
        lay.addWidget(self.search_box)
        lay.addStretch(1)
        self.btn_import = QPushButton(tr("action.import"))
        self.btn_import.setProperty("kind", "primary")
        self.btn_import.clicked.connect(self.start_import)
        lay.addWidget(self.btn_import)
        self.btn_theme = QToolButton()
        self.btn_theme.setToolTip(tr("action.theme"))
        self.btn_theme.clicked.connect(self.ctrl.toggle_theme)
        self.btn_lock = QToolButton()
        self.btn_lock.setToolTip(tr("action.lock"))
        self.btn_lock.clicked.connect(self.lock)
        for b in (self.btn_theme, self.btn_lock):
            b.setIconSize(QSize(22, 22))
            lay.addWidget(b)
        return header

    def apply_theme_icons(self) -> None:
        tk = tokens(self.ctrl.theme)
        for key, btn in self.nav_buttons.items():
            btn.setIcon(make_icon(key, tk["sidebar_text"] if not btn.isChecked() else tk["accent_text"]))
        self.btn_theme.setIcon(make_icon("theme", tk["muted"]))
        self.btn_lock.setIcon(make_icon("lock", tk["muted"]))
        self.btn_lock.setVisible(self.ctrl.ctx.services.pin.enabled)

    def _connect(self) -> None:
        c = self.ctrl
        c.data_changed.connect(self._data_changed)
        c.theme_changed.connect(self._theme_changed)
        c.navigate.connect(self.show_page)
        c.open_invoice.connect(self.show_invoice)
        c.open_supplier.connect(self.show_supplier)
        c.open_document.connect(self.show_document)
        c.open_case.connect(self.show_case)
        c.drill.connect(self.show_drill)
        c.focus_search.connect(self.focus_search)
        c.import_requested.connect(self.start_import)
        c.payment_requested.connect(self.new_payment)
        c.supplier_requested.connect(self.new_supplier)
        c.lock_requested.connect(self.lock)
        c.status.connect(lambda msg: self.statusBar().showMessage(msg, 8000))
        self.nav_group.buttonToggled.connect(lambda *_: self.apply_theme_icons())

    def _shortcuts(self) -> None:
        def add(seq: str, slot) -> None:
            act = QAction(self)
            act.setShortcut(QKeySequence(seq))
            act.triggered.connect(slot)
            self.addAction(act)

        add("Ctrl+K", self.focus_search)
        add("Ctrl+F", self.focus_search)
        add("Ctrl+I", self.start_import)
        add("Ctrl+P", lambda: self.new_payment(None))
        add("Ctrl+N", self.new_supplier)
        add("Ctrl+T", self.ctrl.toggle_theme)
        add("Ctrl+L", self.lock)
        add("F5", self.refresh_current)
        for i, cls in enumerate(PAGES, start=1):
            add(f"Ctrl+{i}", lambda k=cls.key: self.show_page(k))

    # -- navigation --------------------------------------------------------------------------------------------------
    def show_page(self, key: str) -> None:
        page = self.pages[key]
        self.stack.setCurrentWidget(page)
        self.nav_buttons[key].setChecked(True)
        page.refresh()
        self._dirty.discard(key)
        self.apply_theme_icons()

    def current_key(self) -> str:
        return self.stack.currentWidget().key  # type: ignore[attr-defined]

    def refresh_current(self) -> None:
        self.show_page(self.current_key())

    def _data_changed(self) -> None:
        current = self.current_key()
        self._dirty = {k for k in self.pages if k != current}
        self.pages[current].refresh()
        self.btn_lock.setVisible(self.ctrl.ctx.services.pin.enabled)
        self.ctrl.restart_idle_timer()

    def _theme_changed(self, _theme: str) -> None:
        self.apply_theme_icons()
        self.pages[self.current_key()].on_theme_changed(self.ctrl.theme)
        self.search_popup.hide()

    def show_invoice(self, invoice_id: int) -> None:
        dlg = InvoiceHistoryDialog(self.ctrl, invoice_id, self)
        dlg.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        dlg.show()
        dlg.raise_()
        self._history_dialogs = [d for d in self._history_dialogs if d.isVisible()] + [dlg]

    def show_supplier(self, supplier_id: int) -> None:
        self.show_page("suppliers")
        self.pages["suppliers"].select_supplier(supplier_id)  # type: ignore[attr-defined]

    def show_document(self, doc_id: int) -> None:
        self.show_page("documents")
        self.pages["documents"].select_document(doc_id)  # type: ignore[attr-defined]

    def show_case(self, case_id: int) -> None:
        case = self.ctrl.ctx.services.cases.get(case_id)
        if case.invoice_id:
            self.show_page("cases")
            self.pages["cases"].select_invoice(case.invoice_id)  # type: ignore[attr-defined]

    def show_drill(self, target: DrillTarget, flt: DashboardFilter) -> None:
        result = self.ctrl.ctx.dashboard.drilldown(target, flt)
        DrillDialog(self.ctrl, result, self).exec()

    def _open_hit(self, hit: SearchHit) -> None:
        self.search_box.clear()
        if hit.kind == "supplier":
            self.show_supplier(hit.entity_id)
        elif hit.kind == "invoice":
            self.show_invoice(hit.entity_id)
        elif hit.kind == "case":
            self.show_case(hit.entity_id)
        elif hit.kind == "document":
            self.show_document(hit.entity_id)

    # -- actions ---------------------------------------------------------------------------------------------------------
    def focus_search(self) -> None:
        self.search_box.setFocus()
        self.search_box.selectAll()

    def start_import(self) -> None:
        self.show_page("documents")
        self.pages["documents"].choose_files()  # type: ignore[attr-defined]

    def new_payment(self, _arg=None) -> None:
        PaymentDialog(self.ctrl, parent=self).exec()

    def new_supplier(self) -> None:
        SupplierDialog(self.ctrl, parent=self).exec()

    def lock(self) -> None:
        """Show the PIN screen (modal). Closing it without the PIN quits the application."""
        pin = self.ctrl.ctx.services.pin
        if not pin.enabled:
            return
        self.search_popup.hide()
        dlg = UnlockDialog(pin, self)
        if not dlg.exec():
            self.ctrl.app.quit()
        self.ctrl.restart_idle_timer()
