"""Shared-folder mode (no server): several PCs use one folder at the same time."""

from __future__ import annotations

import sqlite3
import threading
from datetime import date, timedelta

import pytest

from supplier_app.backup.auto import ensure_daily_backup
from supplier_app.backup.transfer import transfer_to_shared
from supplier_app.bootstrap import open_memory_storage, open_storage
from supplier_app.errors import BackupError, DatabaseError, DuplicateError, ValidationError
from supplier_app.main import build_context
from supplier_app.models.enums import UserRole
from supplier_app.services.container import build_services
from supplier_app.settings.connection import MODE_SHARED, ConnectionConfig, check_shared_folder
from supplier_app.settings.paths import AppPaths
from supplier_app.settings.shared import SessionRegistry
from tests.helpers import make_scenario


def _pc(tmp_path, shared, name):
    """One PC: own local folder, same shared folder."""
    cfg = ConnectionConfig(mode=MODE_SHARED, shared_path=str(shared))
    return build_context(AppPaths(tmp_path / f"pc-{name}").ensure(), cfg)


def test_shared_folder_checks(tmp_path) -> None:
    assert check_shared_folder(str(tmp_path)) == tmp_path
    with pytest.raises(ValidationError, match="nicht erreichbar"):
        check_shared_folder(str(tmp_path / "gibt-es-nicht"))
    with pytest.raises(ValidationError, match="angeben"):
        check_shared_folder("  ")
    for bad in ("OneDrive - Firma", "Dropbox", "Google Drive", "iCloudDrive"):
        folder = tmp_path / bad / "Daten"
        folder.mkdir(parents=True)
        with pytest.raises(ValidationError, match="Cloud"):
            check_shared_folder(str(folder))
    cfg = ConnectionConfig(mode=MODE_SHARED, shared_path=str(tmp_path))
    cfg.save(tmp_path / "local")
    loaded = ConnectionConfig.load(tmp_path / "local")
    assert loaded.is_shared and loaded.is_multi_user and not loaded.is_server and loaded.shared_path == str(tmp_path)
    assert loaded.server_label == str(tmp_path)


def test_two_pcs_share_one_folder(tmp_path) -> None:
    shared = tmp_path / "share"
    shared.mkdir()
    a, b = _pc(tmp_path, shared, "a"), _pc(tmp_path, shared, "b")
    try:
        assert a.multi_user and a.paths.root == shared and a.paths.local == tmp_path / "pc-a"
        assert a.paths.logs.parent == tmp_path / "pc-a"  # logs and exports stay on the PC
        assert a.storage.db.shared and a.storage.db.scalar("PRAGMA journal_mode") == "delete"  # no WAL on a network share
        assert not a.services.documents.files_in_database
        a.services.users.create_user("anna", "passwort1", UserRole.ADMIN)
        a.services.users.login("anna", "passwort1")
        assert [u.username for u in b.services.users.users()] == ["anna"]  # visible on the other PC at once
        b.services.users.create_user("ben", "passwort2", UserRole.EDITOR)
        b.services.users.login("ben", "passwort2")
        before = a.storage.db.data_version()
        sc = make_scenario(b.services)
        assert a.storage.db.data_version() != before  # colleague's change is detected
        assert a.storage.db.data_changed_by() == "ben"
        assert a.services.invoices.get(sc.invoice.id).invoice_number == "RE-2024/001"
        # document files live in the shared folder
        src = tmp_path / "scan.txt"
        src.write_text("Rechnung Nr. 5", encoding="utf-8")
        doc, _ = a.services.documents.store_file(src)
        assert b.services.documents.file_path(b.services.documents.get(doc.id)).read_text(encoding="utf-8") == "Rechnung Nr. 5"
        assert (shared / "documents").is_dir() and not (tmp_path / "pc-a" / "documents" / doc.stored_path).exists()
        assert (shared / "backups" / "auto").is_dir()  # daily safety copy
        assert any(e.username == "ben" for e in a.services.repos.audit.list(limit=20))
    finally:
        a.close()
        b.close()


def test_simultaneous_bookings_from_several_pcs(tmp_path) -> None:
    """Every PC (thread) opens its own connection to the shared file, like separate computers would."""
    shared = tmp_path / "share"
    shared.mkdir()
    first = _pc(tmp_path, shared, "first")
    sc = make_scenario(first.services, gross=100000)
    n = 5
    barrier = threading.Barrier(n)
    results: list = [None] * n

    def work(i: int, action) -> None:
        ctx = _pc(tmp_path, shared, f"w{i}")
        try:
            barrier.wait(60)
            results[i] = action(ctx.services)
        except Exception as exc:  # noqa: BLE001
            results[i] = exc
        finally:
            ctx.close()

    try:
        def run(action) -> list:
            threads = [threading.Thread(target=work, args=(i, action)) for i in range(n)]
            [t.start() for t in threads]
            [t.join(180) for t in threads]
            return list(results)

        paid = run(lambda s: s.payments.record_payment(sc.supplier.id, date(2024, 2, 1), 100000, [sc.invoice.id]))
        assert all(not isinstance(r, Exception) for r in paid), paid
        bal = first.services.ledger.invoice_balance(sc.invoice.id)
        assert bal.balance_cents == 0 and bal.paid_cents == 100000  # paid exactly once
        assert first.services.ledger.supplier_balance(sc.supplier.id).total_cents == -400000
        barrier.reset()
        created = run(lambda s: s.invoices.create_invoice(sc.supplier.id, "DOPPELT", date(2024, 3, 1), gross_cents=100))
        assert sum(1 for o in created if not isinstance(o, Exception)) == 1
        assert all(isinstance(o, DuplicateError) for o in created if isinstance(o, Exception))
    finally:
        first.close()


def test_daily_backup_is_created_once_pruned_and_a_damaged_file_is_detected(tmp_path) -> None:
    st = open_storage(AppPaths(tmp_path / "data"), shared=True)
    folder = tmp_path / "bk"
    try:
        make_scenario(build_services(st))
        day = date(2026, 1, 1)
        first = ensure_daily_backup(st.db, folder, keep=3, today=day)
        assert first is not None and first.exists()
        assert ensure_daily_backup(st.db, folder, keep=3, today=day) is None  # only once per day
        for i in range(1, 6):
            ensure_daily_backup(st.db, folder, keep=3, today=day + timedelta(days=i))
        names = sorted(p.name for p in folder.glob("supplier-*.db"))
        assert names == ["supplier-2026-01-04.db", "supplier-2026-01-05.db", "supplier-2026-01-06.db"]
        con = sqlite3.connect(folder / names[-1])
        assert con.execute("SELECT COUNT(*) FROM invoices").fetchone()[0] == 1  # a usable copy of the data
        con.close()
        assert ensure_daily_backup(st.db, tmp_path / "bk" / "x" / "y", today=day) is not None
    finally:
        st.close()
    # a damaged database file is reported with the way out instead of being used
    db_file = tmp_path / "data" / "supplier.db"
    raw = bytearray(db_file.read_bytes())
    for i in range(4096 * 2, min(len(raw), 4096 * 6)):
        raw[i] = 0xFF
    db_file.write_bytes(bytes(raw))
    with pytest.raises((DatabaseError, sqlite3.DatabaseError)):
        st2 = open_storage(AppPaths(tmp_path / "data"), shared=True)
        st2.db.scalar("SELECT COUNT(*) FROM ledger_entries")
        st2.close()


def test_session_registry_shows_colleagues_and_ignores_stale_ones(tmp_path) -> None:
    one, two = SessionRegistry(tmp_path), SessionRegistry(tmp_path, stale_seconds=1)
    two.pid = one.pid + 1
    two._file = two.dir / "other.json"
    one.register("anna")
    two.register("ben")
    assert [d["user"] for d in one.others()] == ["ben"] and one.others_label() == [f"ben ({two.host})"]
    assert len(one.active()) == 2
    import json
    import time

    data = json.loads(two._file.read_text())
    data["seen"] = time.time() - 120  # a PC that crashed: no heartbeat for more than the 90 s limit
    two._file.write_text(json.dumps(data))
    assert one.others() == []
    one.unregister()
    assert one.active() == []
    (tmp_path / "sessions" / "kaputt.json").write_text("{", encoding="utf-8")
    assert one.active() == []


def test_restore_is_refused_while_colleagues_are_connected(tmp_path) -> None:
    shared = tmp_path / "share"
    shared.mkdir()
    a, b = _pc(tmp_path, shared, "a"), _pc(tmp_path, shared, "b")
    try:
        a.services.users.create_user("anna", "passwort1", UserRole.ADMIN)
        a.services.users.login("anna", "passwort1")
        zp = a.services.backup.create_backup(tmp_path / "bk.zip")
        colleague = SessionRegistry(shared)
        colleague.pid += 1  # another program instance (in real life another PC)
        colleague._file = colleague.dir / "ben.json"
        colleague.register("ben")  # a colleague is working
        with pytest.raises(BackupError, match="andere Benutzer"):
            a.services.backup.restore_backup(zp)
    finally:
        a.close()
        b.close()


def test_transfer_local_data_to_a_shared_folder(tmp_path) -> None:
    local = open_storage(AppPaths(tmp_path / "local").ensure())
    try:
        svc = build_services(local)
        sc = make_scenario(svc)
        src = tmp_path / "beleg.txt"
        src.write_text("Rechnung", encoding="utf-8")
        doc, _ = svc.documents.store_file(src)
        shared = tmp_path / "share"
        shared.mkdir()
        assert transfer_to_shared(local, shared) == 2
        with pytest.raises(BackupError, match="bereits"):
            transfer_to_shared(local, shared)
        cfg = ConnectionConfig(mode=MODE_SHARED, shared_path=str(shared))
        ctx = build_context(AppPaths(tmp_path / "pc").ensure(), cfg)
        try:
            assert ctx.services.users.needs_first_admin()
            assert ctx.services.invoices.get(sc.invoice.id).invoice_number == "RE-2024/001"
            assert ctx.services.documents.file_path(ctx.services.documents.get(doc.id)).read_text(encoding="utf-8") == "Rechnung"
        finally:
            ctx.close()
        mem = open_memory_storage()
        with pytest.raises(BackupError):
            transfer_to_shared(type("S", (), {"db": type("D", (), {"backend": "postgres"})(), "paths": None})(), shared)
        mem.close()
    finally:
        local.close()


def test_separate_programs_book_into_the_same_file(tmp_path) -> None:
    """Real separate processes (like programs on different PCs), not threads, pay the same invoice at once."""
    import subprocess
    import sys
    import textwrap

    shared = tmp_path / "share"
    shared.mkdir()
    first = _pc(tmp_path, shared, "first")
    sc = make_scenario(first.services, gross=100000)
    script = tmp_path / "worker.py"
    script.write_text(textwrap.dedent(f"""
        import sys, time
        from datetime import date
        from supplier_app.main import build_context
        from supplier_app.settings.connection import ConnectionConfig
        from supplier_app.settings.paths import AppPaths
        name = sys.argv[1]
        cfg = ConnectionConfig(mode="shared", shared_path={str(shared)!r})
        ctx = build_context(AppPaths(__import__("pathlib").Path({str(tmp_path)!r}) / ("pc-" + name)).ensure(), cfg)
        try:
            go = __import__("pathlib").Path({str(tmp_path / "go")!r})
            while not go.exists():
                time.sleep(0.02)
            ctx.services.payments.record_payment({sc.supplier.id}, date(2024, 2, 1), 100000, [{sc.invoice.id}])
        finally:
            ctx.close()
    """), encoding="utf-8")
    import os

    env = {**os.environ, "QT_QPA_PLATFORM": "offscreen", "PYTHONPATH": os.getcwd()}
    procs = [subprocess.Popen([sys.executable, str(script), f"p{i}"], env=env, stderr=subprocess.PIPE) for i in range(4)]
    try:
        import time

        time.sleep(4)  # let every program start and open the file
        (tmp_path / "go").write_text("go")
        outputs = [p.communicate(timeout=120)[1].decode() for p in procs]
        assert all(p.returncode == 0 for p in procs), outputs
        bal = first.services.ledger.invoice_balance(sc.invoice.id)
        assert bal.balance_cents == 0 and bal.paid_cents == 100000
        assert first.services.ledger.supplier_balance(sc.supplier.id).total_cents == -300000
    finally:
        for p in procs:
            if p.poll() is None:
                p.kill()
        first.close()


def test_shared_mode_screens_dialogs_and_start_flow(tmp_path, monkeypatch) -> None:
    pytest.importorskip("PySide6")
    from PySide6.QtCore import QEvent
    from PySide6.QtWidgets import QApplication

    from supplier_app.selfcheck_ui import make_window
    from supplier_app.views import app as app_module
    from supplier_app.views.dialogs.connection_dialog import ConnectionDialog

    QApplication.instance() or QApplication([])
    shared = tmp_path / "share"
    shared.mkdir()
    dlg = ConnectionDialog(ConnectionConfig())
    assert dlg.local.isChecked() and not dlg.shared_path.isEnabled()
    dlg.shared.setChecked(True)
    assert dlg.shared_path.isEnabled() and not dlg.host.isEnabled()
    dlg.shared_path.setText(str(tmp_path / "gibt-es-nicht"))
    dlg.test()
    assert not dlg.error.isHidden() and "nicht erreichbar" in dlg.error.text()
    dlg.shared_path.setText(str(shared))
    dlg.test()
    assert not dlg.info.isHidden()
    dlg.accept()
    assert dlg.result_config is not None and dlg.result_config.is_shared and dlg.result_config.shared_path == str(shared)

    paths = AppPaths(tmp_path / "pc").ensure()
    dlg.result_config.save(paths.local)
    ctx = app_module.open_context(paths)
    assert ctx is not None and ctx.multi_user and ctx.config.is_shared
    try:
        monkeypatch.setattr("supplier_app.views.app.FirstAdminDialog.exec", lambda self: 1)
        assert app_module.sign_in(ctx) == "ok"
        ctx.services.users.create_user("chef", "geheim123", UserRole.ADMIN)
        ctx.services.users.login("chef", "geheim123")
        app, ctrl, window = make_window(ctx)
        window.show()
        try:
            ctrl.start_polling(60_000)
            assert ctx.registry is not None and ctx.registry.active()[0]["user"] == "chef"
            window.show_page("settings")
            sp = window.pages["settings"]
            assert "gemeinsamer Ordner" in sp.db_info.text() and str(shared) in sp.db_info.text()
            assert sp.users_card.isVisible() and not sp.security_card.isVisible() and not sp.btn_transfer_shared.isVisible()
            # a colleague on another PC books something: this window refreshes
            other = _pc(tmp_path, shared, "kollege")
            try:
                other.services.users.login("chef", "geheim123")
                make_scenario(other.services)
                assert ctrl.poll_changes() is True
            finally:
                other.close()
        finally:
            window.close()
            window.deleteLater()
            ctrl.shutdown()
            for top in QApplication.topLevelWidgets():
                top.deleteLater()
            QApplication.instance().processEvents()
            QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        assert ctx.registry.active() == []  # leaving the program removes the heartbeat
    finally:
        ctx.close()


def test_program_folder_configures_every_pc(tmp_path, monkeypatch) -> None:
    """The program in a shared folder: one connection.json next to it, a PC's own setting still wins."""
    program = tmp_path / "Programm" / "SupplierApp"
    program.mkdir(parents=True)
    shared = tmp_path / "Daten"
    shared.mkdir()
    monkeypatch.setenv("SUPPLIERAPP_PROGRAM_DIR", str(program))
    ConnectionConfig(mode=MODE_SHARED, shared_path=str(shared)).save_for_all_pcs()
    assert (program / "connection.json").exists()
    fresh_pc = ConnectionConfig.load(tmp_path / "pc-neu")  # nothing saved on this PC yet
    assert fresh_pc.is_shared and fresh_pc.shared_path == str(shared)
    ConnectionConfig().save(tmp_path / "pc-lokal")  # a PC that was set to local on purpose keeps that
    assert not ConnectionConfig.load(tmp_path / "pc-lokal").is_shared
    with pytest.raises(ValidationError, match="Passwort"):
        ConnectionConfig(mode="server", host="x").save_for_all_pcs()
    monkeypatch.delenv("SUPPLIERAPP_PROGRAM_DIR")
    with pytest.raises(ValidationError, match="Programmordner"):
        ConnectionConfig(mode=MODE_SHARED, shared_path=str(shared)).save_for_all_pcs()  # not a packaged program (tests)
