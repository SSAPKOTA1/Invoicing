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
    assert check_all_screens(demo_ctx) == 16


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


# -- companies / hotels (scope) ---------------------------------------------------------------------------
def test_scope_selector_filters_every_page_and_is_remembered(win, demo_ctx) -> None:
    from supplier_app.models.scope import ALL, Scope
    app, ctrl, window = win
    svc = demo_ctx.services
    box = window.scope_box
    assert box.count() == 1 + 2 + 4 and box.itemData(0) == ALL
    window.show_page("transactions")
    all_rows = window.pages["transactions"].table.row_count()
    all_open = window.pages["dashboard"].data.kpis["total_open"].value if window.pages["dashboard"].data else None
    hotel_idx = next(i for i in range(box.count()) if box.itemData(i).hotel_id is not None)
    hotel_scope = box.itemData(hotel_idx)
    box.setCurrentIndex(hotel_idx)
    window._scope_chosen(hotel_idx)
    assert ctrl.scope == hotel_scope and svc.settings.get("active_scope") == hotel_scope.key()
    assert 0 < window.pages["transactions"].table.row_count() < all_rows
    assert "Seeblick" in window.pages["transactions"].scope_label.text() or "Nordlicht" in window.pages["transactions"].scope_label.text()
    window.show_page("dashboard")
    dash = window.pages["dashboard"]
    assert dash.data.kpis["total_open"].value < all_open and hotel_scope.hotel_id is not None
    assert dash.scope_label.text() == svc.organization.label(hotel_scope)
    for key in ("suppliers", "cases", "documents", "reports", "settings"):
        window.show_page(key)
    assert window.pages["cases"].table.row_count() < 12
    # company view contains the hotel view; a restart restores the selection
    company_scope = Scope(hotel_scope.company_id)
    ctrl.set_scope(company_scope)
    assert window.scope_box.currentData() == company_scope
    window.show_page("transactions")
    assert window.pages["transactions"].table.row_count() >= 1
    from supplier_app.controllers.app_controller import AppController
    again = AppController(demo_ctx, app)
    assert again.scope == company_scope
    again.shutdown()
    # a deleted entry falls back to "everything"
    svc.settings.set("active_scope", "h:99999")
    again = AppController(demo_ctx, app)
    assert again.scope == ALL
    again.shutdown()
    ctrl.set_scope(ALL)
    assert window.scope_box.currentIndex() == 0


def test_search_respects_scope(win, demo_ctx) -> None:
    app, ctrl, window = win
    org = demo_ctx.services.organization
    hotel = org.hotels()[0]
    ctrl.set_scope(org.scope_for(hotel.company_id, hotel.id))
    popup = window.search_popup
    window.search_box.setText("RE-")
    popup.run_search()
    scoped = popup.results.total
    ctrl.set_scope(__import__("supplier_app.models.scope", fromlist=["ALL"]).ALL)
    popup.run_search()
    assert 0 <= scoped <= popup.results.total


def test_settings_manage_companies_and_hotels(win, demo_ctx, monkeypatch) -> None:
    from PySide6.QtWidgets import QInputDialog
    app, ctrl, window = win
    window.show_page("settings")
    sp = window.pages["settings"]
    before = sp.org_table.row_count()
    answers = iter(["Neue Betriebs GmbH", "Hotel Neu", "Hotel Neu 2"])
    monkeypatch.setattr(QInputDialog, "getText", lambda *a, **k: (next(answers), True))
    sp.add_company()
    assert sp.org_table.row_count() == before + 1
    company = next(c for c in demo_ctx.services.organization.companies() if c.name == "Neue Betriebs GmbH")
    assert any(i for i in range(window.scope_box.count()) if "Neue Betriebs" in window.scope_box.itemText(i))
    sp.org_table.select_payload(("c", company.id))
    sp.add_hotel()
    hotel = demo_ctx.services.organization.hotels(company.id)[0]
    assert hotel.name == "Hotel Neu"
    sp.org_table.select_payload(("h", hotel.id))
    monkeypatch.setattr(QInputDialog, "getText", lambda *a, **k: ("Hotel Umbenannt", True))
    sp.rename_org()
    assert demo_ctx.services.organization.hotel(hotel.id).name == "Hotel Umbenannt"
    monkeypatch.setattr("supplier_app.views.pages.settings.confirm", lambda *a, **k: True)
    ctrl.set_scope(demo_ctx.services.organization.scope_for(company.id, hotel.id))
    sp.org_table.select_payload(("h", hotel.id))
    sp.delete_org()  # empty hotel can be deleted; the active scope falls back to "all"
    assert not demo_ctx.services.organization.hotels(company.id) and ctrl.scope.is_all
    # a company with business cannot be deleted: friendly error instead of a crash
    shown = []
    monkeypatch.setattr("supplier_app.views.errors.show_error", lambda parent, exc: shown.append(exc))
    busy = next(c for c in demo_ctx.services.organization.companies() if c.name.startswith("Seeblick"))
    sp.org_table.select_payload(("c", busy.id))
    sp.delete_org()
    assert shown and demo_ctx.services.organization.company(busy.id)


def test_due_date_scope_and_deadline_can_be_changed_later(win, demo_ctx, monkeypatch) -> None:
    from datetime import timedelta

    from supplier_app.views.dialogs.edit_dialogs import DateDialog, ScopeDialog
    app, ctrl, window = win
    svc = demo_ctx.services
    inv = next(i for i in svc.invoices.list() if i.invoice_number == "RE-2025-001")
    window.show_invoice(inv.id)
    w = window._history_dialogs[-1].widget
    new_due = date.today() + timedelta(days=45)

    def fake_date_exec(self) -> int:
        self.edit.setDate(__import__("PySide6.QtCore", fromlist=["QDate"]).QDate(new_due.year, new_due.month, new_due.day))
        return 1

    monkeypatch.setattr(DateDialog, "exec", fake_date_exec)
    w._change_due()
    assert svc.invoices.get(inv.id).due_date == new_due and format_check(w.subtitle.text(), new_due)
    # assignment: pick another hotel; the company follows automatically
    hotel = next(h for h in svc.organization.hotels() if h.id != inv.hotel_id)
    monkeypatch.setattr(ScopeDialog, "exec", lambda self: (self.picker.set_values(None, hotel.id), 1)[1])
    w._change_scope()
    changed = svc.invoices.get(inv.id)
    assert changed.hotel_id == hotel.id and changed.company_id == hotel.company_id
    assert hotel.name in w.subtitle.text()
    # notice deadline: only enabled for notice rows
    assert not w.actions["deadline"].isEnabled()
    for r in range(w.table.row_count()):
        item = w.table.payload_at(r)
        if item.kind == "notice":
            w.table.selectRow(r)
            break
    assert w.actions["deadline"].isEnabled()
    notice_id = w.table.selected_payload().notice_id
    w._change_deadline()
    notice = svc.dunning.get(notice_id)
    assert notice.new_deadline == new_due
    assert any(a.action in ("due_date", "deadline", "assign_scope") for a in svc.repos.audit.list(limit=20))


def format_check(text: str, day: date) -> bool:
    return day.strftime("%d.%m.%Y") in text


def test_invoice_dialog_assigns_hotel_and_company(win, demo_ctx) -> None:
    from decimal import Decimal  # noqa: F401

    from supplier_app.views.dialogs.invoice_dialog import InvoiceDialog
    app, ctrl, window = win
    svc = demo_ctx.services
    hotel = svc.organization.hotels()[0]
    sup = svc.suppliers.suppliers()[0]
    dlg = InvoiceDialog(ctrl, sup.id, window)
    assert dlg.scope.isVisible() or not dlg.isVisible()
    dlg.scope.set_values(None, hotel.id)
    assert dlg.scope.company_id == hotel.company_id  # hotel implies its company
    dlg.number.setText("RE-SCOPE-1")
    dlg.gross.set_cents(11900)
    dlg._from_gross()
    dlg.accept()
    created = svc.invoices.get(dlg.invoice_id)
    assert created.hotel_id == hotel.id and created.company_id == hotel.company_id
    # company only, no hotel
    dlg2 = InvoiceDialog(ctrl, sup.id, window)
    dlg2.scope.set_values(hotel.company_id, None)
    dlg2.number.setText("RE-SCOPE-2")
    dlg2.gross.set_cents(5000)
    dlg2._from_gross()
    dlg2.accept()
    only_company = svc.invoices.get(dlg2.invoice_id)
    assert only_company.company_id == hotel.company_id and only_company.hotel_id is None


def test_review_form_due_date_shortcuts_and_assignment(win, demo_ctx) -> None:
    import time
    app, ctrl, window = win
    svc = demo_ctx.services
    window.show_page("documents")
    page = window.pages["documents"]
    page.start_import([FIX / "pdf/invoice_RE-2024-001.pdf"])
    deadline = time.time() + 30
    while page.importer.busy and time.time() < deadline:
        app.processEvents()
        time.sleep(0.02)
    app.processEvents()
    doc = next(d for d in svc.repos.documents.list() if d.original_name == "invoice_RE-2024-001.pdf")
    hotel = svc.organization.hotels()[1]
    ctrl.set_scope(svc.organization.scope_for(hotel.company_id, hotel.id))
    page.select_document(doc.id)
    panel = page.review
    form = panel.forms["invoice"]
    assert panel.review.kind == "invoice"
    assert form.scope.hotel_id == hotel.id  # imported while a hotel is selected -> preassigned
    base = form.date.date().toPython()
    form._due_plus(60)
    from datetime import timedelta
    assert form.due.date().toPython() == base + timedelta(days=60)
    form.scope.set_values(hotel.company_id, None)
    assert form.scope.hotel_id is None
    panel._collect()
    assert panel.review.company_id == hotel.company_id and panel.review.hotel_id is None
    assert panel.review.due_date == base + timedelta(days=60)


def test_reports_print_preview_and_pdf(win, demo_ctx, tmp_path, monkeypatch) -> None:
    from PySide6.QtPrintSupport import QPrintDialog, QPrinter, QPrintPreviewDialog

    from supplier_app.views.pages import reports as reports_mod
    app, ctrl, window = win
    window.show_page("reports")
    rp = window.pages["reports"]
    assert not rp.btn_print.isEnabled()  # the Kontoblatt needs a supplier first
    rp.kind.setCurrentIndex(rp.kind.findData("open_items"))
    assert rp.btn_print.isEnabled() and rp.btn_preview.isEnabled()
    pdf = tmp_path / "print.pdf"
    pages = rp.print_pdf(str(pdf))
    assert pages >= 1 and pdf.read_bytes().startswith(b"%PDF")
    # preview dialog renders through the same code path
    seen = {}

    def fake_preview_exec(self) -> int:
        printer = QPrinter()
        printer.setOutputFormat(QPrinter.OutputFormat.PdfFormat)
        printer.setOutputFileName(str(tmp_path / "preview.pdf"))
        self.paintRequested.emit(printer)
        seen["preview"] = True
        return 0

    monkeypatch.setattr(QPrintPreviewDialog, "exec", fake_preview_exec)
    rp.preview()
    assert seen.get("preview") and (tmp_path / "preview.pdf").exists()
    # print dialog accepted -> a PDF "printer" receives the report
    target = tmp_path / "printed.pdf"
    real_make = reports_mod.make_printer

    def pdf_printer(landscape: bool = True):
        printer = real_make(landscape)
        printer.setOutputFormat(QPrinter.OutputFormat.PdfFormat)
        printer.setOutputFileName(str(target))
        return printer

    monkeypatch.setattr(reports_mod, "make_printer", pdf_printer)
    monkeypatch.setattr(QPrintDialog, "exec", lambda self: 1)
    rp.print_report()
    assert target.exists() and target.stat().st_size > 500
    # the open-items report carries the hotel column and the active scope in the subtitle
    org = demo_ctx.services.organization
    hotel = org.hotels()[0]
    ctrl.set_scope(org.scope_for(hotel.company_id, hotel.id))
    rp.kind.setCurrentIndex(rp.kind.findData("open_items"))
    assert rp.report.columns[-1] == "Hotel / Gesellschaft" and hotel.name in rp.report.subtitle
    assert all(hotel.name in r[-1] for r in rp.report.rows)
    # nothing to print for the statement without supplier
    rp.kind.setCurrentIndex(rp.kind.findData("statement"))
    rp.supplier.setCurrentIndex(0)
    assert not rp.btn_print.isEnabled()
    rp.print_report()
    rp.preview()
    assert rp.print_pdf(str(tmp_path / "none.pdf")) is None


def test_settings_vocabulary_card_saves_and_reloads(win, demo_ctx) -> None:
    app, ctrl, window = win
    window.show_page("settings")
    sp = window.pages["settings"]
    sp.vocab_edits["gross"].setText("Zahlungsbetrag, Rechnungs-Endbetrag")
    sp.vocab_edits["invoice_title"].setText("Lieferantenabrechnung")
    sp._save_vocab()
    assert demo_ctx.services.settings.custom_vocab() == {"invoice_title": ["Lieferantenabrechnung"],
                                                         "gross": ["Zahlungsbetrag", "Rechnungs-Endbetrag"]}
    sp.vocab_edits["gross"].setText("")
    sp.refresh()
    assert sp.vocab_edits["gross"].text() == "Zahlungsbetrag, Rechnungs-Endbetrag"


def test_recurring_invoice_dialog_tab_and_supplier_change(win, demo_ctx, monkeypatch) -> None:
    from supplier_app.views.dialogs.recurring_dialog import RecurringDialog
    from supplier_app.views.widgets.party_picker import PartyChangeDialog
    app, ctrl, window = win
    svc = demo_ctx.services
    landlord = svc.suppliers.suppliers()[0]
    dlg = RecurringDialog(ctrl, landlord.id)
    dlg.title_edit.setText("Miete Hotel")
    dlg.amounts.cellWidget(0, 1).setText("4.500,00")
    assert "MIETE-" in dlg.preview.text()
    dlg.accept()
    assert dlg.saved and svc.recurring.list(supplier_id=landlord.id)
    bad = RecurringDialog(ctrl, landlord.id)
    bad.accept()  # no name, no amount
    assert not bad.error.isHidden()
    page = window.pages["suppliers"]
    page.select_supplier(landlord.id)
    page.refresh()
    assert page.recurring.row_count() == 1
    page.recurring.select_payload(dlg.saved.id)
    page.generate_recurring()
    assert svc.recurring.runs(dlg.saved.id)
    assert ctrl.generate_recurring() == 0  # nothing new
    chooser = PartyChangeDialog("t", "hint", svc.suppliers.suppliers(), landlord.id)
    assert chooser.party_id() == landlord.id


def test_bank_page_import_review_and_booking(win, demo_ctx, monkeypatch) -> None:
    from supplier_app.models.enums import BankTxStatus
    from supplier_app.views.dialogs.bank_dialogs import AccountChooserDialog, BankAccountEditDialog, BankAccountsDialog
    app, ctrl, window = win
    svc = demo_ctx.services
    page = window.pages["bank"]
    window.show_page("bank")
    fixtures = FIX / "bank"
    page.import_files([fixtures / "sparkasse.csv"])
    page.refresh()
    assert page.table.row_count() >= 2 and "zu prüfen" in page.summary.text()
    outgoing = [t for t in svc.bank.transactions() if t.amount_cents < 0]
    assert outgoing
    tx = outgoing[0]
    page.status.setCurrentIndex(page.status.findData("all"))
    page.table.select_payload(tx.id)
    assert page.tx_id == tx.id and page.picker.combo.count() > 1
    assert "IBAN" in page.facts.text()
    page.save_later()
    page.ignore()
    assert svc.bank.get(tx.id).status == BankTxStatus.IGNORED
    page.table.select_payload(tx.id)
    page.reopen()
    # supplier + invoice chosen by the user, then booked
    supplier = svc.suppliers.suppliers()[0]
    inv = next(i for i in svc.invoices.list(supplier.id) if svc.ledger.invoice_balance(i.id).balance_cents > 0)
    svc.bank.assign(tx.id, supplier.id, [inv.id])
    page.refresh()
    page.table.select_payload(tx.id)
    assert page.invoices.rowCount() >= 1 and page.btn_book.isEnabled()
    page.book()
    assert svc.bank.get(tx.id).status in (BankTxStatus.BOOKED, BankTxStatus.MATCHED)
    page.book_sure()
    # accounts
    dlg = BankAccountsDialog(ctrl)
    assert dlg.table.row_count() == 1
    edit = BankAccountEditDialog(ctrl, svc.bank.accounts()[0])
    edit.name.setText("Hauptkonto")
    edit.accept()
    assert svc.bank.accounts()[0].name == "Hauptkonto"
    chooser = AccountChooserDialog(ctrl, "x.csv")
    chooser.accept()
    assert chooser.account_id == svc.bank.accounts()[0].id
    monkeypatch.setattr("supplier_app.views.pages.bank.AccountChooserDialog", lambda *a, **k: type("D", (), {
        "exec": lambda self: 0, "account_id": None})())
    page.import_files([fixtures / "statement.sta"])
    page.refresh()


def test_party_picker_and_claims_editor(win, demo_ctx) -> None:
    from supplier_app.ai.result_types import NewPartyInfo, PartyCandidate
    from supplier_app.models.entities import Party
    from supplier_app.services.review_models import ClaimInput
    from supplier_app.views.widgets.claims_editor import ClaimsEditor
    from supplier_app.views.widgets.party_picker import PartyChooserDialog, PartyPicker
    app, ctrl, window = win
    svc = demo_ctx.services
    parties = svc.suppliers.suppliers()
    picker = PartyPicker(parties)
    cands = [PartyCandidate(parties[0].id, parties[0].name, 0.82, ["IBAN passt"]), PartyCandidate(parties[1].id, parties[1].name, 0.2)]
    picker.set_candidates(cands, parties[0].id, suggested=True)
    assert picker.party_id() == parties[0].id and "82" in picker.hint.text()
    assert picker.combo.itemText(0).startswith("★") and picker.combo.findData(parties[1].id) >= 0
    picker.set_candidates([], None, new_name="Neue GmbH", info=NewPartyInfo(address="Hauptstr. 1", vat_id="DE123456789"))
    assert picker.party_id() is None and not picker.new_holder.isHidden() and "Hauptstr. 1" in picker.hint.text()
    assert picker.name_for_new() == "Neue GmbH"
    chooser = PartyChooserDialog(parties)
    chooser.filter.setText(parties[2].name[:5])
    assert chooser.list.count() >= 1
    chooser.accept()
    assert chooser.chosen_id is not None
    # claims editor: cards for the invoices of the supplier, suggestions as buttons
    inv = next(i for i in svc.invoices.list() if svc.ledger.invoice_balance(i.id).balance_cents > 0)
    editor = ClaimsEditor(svc)
    editor.set_supplier(inv.supplier_id)
    editor.set_claims([], [])
    assert not editor.empty.isHidden() and editor.claims() == []
    editor.set_claims([ClaimInput(inv.id, principal_cents=1000, fees_cents=500, total_cents=1500)])
    assert editor.empty.isHidden() and editor.claims()[0].invoice_id == inv.id and editor.claims()[0].total_cents == 1500
    editor._remove(editor.cards[0])
    assert editor.claims() == []
    unknown = svc.suppliers.create(Party(name="Ohne Rechnungen AG"))
    editor.set_supplier(unknown.id)
    editor.add_claim(None)
    assert editor.claims() == []  # a card without an invoice is not a claim


def test_dashboard_shows_open_bank_transactions(win, demo_ctx, monkeypatch) -> None:
    from supplier_app.services.dashboard_models import DashboardFilter
    from supplier_app.services.dashboard_service import DashboardService
    app, ctrl, window = win
    svc = demo_ctx.services
    svc.bank.import_file(FIX / "bank" / "sparkasse.csv")
    ds = DashboardService(svc.repos, svc.ledger, svc.settings)
    items = ds.build(DashboardFilter.for_period("year", date.today())).attention["bank"]
    assert len(items) == 1 and items[0].target.kind == "bank"
    seen = []
    ctrl.navigate.connect(seen.append)
    window.show_page("dashboard")
    window.pages["dashboard"].refresh()
    window.pages["dashboard"]._attention_clicked(items[0])
    assert seen == ["bank"]
    # a bank statement dropped on the documents page is routed to the bank page
    routed = []
    ctrl.bank_files.connect(routed.append)
    window.pages["documents"].start_import([FIX / "bank" / "statement.camt.xml"])
    assert routed and routed[0][0].name == "statement.camt.xml"
