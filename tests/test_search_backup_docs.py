from __future__ import annotations

import sqlite3
import zipfile
from datetime import date

import pytest

from supplier_app.backup.service import BackupService
from supplier_app.errors import BackupError, DocumentError
from supplier_app.models.entities import Document
from supplier_app.models.enums import DunningLevel, ReferenceType, ReviewStatus
from supplier_app.services.dunning_service import NoticeDraft
from supplier_app.services.ledger import NoticeClaim
from tests.helpers import make_scenario


@pytest.fixture()
def booked(svc):
    sc = make_scenario(svc)
    doc = svc.repos.documents.add(Document(stored_path="m.pdf", sha256="b" * 64, original_name="Mahnung_2.pdf",
                                           ocr_text="Zahlungserinnerung Aktenzeichen INK-2024-77881 Rechnung RE-2024/001"))
    svc.dunning.book_notice(NoticeDraft(
        sc.supplier.id, date(2024, 3, 1), DunningLevel.FIRST, [NoticeClaim(sc.invoice.id, 100000, fees_cents=500)],
        document_id=doc.id,
        references=[(ReferenceType.PROCESSING_NUMBER, "4711/A")]))
    svc.dunning.book_notice(NoticeDraft(
        sc.agency.id, date(2024, 3, 20), DunningLevel.COLLECTION, [NoticeClaim(sc.invoice.id, 100000, fees_cents=500)],
        references=[(ReferenceType.FILE_NUMBER, "INK-2024-77881")]))
    return sc


@pytest.mark.parametrize("query", [
    "Müller Bürobedarf", "mueller buero", "Mueller", "RE-2024/001", "re2024001", "RE 2024 001", "4711/A",
    "4711a", "4711 A", "INK-2024-77881", "ink 2024 77881", "DE89 3704 0044 0532 0130 00", "1.000,00", "1000,00 €",
])
def test_every_way_finds_the_same_invoice(svc, booked, query) -> None:
    res = svc.search.search(query)
    assert booked.invoice.id in res.invoice_ids(), query


def test_search_groups_and_documents(svc, booked) -> None:
    res = svc.search.search("Zahlungserinnerung")
    assert res.documents and res.documents[0].snippet
    res = svc.search.search("Müller")
    assert res.suppliers and res.cases and res.invoices
    assert svc.search.search("   ").total == 0
    assert svc.search.search("völlig unbekannt xyz").total == 0
    res = svc.search.search("INK-2024-77881")
    assert res.cases and res.documents
    assert svc.search.search('"').total == 0


def test_search_by_payment_amount(svc, booked) -> None:
    svc.payments.record_payment(booked.supplier.id, date(2024, 4, 1), 12345, [booked.invoice.id])
    assert booked.invoice.id in svc.search.search("123,45").invoice_ids()


def test_backup_restore_roundtrip(file_svc, file_storage) -> None:
    svc = file_svc
    sc = make_scenario(svc)
    src = file_storage.paths.root / "scan.txt"
    src.write_text("Rechnung RE-2024/001", encoding="utf-8")
    doc, created = svc.documents.store_file(src)
    assert created and svc.documents.file_path(doc).exists()
    zip_path = svc.backup.create_backup()
    manifest = BackupService.verify_backup(zip_path)
    assert manifest["schema_version"] == 3 and doc.stored_path in manifest["documents"]
    # change state after the backup
    svc.payments.record_payment(sc.supplier.id, date(2024, 4, 1), 5000, [sc.invoice.id])
    svc.documents.file_path(doc).unlink()
    assert svc.ledger.invoice_balance(sc.invoice.id).balance_cents == 95000
    result = svc.backup.restore_backup(zip_path)
    assert result.documents == 1 and result.safety_backup.exists()
    assert svc.ledger.invoice_balance(sc.invoice.id).balance_cents == 100000
    assert svc.documents.file_path(doc).exists()
    assert file_storage.db.integrity_ok()


def test_backup_rejects_tampering_and_garbage(file_svc, file_storage, tmp_path) -> None:
    make_scenario(file_svc)
    good = file_svc.backup.create_backup(tmp_path / "out")
    assert good.parent == tmp_path / "out"
    # tamper with the database inside the zip
    bad = tmp_path / "bad.zip"
    with zipfile.ZipFile(good) as zin, zipfile.ZipFile(bad, "w") as zout:
        for item in zin.infolist():
            data = zin.read(item.filename)
            if item.filename == "supplier.db":
                data = data[:-10] + b"XXXXXXXXXX"
            zout.writestr(item, data)
    with pytest.raises(BackupError):
        BackupService.verify_backup(bad)
    garbage = tmp_path / "garbage.zip"
    garbage.write_bytes(b"not a zip")
    with pytest.raises(BackupError):
        BackupService.verify_backup(garbage)
    empty = tmp_path / "empty.zip"
    with zipfile.ZipFile(empty, "w") as z:
        z.writestr("x.txt", "x")
    with pytest.raises(BackupError):
        BackupService.verify_backup(empty)
    slip = tmp_path / "slip.zip"
    with zipfile.ZipFile(slip, "w") as z:
        z.writestr("../evil.txt", "x")
    with pytest.raises(BackupError):
        BackupService.verify_backup(slip)
    with pytest.raises(BackupError):
        file_svc.backup.restore_backup(garbage)
    # DB still usable after failed restore
    assert file_storage.db.integrity_ok()


def test_restore_of_older_schema_gets_migrated(file_svc, file_storage, tmp_path) -> None:
    from supplier_app.database.migrator import migrate
    old_db = tmp_path / "old" / "supplier.db"
    migrate(old_db, None, target_version=1)
    import hashlib
    import json
    zp = tmp_path / "old.zip"
    with zipfile.ZipFile(zp, "w") as z:
        z.write(old_db, "supplier.db")
        z.writestr("manifest.json", json.dumps({
            "schema_version": 1, "db_sha256": hashlib.sha256(old_db.read_bytes()).hexdigest(), "documents": {}}))
    file_svc.backup.restore_backup(zp)
    assert file_storage.db.schema_version() == 3


def test_document_store_rules(file_svc, tmp_path) -> None:
    docs = file_svc.documents
    f = tmp_path / "a b.txt"
    f.write_text("hallo", encoding="utf-8")
    d1, created = docs.store_file(f)
    d2, created2 = docs.store_file(f)
    assert created and not created2 and d1.id == d2.id
    with pytest.raises(DocumentError):
        docs.store_file(tmp_path / "missing.pdf")
    empty = tmp_path / "e.pdf"
    empty.write_bytes(b"")
    with pytest.raises(DocumentError):
        docs.store_file(empty)
    exe = tmp_path / "x.exe"
    exe.write_bytes(b"MZ")
    with pytest.raises(DocumentError):
        docs.store_file(exe)
    docs.set_review_status(d1.id, ReviewStatus.ACCEPTED)
    assert docs.list(ReviewStatus.ACCEPTED)[0].id == d1.id
    with pytest.raises(DocumentError):
        docs.get(999)


def test_ledger_invariants_hold(svc) -> None:
    sc = make_scenario(svc, gross=100000)
    svc.invoices.create_invoice(sc.supplier.id, "RE-2", date(2024, 2, 1), gross_cents=77777)
    svc.dunning.book_notice(NoticeDraft(sc.supplier.id, date(2024, 3, 1), DunningLevel.FIRST,
                                        [NoticeClaim(sc.invoice.id, 100000, fees_cents=500, interest_cents=210)]))
    svc.payments.record_payment(sc.supplier.id, date(2024, 3, 5), 123456, [sc.invoice.id])
    total_entries = svc.repos.db.scalar("SELECT SUM(amount_cents) FROM ledger_entries")
    by_invoice = sum(s.balance.balance_cents for s in svc.ledger.invoice_states())
    unapplied = sum(svc.repos.ledger.unapplied_by_supplier().values())
    assert total_entries == by_invoice + unapplied == svc.ledger.supplier_balance(sc.supplier.id).total_cents
    for state in svc.ledger.invoice_states():
        b = state.balance
        assert b.balance_cents == b.open_costs_cents + b.open_interest_cents + b.open_principal_cents
        assert b.balance_cents == svc.ledger.invoice_balance(state.invoice.id).balance_cents
    sqlite3.connect(":memory:").close()
