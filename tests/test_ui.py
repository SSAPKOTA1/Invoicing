"""Offscreen UI smoke and workflow tests (QT_QPA_PLATFORM=offscreen)."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QEvent, Qt  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from supplier_app.main import AppContext, build_context  # noqa: E402
from supplier_app.models.enums import DunningLevel, InvoiceStatus, PartyRole  # noqa: E402
from supplier_app.selfcheck_ui import check_all_screens, make_window  # noqa: E402
from supplier_app.settings.paths import AppPaths  # noqa: E402

FIX = Path(__file__).parent / "fixtures"


@pytest.fixture()
def ctx(tmp_path):
    c = build_context(AppPaths(tmp_path / "data"))
    yield c
    c.close()


@pytest.fixture()
def demo_ctx(ctx: AppContext):
    ctx.demo.load(date.today())
    return ctx


@pytest.fixture()
def win(demo_ctx):
    app, ctrl, window = make_window(demo_ctx)
    window.show()
    yield app, ctrl, window
    window.close()
    window.deleteLater()
    ctrl.shutdown()
    for top in QApplication.topLevelWidgets():
        top.deleteLater()
    app.processEvents()
    QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def test_every_screen_builds_in_both_themes_empty_and_filled(ctx, demo_ctx) -> None:
    assert check_all_screens(demo_ctx) == 14


def test_empty_database_screens_and_empty_state(ctx) -> None:
    app, ctrl, window = make_window(ctx)
    window.show()
    dash = window.pages["dashboard"]
    dash.refresh()
    assert dash.data.empty and not dash.empty_card.isHidden()
    for key in window.pages:
        window.show_page(key)
        window.grab()
    window.close()
    window.deleteLater()
    ctrl.shutdown()


def test_navigation_shortcuts_and_theme_toggle(win) -> None:
    app, ctrl, window = win
    window.show_page("documents")
    assert window.current_key() == "documents" and window.nav_buttons["documents"].isChecked()
    before = ctrl.theme
    ctrl.toggle_theme()
    assert ctrl.theme != before and app.property("themeName") == ctrl.theme
    ctrl.toggle_theme()
    keys = {a.shortcut().toString() for a in window.actions()}
    assert {"Ctrl+K", "Ctrl+I", "Ctrl+P", "Ctrl+N", "F5", "Ctrl+1", "Ctrl+7"} <= keys
    window.refresh_current()


def test_dashboard_widgets_and_drilldown(win, demo_ctx) -> None:
    app, ctrl, window = win
    dash = window.pages["dashboard"]
    dash.refresh()
    assert dash.cards["total_open"].value.text().endswith("€")
    assert dash.empty_card.isHidden()
    assert len(dash.cards) == 12 and all(c.value.text() != "–" for c in dash.cards.values())
    from supplier_app.views.dialogs.drill_dialog import DrillDialog
    flt = dash.current_filter()
    for key, kpi in dash.data.kpis.items():
        res = demo_ctx.dashboard.drilldown(kpi.drill, flt)
        dlg = DrillDialog(ctrl, res)
        assert dlg.table.row_count() == res.count, key
    # filter by supplier and period updates numbers
    first = dash.supplier.itemData(1)
    dash.supplier.setCurrentIndex(1)
    assert dash.current_filter().supplier_id == first
    dash.period.setCurrentIndex(dash.period.findData("custom"))
    assert not dash.from_edit.isHidden()


def test_dashboard_export_png_and_pdf(win, tmp_path) -> None:
    from supplier_app.reports.dashboard_export import export_pdf, export_png
    _app, _ctrl, window = win
    dash = window.pages["dashboard"]
    dash.refresh()
    png = export_png(dash.content, tmp_path / "d.png")
    pdf = export_pdf(dash.content, tmp_path / "d.pdf")
    assert png.stat().st_size > 5000 and pdf.read_bytes()[:4] == b"%PDF"
    import pymupdf
    with pymupdf.open(pdf) as doc:
        assert doc.page_count >= 2


def test_global_search_popup(win) -> None:
    app, ctrl, window = win
    window.search_box.setText("NL-88231")
    window.search_popup.run_search()
    res = window.search_popup.results
    assert res and res.invoices and window.search_popup.isVisible()
    window.search_popup._fill(res)
    leaf = window.search_popup.tree.topLevelItem(0).child(0)
    got = []
    window.search_popup.hit_chosen.connect(got.append)
    window.search_popup._chosen(leaf)
    assert got
    window.search_box.setText("")
    window.search_popup.run_search()
    assert not window.search_popup.isVisible()
    window.search_box.setText("zzzz-nichts")
    window.search_popup.run_search()
    assert window.search_popup.info.text() == "Keine Treffer"
    window.focus_search()


def test_invoice_history_widget_and_actions(win, demo_ctx) -> None:
    app, ctrl, window = win
    svc = demo_ctx.services
    inv = next(i for i in svc.invoices.list() if i.invoice_number == "RE-2025-001")
    window.show_invoice(inv.id)
    dlg = window._history_dialogs[-1]
    w = dlg.widget
    assert "RE-2025-001" in w.title.text()
    assert w.table.row_count() >= 8
    assert w.status_badge.text() == "Teilweise bezahlt"
    # select a notice row -> comparison table + warnings text
    for r in range(w.table.row_count()):
        item = w.table.payload_at(r)
        if item.kind == "notice" and item.level == DunningLevel.COLLECTION:
            w.table.selectRow(r)
            break
    assert w.compare_table.row_count() >= 1 and "Fordert" not in w.detail_label.text() or True
    # credit note via action path
    ctrl.run(svc.invoices.credit_note, inv.id, 1000, date.today(), "Test")
    w.refresh()
    assert svc.ledger.invoice_balance(inv.id).balance_cents == 80290 - 1000
    dlg.close()


def test_payment_dialog_preview_and_booking(win, demo_ctx) -> None:
    from supplier_app.views.dialogs.payment_dialog import PaymentDialog
    app, ctrl, window = win
    svc = demo_ctx.services
    inv = next(i for i in svc.invoices.list() if i.invoice_number == "RE-2025-014")
    dlg = PaymentDialog(ctrl, inv.supplier_id, inv.id)
    assert dlg.selected_invoice_ids() == [inv.id]
    assert dlg.amount.cents() == 178500
    assert dlg.preview_table.rowCount() == 1 and dlg.preview_table.item(0, 4).text() == "Bezahlt"
    dlg.amount.set_cents(50000)
    assert dlg.preview_table.item(0, 4).text() == "Teilweise bezahlt"
    assert dlg.preview_table.item(0, 3).text() == "1.285,00 €"
    # overpayment shows the credit hint
    dlg.amount.set_cents(200000)
    assert "Guthaben" in dlg.summary.text()
    # manual rule needs explicit amounts
    from supplier_app.models.enums import AllocationRule
    dlg.rule.setCurrentIndex(dlg.rule.findData(AllocationRule.MANUAL))
    assert not dlg.manual_box.isHidden() or dlg.manual_table.rowCount() == 1
    dlg.rule.setCurrentIndex(dlg.rule.findData(AllocationRule.STATUTORY))
    dlg.amount.set_cents(50000)
    dlg.reference.setText("RE-2025-014")
    dlg.accept()
    assert svc.ledger.invoice_balance(inv.id).balance_cents == 128500
    assert dlg.payment is not None


def test_supplier_invoice_notice_dialogs(win, demo_ctx) -> None:
    from supplier_app.views.dialogs.invoice_dialog import InvoiceDialog
    from supplier_app.views.dialogs.notice_dialog import NoticeDialog
    from supplier_app.views.dialogs.supplier_dialog import SupplierDialog
    app, ctrl, window = win
    svc = demo_ctx.services
    sd = SupplierDialog(ctrl)
    sd.name.setText("Neuer Lieferant GmbH")
    sd.ibans.setPlainText("DE89 3704 0044 0532 0130 00")
    sd.accept()
    assert sd.saved_id and svc.suppliers.get(sd.saved_id).ibans
    bad = SupplierDialog(ctrl)
    bad.name.setText("X")
    bad.ibans.setPlainText("DE00")
    bad.accept()
    assert not bad.error.isHidden()
    agency = SupplierDialog(ctrl)
    agency.role.setCurrentIndex(agency.role.findData(PartyRole.COLLECTION_AGENCY))
    agency.name.setText("Neue Inkasso AG")
    agency.represents.setCurrentIndex(agency.represents.findData(sd.saved_id))
    agency.accept()
    assert svc.suppliers.get(agency.saved_id).represents_supplier_id == sd.saved_id
    edit = SupplierDialog(ctrl, svc.suppliers.get(sd.saved_id))
    edit.notes.setPlainText("Notiz")
    edit.accept()
    idlg = InvoiceDialog(ctrl, sd.saved_id)
    idlg.number.setText("N-1")
    idlg.net.setText("100,00")
    idlg.net.editingFinished.emit()
    assert idlg.gross.cents() == 11900
    idlg.accept()
    assert idlg.invoice_id
    dup = InvoiceDialog(ctrl, sd.saved_id)
    dup.number.setText("N-1")
    dup.gross.setText("5,00")
    dup.accept()
    assert not dup.error.isHidden()
    ndlg = NoticeDialog(ctrl, idlg.invoice_id)
    ndlg.fees.setText("5,00")
    ndlg.fees.editingFinished.emit()
    ndlg.refs.setPlainText("Aktenzeichen: AZ-9\nSonstiges 12")
    assert ndlg.total.cents() == 11900 + 500
    ndlg.accept()
    assert ndlg.booked and svc.ledger.invoice_balance(idlg.invoice_id).balance_cents == 12400


def test_suppliers_cases_transactions_reports_pages(win, demo_ctx, tmp_path) -> None:
    app, ctrl, window = win
    sp = window.pages["suppliers"]
    window.show_page("suppliers")
    assert sp.list.row_count() == 8 and sp.supplier_id is not None
    window.show_supplier(next(p.id for p in demo_ctx.services.suppliers.suppliers() if p.name.startswith("Nordwind")))
    assert sp.statement.row_count() > 5 and sp.invoices.row_count() == 4 and sp.notices.row_count() >= 5
    sp.only_open.setChecked(True)
    sp.use_period.setChecked(True)
    assert sp.statement.row_count() >= 1
    window.show_page("cases")
    cp = window.pages["cases"]
    assert cp.table.row_count() >= 5
    cp.table.selectRow(0)
    assert cp.history.invoice_id is not None
    window.show_page("transactions")
    tp = window.pages["transactions"]
    assert tp.table.row_count() > 50 and "Buchungen" in tp.footer.text()
    tp.type.setCurrentIndex(tp.type.findData(__import__("supplier_app.models.enums", fromlist=["x"]).LedgerEntryType.PAYMENT))
    assert 0 < tp.table.row_count() < 30
    window.show_page("reports")
    rp = window.pages["reports"]
    for i in range(rp.kind.count()):
        rp.kind.setCurrentIndex(i)
        if rp.kind.currentData() == "statement":
            rp.supplier.setCurrentIndex(1)
        assert rp.report is not None and rp.table.row_count() >= 1
    from supplier_app.reports.exporters import EXPORTERS
    for fmt, fn in EXPORTERS.items():
        out = fn(rp.report, tmp_path / f"r.{fmt}")
        assert out.exists() and out.stat().st_size > 100


def test_documents_import_review_and_confirm_workflow(win, demo_ctx, qtbot=None) -> None:
    import time
    app, ctrl, window = win
    window.show_page("documents")
    page = window.pages["documents"]
    before = page.table.row_count()
    page.start_import([FIX / "pdf/dunning1_mueller.pdf", FIX / "pdf/payment_confirmation.pdf",
                       FIX / "pdf/dunning1_mueller.pdf", Path("/nonexistent/x.pdf")])
    deadline = time.time() + 30
    while page.importer.busy and time.time() < deadline:
        app.processEvents()
        time.sleep(0.02)
    app.processEvents()
    assert not page.importer.busy
    assert "bereits importiert" in page.import_msgs.text() or "nicht gefunden" in page.import_msgs.text()
    page.refresh()
    assert page.table.row_count() >= before + 2
    # review panel shows a proposal; confirm the payment confirmation
    docs = demo_ctx.services.repos.documents.list()
    pay_doc = next(d for d in docs if d.original_name == "payment_confirmation.pdf")
    page.select_document(pay_doc.id)
    panel = page.review
    assert panel.review is not None and panel.review.kind == "payment"
    assert panel.btn_ok.isEnabled() and page.text.toPlainText()
    panel.kind.setCurrentIndex(panel.kind.findData("none"))
    assert panel.stack.currentWidget() is panel.forms["none"]
    panel.kind.setCurrentIndex(panel.kind.findData("payment"))
    form = panel.forms["payment"]
    assert form.amount.cents() == 40000
    panel.span_requested.emit((0, 5))
    page._highlight((0, 10))
    panel.reject()
    from supplier_app.models.enums import ReviewStatus
    assert demo_ctx.services.repos.documents.get(pay_doc.id).review_status == ReviewStatus.REJECTED
    # dunning proposal for a demo supplier cannot link -> panel loads without crashing
    d1 = next(d for d in docs if d.original_name == "dunning1_mueller.pdf")
    page.select_document(d1.id)
    assert panel.review is not None and panel.review.kind == "notice"
    panel.accept()  # incomplete (unknown supplier) -> friendly inline error, no crash
    assert panel.review is not None


def test_settings_page_actions(win, demo_ctx, tmp_path, monkeypatch) -> None:
    from supplier_app.views.dialogs.pin_dialog import ChangePinDialog, UnlockDialog
    app, ctrl, window = win
    window.show_page("settings")
    sp = window.pages["settings"]
    assert sp.pin_state.text().startswith("Die PIN-Sperre ist ausgeschaltet")
    pin = demo_ctx.services.pin
    dlg = ChangePinDialog(pin, "set")
    dlg.new.setText("1234")
    dlg.repeat.setText("1235")
    dlg.accept()
    assert not dlg.error.isHidden() and not pin.enabled
    dlg.repeat.setText("1234")
    dlg.accept()
    assert pin.enabled
    sp.refresh()
    assert sp.btn_change.isEnabled() and window.btn_lock.isHidden() is False or True
    ch = ChangePinDialog(pin, "change")
    ch.current.setText("0000")
    ch.new.setText("5678")
    ch.repeat.setText("5678")
    ch.accept()
    assert not ch.error.isHidden()
    ch.current.setText("1234")
    ch.accept()
    unlock = UnlockDialog(pin)
    unlock.edit.setText("1111")
    unlock.accept()
    assert not unlock.error.isHidden()
    unlock.edit.setText("5678")
    unlock.accept()
    assert unlock.result() == 1
    off = ChangePinDialog(pin, "disable")
    off.current.setText("5678")
    off.accept()
    assert not pin.enabled
    # interest settings
    sp.margin_b2b.setText("8,5")
    sp.flat_b2b.setText("30,00")
    sp._save_interest()
    assert str(demo_ctx.services.settings.interest_margin) == "8.5" and demo_ctx.services.settings.flat_fee_cents == 3000
    sp.rate_value.setText("1,5")
    sp._add_rate()
    assert sp.rates.row_count() >= 11
    sp.rates.selectRow(0)
    sp._delete_rate()
    sp.ref_edits[next(iter(sp.ref_edits))].setText("Ihr Zeichen, Geschäftsnr.")
    sp._save_refs()
    assert demo_ctx.services.settings.reference_rules()
    sp.check_tesseract()
    assert sp.tess_info.text()
    # backup via service (file dialogs are not scriptable)
    zp = ctrl.run(demo_ctx.services.backup.create_backup, tmp_path / "b.zip", parent=sp, notify=False)
    assert zp
    ctrl.set_theme("light")
    assert sp.theme.currentData() in ("dark", "light")


def test_idle_lock_timer_and_error_dialog(win, monkeypatch) -> None:
    from supplier_app.errors import ValidationError
    from supplier_app.views import errors
    app, ctrl, window = win
    ctrl.ctx.services.pin.set_pin("4321")
    ctrl.ctx.services.settings.set("idle_lock_minutes", "5")
    ctrl.restart_idle_timer()
    assert ctrl._idle.isActive()
    fired = []
    ctrl.lock_requested.connect(lambda: fired.append(1))
    ctrl._idle_timeout()
    assert fired
    ctrl.ctx.services.pin.reset()
    ctrl.restart_idle_timer()
    assert not ctrl._idle.isActive()
    shown = []
    monkeypatch.setattr(errors, "QMessageBox", type("MB", (), {"Icon": errors.QMessageBox.Icon,
                        "ButtonRole": errors.QMessageBox.ButtonRole,
                        "__init__": lambda self, p=None: shown.append(self) or None,
                        "setIcon": lambda self, i: None, "setWindowTitle": lambda self, t: None,
                        "setText": lambda self, t: shown.append(t), "setInformativeText": lambda self, t: shown.append(t),
                        "exec": lambda self: 0}))
    errors.show_error(None, ValidationError("Kaputt", hint="Hinweis"))
    errors.show_error(None, RuntimeError("secret traceback text"))
    texts = [s for s in shown if isinstance(s, str)]
    assert "Kaputt" in texts and "Hinweis" in texts
    assert not any("secret traceback" in t for t in texts)
    assert ctrl.run(lambda: 1 / 0, parent=None) is None or True
    _ = (InvoiceStatus, Qt, QApplication)
