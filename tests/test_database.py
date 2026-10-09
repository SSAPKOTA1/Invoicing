from __future__ import annotations

import sqlite3

import pytest

from supplier_app.database.connection import Database
from supplier_app.errors import DatabaseError


def make_db() -> Database:
    db = Database(":memory:").connect()
    db.execute("CREATE TABLE t(id INTEGER PRIMARY KEY, v TEXT UNIQUE)")
    return db


def test_transaction_commit_and_rollback() -> None:
    db = make_db()
    with db.transaction():
        db.insert("INSERT INTO t(v) VALUES (?)", ("a",))
    with pytest.raises(RuntimeError), db.transaction():
        db.insert("INSERT INTO t(v) VALUES (?)", ("b",))
        raise RuntimeError("boom")
    assert db.scalar("SELECT COUNT(*) FROM t") == 1
    assert not db.in_transaction


def test_nested_transaction_savepoint() -> None:
    db = make_db()
    with db.transaction():
        db.insert("INSERT INTO t(v) VALUES (?)", ("a",))
        with pytest.raises(sqlite3.IntegrityError), db.transaction():
            db.insert("INSERT INTO t(v) VALUES (?)", ("b",))
            db.insert("INSERT INTO t(v) VALUES (?)", ("a",))
        assert db.in_transaction
        db.insert("INSERT INTO t(v) VALUES (?)", ("c",))
    assert [r[0] for r in db.query_all("SELECT v FROM t ORDER BY v")] == ["a", "c"]


def test_helpers_and_foreign_keys() -> None:
    db = make_db()
    assert db.scalar("SELECT 5") == 5
    assert db.scalar("SELECT NULL", default=7) == 7
    assert db.query_one("SELECT * FROM t") is None
    assert db.scalar("PRAGMA foreign_keys") == 1
    db.executemany("INSERT INTO t(v) VALUES (?)", [("x",), ("y",)])
    assert db.scalar("SELECT COUNT(*) FROM t") == 2
    assert db.integrity_ok()
    assert db.schema_version() == 0


def test_not_open_raises() -> None:
    db = Database(":memory:")
    with pytest.raises(DatabaseError):
        db.execute("SELECT 1")
    db.connect().close()
    db.close()


def test_locked_database_gives_friendly_error(tmp_path) -> None:
    p = tmp_path / "l.db"
    a = Database(p, timeout=0.1).connect()
    b = Database(p, timeout=0.1).connect()
    a.execute("CREATE TABLE t(x)")
    with a.transaction():
        a.execute("INSERT INTO t VALUES (1)")
        with pytest.raises(DatabaseError) as err, b.transaction():
            pass
        assert "gesperrt" in str(err.value)
    a.close()
    b.close()


def test_open_failure_is_friendly(tmp_path) -> None:
    with pytest.raises(DatabaseError):
        Database(tmp_path).connect()  # a directory is not a database
