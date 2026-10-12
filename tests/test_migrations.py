from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from supplier_app.database.connection import Database
from supplier_app.database.migrations import ALL_MIGRATIONS, LATEST_VERSION, Migration
from supplier_app.database.migrator import migrate, split_statements
from supplier_app.errors import DatabaseError, MigrationError


def tables(path: Path) -> set[str]:
    con = sqlite3.connect(path)
    try:
        return {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type IN ('table','view')")}
    finally:
        con.close()


def test_empty_db_migrates_to_latest(tmp_path: Path) -> None:
    db_path = tmp_path / "a.db"
    assert migrate(db_path, tmp_path / "bk") == LATEST_VERSION
    t = tables(db_path)
    for name in ("parties", "invoices", "ledger_entries", "documents", "document_references", "document_fts",
                 "schema_version", "audit_log", "interest_rates", "cases", "dunning_notices", "payments"):
        assert name in t
    # idempotent
    assert migrate(db_path, tmp_path / "bk") == LATEST_VERSION


@pytest.mark.parametrize("start", [m.version for m in ALL_MIGRATIONS[:-1]])
def test_upgrade_from_every_earlier_version(tmp_path: Path, start: int) -> None:
    db_path = tmp_path / "b.db"
    assert migrate(db_path, tmp_path / "bk", target_version=start) == start
    con = sqlite3.connect(db_path)
    con.execute("INSERT INTO parties(role,name,name_norm,created_at) VALUES ('supplier','Alt GmbH','alt','2024-01-01')")
    con.execute(
        "INSERT INTO documents(stored_path,sha256,original_name,ocr_text,created_at) VALUES ('x',?,?,?,'2024-01-01')",
        ("a" * 64, "scan.pdf", "Rechnung Testtext"),
    )
    con.commit()
    con.close()
    assert migrate(db_path, tmp_path / "bk") == LATEST_VERSION
    with Database(db_path) as db:
        assert db.scalar("SELECT name FROM parties") == "Alt GmbH"
        # FTS rebuilt for pre-existing rows
        assert db.query_all("SELECT rowid FROM document_fts WHERE document_fts MATCH 'Testtext'")
    assert list((tmp_path / "bk").glob("pre-migration-v*.db"))


def test_failed_migration_rolls_back_and_restores(tmp_path: Path) -> None:
    db_path = tmp_path / "c.db"
    migrate(db_path, tmp_path / "bk", target_version=2)
    bad = Migration(99, "bad", "CREATE TABLE ok_table(x INTEGER); INSERT INTO no_such_table VALUES (1);")
    with pytest.raises(MigrationError):
        migrate(db_path, tmp_path / "bk", migrations=[*ALL_MIGRATIONS[:2], bad])
    assert "ok_table" not in tables(db_path)
    con = sqlite3.connect(db_path)
    assert con.execute("SELECT MAX(version) FROM schema_version").fetchone()[0] == 2
    con.close()


def test_failed_migration_on_fresh_db_leaves_nothing(tmp_path: Path) -> None:
    db_path = tmp_path / "d.db"
    bad = Migration(1, "bad", "CREATE TABLE t(x); SELECT * FROM missing_table_zz;")
    with pytest.raises(MigrationError):
        migrate(db_path, tmp_path / "bk", migrations=[bad])
    assert "t" not in tables(db_path)


def test_newer_database_is_rejected(tmp_path: Path) -> None:
    db_path = tmp_path / "e.db"
    migrate(db_path, tmp_path / "bk")
    con = sqlite3.connect(db_path)
    con.execute("INSERT INTO schema_version VALUES (999,'future','x')")
    con.commit()
    con.close()
    with pytest.raises(DatabaseError):
        migrate(db_path, tmp_path / "bk")


def test_split_statements_keeps_triggers() -> None:
    sql = "CREATE TABLE a(x); CREATE TRIGGER t BEFORE UPDATE ON a BEGIN SELECT 1; SELECT 2; END; INSERT INTO a VALUES (1);"
    assert len(split_statements(sql)) == 3


def test_ledger_is_append_only(file_storage) -> None:
    db = file_storage.db
    pid = db.insert("INSERT INTO parties(role,name,name_norm,created_at) VALUES ('supplier','S','s','2024-01-01')")
    eid = db.insert(
        "INSERT INTO ledger_entries(entry_date,supplier_id,entry_type,category_type,amount_cents,created_at)"
        " VALUES ('2024-01-01',?,'INVOICE','INVOICE',100,'x')", (pid,))
    with pytest.raises(sqlite3.DatabaseError):
        db.execute("UPDATE ledger_entries SET amount_cents=5 WHERE id=?", (eid,))
    with pytest.raises(sqlite3.DatabaseError):
        db.execute("DELETE FROM ledger_entries WHERE id=?", (eid,))


def test_ledger_check_constraints(file_storage) -> None:
    db = file_storage.db
    pid = db.insert("INSERT INTO parties(role,name,name_norm,created_at) VALUES ('supplier','S','s','2024-01-01')")
    base = ("INSERT INTO ledger_entries(entry_date,supplier_id,entry_type,category_type,amount_cents,created_at)"
            " VALUES ('2024-01-01',?,?,?,?,'x')")
    with pytest.raises(sqlite3.IntegrityError):
        db.execute(base, (pid, "PAYMENT", "PAYMENT", 100))  # payment must be negative
    with pytest.raises(sqlite3.IntegrityError):
        db.execute(base, (pid, "INVOICE", "INVOICE", 0))
    with pytest.raises(sqlite3.IntegrityError):
        db.execute(base, (pid, "REVERSAL", "INVOICE", -5))  # reversal needs reverses_entry_id
    with pytest.raises(sqlite3.IntegrityError):
        db.execute(base, (pid, "BOGUS", "INVOICE", 5))
