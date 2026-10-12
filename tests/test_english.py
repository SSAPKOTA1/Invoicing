"""The English interface: switching and saving the language, translated program texts, no German left on the screens."""

from __future__ import annotations

import re
from datetime import date

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QAbstractListModel, QEvent, Qt  # noqa: E402
from PySide6.QtWidgets import (  # noqa: E402
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QComboBox,
    QGroupBox,
    QLabel,
    QLineEdit,
    QPushButton,
    QTabBar,
    QToolButton,
    QWidget,
)

from supplier_app.errors import ValidationError  # noqa: E402
from supplier_app.i18n import current_language, set_language, tr  # noqa: E402
from supplier_app.main import build_context  # noqa: E402
from supplier_app.reports.builders import ReportService  # noqa: E402
from supplier_app.selfcheck_ui import make_window  # noqa: E402
from supplier_app.settings.local_prefs import saved_language  # noqa: E402
from supplier_app.settings.paths import AppPaths  # noqa: E402
from tests.helpers import make_scenario  # noqa: E402

#: function words that never occur in English texts (domain words and names may: demo data is German)
GERMAN_WORDS = set(
    "der die das und nicht ist wurde bitte für mit von kein keine wird kann muss dem des eine einer bei nach über oder "
    "wenn zum zur nur noch bereits werden sind sie ihre sich gibt haben aus als auch".split())


def _german(text: str) -> bool:
    return any(w in GERMAN_WORDS for w in re.findall(r"[a-zA-ZäöüÄÖÜß]+", text.lower()))


@pytest.fixture()
def ctx(tmp_path):
    c = build_context(AppPaths(tmp_path / "data"))
    yield c
    c.close()


@pytest.fixture()
def en_win(ctx):
    ctx.demo.load(date.today())
    set_language("en")
    app, ctrl, window = make_window(ctx)
    window.resize(1500, 950)
    window.show()
    yield app, ctrl, window
    window.close()
    window.deleteLater()
    ctrl.shutdown()
    for top in QApplication.topLevelWidgets():
        top.deleteLater()
    app.processEvents()
    QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def _texts(root: QWidget):
    """Every text a user can read in the widget tree (labels, buttons, tabs, combos, table headers and cells, tooltips)."""
    for w in root.findChildren(QWidget):
        if isinstance(w, QLabel | QPushButton | QCheckBox | QToolButton):
            yield re.sub(r"<[^>]+>", "", w.text())
        if isinstance(w, QGroupBox):
            yield w.title()
        if isinstance(w, QComboBox):
            yield from (w.itemText(i) for i in range(w.count()))
        if isinstance(w, QTabBar):
            yield from (w.tabText(i) for i in range(w.count()))
        if isinstance(w, QLineEdit):
            yield w.placeholderText()
        yield w.toolTip()
        if isinstance(w, QAbstractItemView) and w.model() is not None:
            m = w.model()
            columns = 1 if isinstance(m, QAbstractListModel) else m.columnCount()
            for r in range(min(m.rowCount(), 80)):
                for c in range(columns):
                    yield str(m.data(m.index(r, c), Qt.ItemDataRole.DisplayRole) or "")
            if columns > 1:
                yield from (str(m.headerData(c, Qt.Orientation.Horizontal) or "") for c in range(columns))


def test_no_german_function_words_on_any_english_screen(en_win) -> None:
    app, ctrl, window = en_win
    leftovers: dict[str, str] = {}
    for key in window.pages:
        window.show_page(key)
        app.processEvents()
        for text in _texts(window.pages[key]):
            # settings.vocab.hint deliberately names German example words
            if text and _german(text) and not text.startswith("Recognition already knows"):
                leftovers[text[:90]] = key
    assert not leftovers, leftovers
    assert window.nav_buttons["dashboard"].text().strip().endswith("Overview")


def test_dialogs_and_review_panel_in_english(en_win, ctx) -> None:
    from supplier_app.views.dialogs.history_dialog import InvoiceHistoryDialog
    from supplier_app.views.dialogs.invoice_dialog import InvoiceDialog
    from supplier_app.views.dialogs.notice_dialog import NoticeDialog
    from supplier_app.views.dialogs.payment_dialog import PaymentDialog
    from supplier_app.views.dialogs.supplier_dialog import SupplierDialog

    app, ctrl, window = en_win
    inv = ctx.services.invoices.list()[0]
    leftovers = []
    for dialog in (PaymentDialog(ctrl, inv.supplier_id, inv.id), SupplierDialog(ctrl), InvoiceDialog(ctrl, inv.supplier_id),
                   NoticeDialog(ctrl, inv.id), InvoiceHistoryDialog(ctrl, inv.id)):
        dialog.show()
        app.processEvents()
        leftovers += [t for t in _texts(dialog) if t and _german(t)]
        dialog.close()
    window.show_page("documents")
    page = window.pages["documents"]
    for doc in ctx.services.repos.documents.list():
        page.select_document(doc.id)  # includes the recognition hints of the review panel
        app.processEvents()
        leftovers += [t for t in _texts(page) if t and _german(t)]
    assert not leftovers, sorted(set(leftovers))[:10]


def test_dashboard_drilldowns_reports_and_history_in_english(en_win, ctx) -> None:
    from supplier_app.services.dashboard_models import DrillTarget

    app, ctrl, window = en_win
    window.show_page("dashboard")
    data = window.pages["dashboard"].data
    texts: list[str] = []
    for target in (DrillTarget("open"), DrillTarget("overdue"), DrillTarget("credits"), DrillTarget("discrepancies"),
                   DrillTarget("cases"), DrillTarget("docs", "review"), DrillTarget("paid"), DrillTarget("charges")):
        result = ctx.dashboard.drilldown(target, data.filter)
        texts += [result.title, *result.columns] + [c for row in result.rows for c in row.cells]
    for items in data.attention.values():
        texts += [t for it in items for t in (it.title, it.subtitle)]
    texts += [it.text for it in data.activity]
    reports = ReportService(ctx.services)
    supplier = ctx.services.suppliers.list()[0]
    for kind in ("statement", "open_items", "dunning", "payments"):
        table = reports.build(kind, supplier_id=supplier.id if kind == "statement" else None, as_of=date.today())
        texts += [table.title, table.subtitle, *table.columns, table.totals_label]
        texts += [str(c) for row in table.rows for c in row] + [c for t in table.extra for c in (t.title, *t.columns)]
    for inv in ctx.services.invoices.list():
        hist = ctx.services.history.invoice_history(inv.id)
        texts += [it.title for it in hist.items] + [it.comment for it in hist.items] + hist.warnings
    assert not [t for t in texts if _german(t)], sorted({t for t in texts if _german(t)})[:10]


def test_service_errors_and_report_headings_are_english(ctx) -> None:
    svc = ctx.services
    set_language("en")
    with pytest.raises(Exception, match="Invoice not found"):
        svc.history.invoice_history(9999)
    sc = make_scenario(svc)
    with pytest.raises(ValidationError, match="Please enter an invoice number"):
        svc.invoices.create_invoice(sc.supplier.id, "", date(2024, 1, 1), gross_cents=100)
    with pytest.raises(ValidationError, match="payment amount must be greater than 0"):
        svc.payments.record_payment(sc.supplier.id, date(2024, 2, 1), 0, [sc.invoice.id])
    table = ReportService(svc).build("statement", supplier_id=sc.supplier.id, date_from=date(2024, 1, 1))
    assert table.columns[:2] == ["Date", "Invoice"] and table.title.startswith("Account statement")
    assert "Balance brought forward" in {str(c) for row in table.rows for c in row}
    set_language("de")
    german = ReportService(svc).build("statement", supplier_id=sc.supplier.id, date_from=date(2024, 1, 1))
    assert german.columns[:2] == ["Datum", "Rechnung"]  # booking texts stay German in the database, only the display changes


def test_language_is_saved_per_pc_and_validated(ctx, tmp_path) -> None:
    app, ctrl, window = make_window(ctx)
    try:
        assert current_language() == "de" and ctrl.language == "de"
        ctrl.set_language("en")
        assert ctrl.language == "en" and saved_language(ctx.paths.local) == "en"
        with pytest.raises(ValidationError):
            ctrl.set_language("klingon")
        assert saved_language(ctx.paths.local) == "en"
    finally:
        window.close()
        window.deleteLater()
        ctrl.shutdown()


def test_settings_page_language_choice_and_restart(en_win, monkeypatch) -> None:
    from supplier_app.views.pages import settings as settings_module

    app, ctrl, window = en_win
    window.show_page("settings")
    page = window.pages["settings"]
    assert page.language.currentData() == "en"  # shows the active language
    asked, restarted, informed = [], [], []
    monkeypatch.setattr(settings_module, "confirm", lambda parent, text: asked.append(text) or False)
    monkeypatch.setattr(settings_module, "info", lambda parent, text: informed.append(text))
    monkeypatch.setattr(ctrl, "restart_application", lambda: restarted.append(1))
    page.language.setCurrentIndex(page.language.findData("de"))
    page._language_chosen()
    assert asked and informed and not restarted and ctrl.language == "de"
    assert saved_language(ctrl.ctx.paths.local) == "de"
    page.refresh()
    assert page.language.currentData() == "de"  # the choice stays visible until the restart
    monkeypatch.setattr(settings_module, "confirm", lambda parent, text: True)
    page._language_chosen()
    assert restarted == [1]


def test_cli_language_option_and_startup_choice(tmp_path, monkeypatch) -> None:
    import os

    from supplier_app.__main__ import main

    monkeypatch.setenv("SUPPLIERAPP_DATA", str(tmp_path / "data"))
    monkeypatch.delenv("SUPPLIERAPP_LANGUAGE", raising=False)
    assert main(["--language", "en", "--selfcheck"]) == 0
    assert current_language() == "en" and os.environ["SUPPLIERAPP_LANGUAGE"] == "en"
    monkeypatch.delenv("SUPPLIERAPP_LANGUAGE")
    assert tr("nav.settings") == "Settings"
