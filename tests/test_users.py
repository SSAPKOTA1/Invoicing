"""Users, roles, login, lockout and read-only enforcement (SQLite and PostgreSQL)."""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta

import pytest

from supplier_app.errors import AuthError, DatabaseError, DuplicateError, ValidationError
from supplier_app.models.enums import UserRole
from supplier_app.services.session import Session
from supplier_app.services.user_service import MAX_ATTEMPTS, UserService
from supplier_app.settings.local_prefs import LocalPrefs
from tests.helpers import make_scenario


def test_first_admin_login_and_roles(svc) -> None:
    users = svc.users
    assert users.needs_first_admin()
    admin = users.create_user("chef", "geheim123", UserRole.ADMIN, "Die Chefin")
    assert not users.needs_first_admin() and admin.id and admin.label == "Die Chefin"
    assert admin.password_hash != "geheim123" and len(admin.password_salt) == 32
    with pytest.raises(AuthError):
        users.login("chef", "falsch")
    with pytest.raises(AuthError):
        users.login("unbekannt", "geheim123")  # same message: no user enumeration
    logged = users.login("CHEF", "geheim123")  # user names are case-insensitive
    assert logged.last_login and svc.session.is_admin and svc.session.username == "chef"
    editor = users.create_user("anna", "passwort1", UserRole.EDITOR)
    viewer = users.create_user("max", "passwort2", UserRole.VIEWER)
    assert [u.username for u in users.users()] == ["anna", "chef", "max"]
    with pytest.raises(DuplicateError):
        users.create_user("Anna", "passwort3")
    with pytest.raises(ValidationError):
        users.create_user("x y", "passwort3")
    with pytest.raises(ValidationError):
        users.create_user("neu", "kurz")
    assert editor.role == UserRole.EDITOR and viewer.role == UserRole.VIEWER


def test_only_administrators_manage_users(svc) -> None:
    users = svc.users
    users.create_user("chef", "geheim123", UserRole.ADMIN)
    editor = users.create_user("anna", "passwort1", UserRole.EDITOR)
    session = Session(multi_user=True)
    as_editor = UserService(svc.repos, session)
    as_editor.start_session(editor)
    with pytest.raises(AuthError):
        as_editor.create_user("neu", "passwort9")
    with pytest.raises(AuthError):
        as_editor.reset_password(editor.id, "passwort9")
    with pytest.raises(AuthError):
        as_editor.update_user(editor.id, role=UserRole.ADMIN)
    with pytest.raises(AuthError):
        as_editor.delete_user(editor.id)
    as_editor.change_password(editor.id, "passwort1", "neues-passwort")  # everybody may change their own
    assert as_editor.login("anna", "neues-passwort").username == "anna"
    with pytest.raises(AuthError):
        as_editor.change_password(editor.id, "falsch", "noch-ein-passwort")


def test_last_administrator_cannot_be_removed(svc) -> None:
    users = svc.users
    admin = users.create_user("chef", "geheim123", UserRole.ADMIN)
    with pytest.raises(ValidationError):
        users.update_user(admin.id, role=UserRole.EDITOR)
    with pytest.raises(ValidationError):
        users.update_user(admin.id, active=False)
    with pytest.raises(ValidationError):
        users.delete_user(admin.id)
    second = users.create_user("zweite", "passwort1", UserRole.ADMIN)
    users.update_user(admin.id, active=False)  # now allowed: another active admin exists
    with pytest.raises(AuthError):
        users.login("chef", "geheim123")  # deactivated
    users.login("zweite", "passwort1")
    with pytest.raises(ValidationError):
        users.delete_user(second.id)  # cannot delete oneself
    users.delete_user(admin.id)
    assert [u.username for u in users.users()] == ["zweite"]


def test_lockout_after_failed_logins_and_reset(svc) -> None:
    now = [datetime(2026, 1, 1, 12, 0, 0)]
    users = UserService(svc.repos, Session(multi_user=True), clock=lambda: now[0])
    users.create_user("chef", "geheim123", UserRole.ADMIN)
    for _ in range(MAX_ATTEMPTS):
        with pytest.raises(AuthError):
            users.login("chef", "falsch")
    with pytest.raises(AuthError, match="Fehlversuche"):
        users.login("chef", "geheim123")  # locked even with the right password
    now[0] += timedelta(seconds=31)
    assert users.login("chef", "geheim123").failed_logins == 0
    user = users.users()[0]
    users.reset_password(user.id, "ganz-neues-pw")
    assert users.login("chef", "ganz-neues-pw")


def test_viewer_is_read_only_and_audit_records_the_user(svc) -> None:
    users = svc.users
    users.create_user("chef", "geheim123", UserRole.ADMIN)
    users.create_user("max", "passwort2", UserRole.VIEWER)
    users.login("chef", "geheim123")
    sc = make_scenario(svc)
    audit = svc.repos.audit.list(limit=50)
    assert any(a.action == "create" and a.entity == "invoice" and a.username == "chef" for a in audit)
    users.login("max", "passwort2")
    assert svc.repos.db.read_only
    assert svc.invoices.get(sc.invoice.id).invoice_number == "RE-2024/001"  # reading works
    with pytest.raises(DatabaseError, match="Lesen"):
        svc.invoices.create_invoice(sc.supplier.id, "RE-2", date(2024, 2, 1), gross_cents=100)
    with pytest.raises(DatabaseError, match="Lesen"):
        svc.payments.record_payment(sc.supplier.id, date(2024, 2, 1), 100, [sc.invoice.id])
    with pytest.raises(AuthError):
        users.login("max", "falsch")  # the failed-login counter is still written for read-only users
    users.logout()
    assert not svc.repos.db.read_only and svc.session.user is None
    svc.invoices.create_invoice(sc.supplier.id, "RE-2", date(2024, 2, 1), gross_cents=100)


def test_personal_settings_stay_on_this_machine(svc, tmp_path) -> None:
    from supplier_app.services.settings_service import SettingsService

    prefs = LocalPrefs(tmp_path / "prefs.json")
    shared = SettingsService(svc.repos, prefs)
    shared.set_theme("light")
    shared.set("active_scope", "h:3")
    shared.set("margin_b2b", "8")
    assert svc.repos.settings.get("theme") != "light" and svc.repos.settings.get("active_scope") is None
    assert svc.repos.settings.get("margin_b2b") == "8"  # business settings are shared
    again = SettingsService(svc.repos, LocalPrefs(tmp_path / "prefs.json"))
    assert again.theme == "light" and again.get("active_scope") == "h:3"
    (tmp_path / "prefs.json").write_text("{kaputt", encoding="utf-8")
    assert SettingsService(svc.repos, LocalPrefs(tmp_path / "prefs.json")).theme == "dark"  # unreadable file -> defaults


def test_change_counter_moves_when_data_changes(svc) -> None:
    db = svc.repos.db
    if db.backend != "postgres":
        pytest.skip("SQLite reports changes of other connections only (PRAGMA data_version)")
    before = db.data_version()
    make_scenario(svc)
    assert db.data_version() != before
    svc.users.create_user("chef", "geheim123", UserRole.ADMIN)
    svc.users.login("chef", "geheim123")
    make_scenario(svc, number="RE-X")
    assert db.data_changed_by() == "chef"


def test_server_documents_backup_restore_and_transfer(storage, tmp_path) -> None:
    """Files live in the database; table backups restore a server; a local database can be moved to a server."""
    import zipfile

    from supplier_app.backup.dump import copy_database, is_empty
    from supplier_app.backup.service import BackupService
    from supplier_app.bootstrap import open_memory_storage
    from supplier_app.errors import BackupError
    from supplier_app.services.container import build_services
    from supplier_app.settings.local_prefs import LocalPrefs

    if storage.db.backend != "postgres":
        pytest.skip("server mode only")
    svc = build_services(storage, multi_user=True, prefs=LocalPrefs(tmp_path / "prefs.json"))
    sc = make_scenario(svc)
    src = tmp_path / "rechnung.txt"
    src.write_text("Rechnung RE-2024/001 Zahlungserinnerung", encoding="utf-8")
    doc, created = svc.documents.store_file(src)
    assert created and svc.repos.documents.load_file(doc.id) == src.read_bytes()
    cached = svc.documents.file_path(doc)
    cached.unlink()  # another PC has no cache: the file is fetched from the database
    assert svc.documents.file_path(doc).read_bytes() == src.read_bytes()
    same, again = svc.documents.store_file(src)
    assert same.id == doc.id and not again
    svc.users.create_user("chef", "geheim123", UserRole.ADMIN)
    svc.payments.record_payment(sc.supplier.id, date(2024, 2, 1), 40000, [sc.invoice.id])
    balance = svc.ledger.invoice_balance(sc.invoice.id).balance_cents

    zp = svc.backup.create_backup(tmp_path / "server.zip")
    manifest = BackupService.verify_backup(zp)
    assert manifest["rows"]["ledger_entries"] >= 2 and manifest["rows"]["document_files"] == 1
    svc.payments.record_payment(sc.supplier.id, date(2024, 2, 2), 10000, [sc.invoice.id])  # after the backup
    result = svc.backup.restore_backup(zp)
    assert result.documents == 1
    assert svc.ledger.invoice_balance(sc.invoice.id).balance_cents == balance  # state of the backup
    assert svc.users.users()[0].username == "chef"
    new = svc.invoices.create_invoice(sc.supplier.id, "NACH-RESTORE", date(2024, 3, 1), gross_cents=500)
    assert new.id > sc.invoice.id  # identity counters continue behind the restored ids
    bad = tmp_path / "bad.zip"
    with zipfile.ZipFile(zp) as zin, zipfile.ZipFile(bad, "w") as zout:
        for item in zin.namelist():
            data = zin.read(item)
            if item == "manifest.json":
                m = json.loads(data)
                m["rows"]["parties"] += 1
                data = json.dumps(m).encode()
            zout.writestr(item, data)
    with pytest.raises(BackupError):
        BackupService.verify_backup(bad)  # row count no longer matches

    # transfer a local database into an empty server database
    local = open_memory_storage()
    lsvc = build_services(local)
    lsc = make_scenario(lsvc)
    lsvc.payments.record_payment(lsc.supplier.id, date(2024, 2, 1), 40000, [lsc.invoice.id])
    lsvc.pin.set_pin("1234")
    lsvc.settings.set_theme("light")
    assert not is_empty(local.db)
    with pytest.raises(BackupError):
        copy_database(local.db, storage.db)  # server already has data
    from supplier_app.backup.dump import clear_database

    clear_database(storage.db)
    rows = copy_database(local.db, storage.db)
    assert rows > 10
    moved = build_services(storage, multi_user=True, prefs=LocalPrefs(tmp_path / "prefs2.json"))
    assert moved.ledger.invoice_balance(lsc.invoice.id).balance_cents == lsvc.ledger.invoice_balance(lsc.invoice.id).balance_cents
    assert not moved.pin.enabled and moved.settings.theme == "dark"  # personal settings and the PIN stay behind
    assert moved.invoices.create_invoice(lsc.supplier.id, "NEU", date(2024, 3, 1), gross_cents=500).id > lsc.invoice.id
    local.close()
