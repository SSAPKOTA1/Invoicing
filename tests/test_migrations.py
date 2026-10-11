"""Schema migrations on PostgreSQL: fresh database, repeated runs, failures, newer schema, ledger protection."""

from __future__ import annotations

import threading

import pytest

from supplier_app.database.errors import INTEGRITY_ERRORS
from supplier_app.database.migrations import ALL_MIGRATIONS, LATEST_VERSION, Migration
from supplier_app.database.migrator import migrate
from supplier_app.database.pg import PgDatabase
from supplier_app.errors import DatabaseError, MigrationError


@pytest.fixture()
def empty_dsn(pg_template):
    """An empty database (no schema at all)."""
    import uuid

    import psycopg

    name = f"t_{uuid.uuid4().hex[:12]}"
    admin = psycopg.connect(pg_template, autocommit=True)
    admin.execute(f'CREATE DATABASE "{name}"')
    yield psycopg.conninfo.make_conninfo(pg_template, dbname=name)
    admin.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
    admin.close()


def _tables(db: PgDatabase) -> set[str]:
    return {r[0] for r in db.query_all("SELECT table_name FROM information_schema.tables WHERE table_schema = current_schema()")}


def test_fresh_database_is_migrated_once_and_repeatable(empty_dsn) -> None:
    with PgDatabase(empty_dsn) as db:
        assert db.schema_version() == 0
        assert migrate(db) == LATEST_VERSION
        names = _tables(db)
        for expected in ("parties", "invoices", "ledger_entries", "settings", "schema_version", "audit_log", "interest_rates",
                         "cases", "dunning_notices", "payments", "companies", "hotels", "app_users", "document_files",
                         "data_version"):
            assert expected in names
        assert migrate(db) == LATEST_VERSION  # nothing to do the second time
        assert [r[0] for r in db.query_all("SELECT version FROM schema_version ORDER BY version")] == list(
            range(1, LATEST_VERSION + 1))
        assert db.scalar("SELECT version FROM data_version") == 0


def test_failing_migration_is_rolled_back_completely(empty_dsn) -> None:
    with PgDatabase(empty_dsn) as db:
        migrate(db, ALL_MIGRATIONS[:2])
        with pytest.raises(MigrationError) as err:
            migrate(db, [*ALL_MIGRATIONS[:2], Migration(3, "bad", ("CREATE TABLE half_done(x INT)", "THIS IS NOT SQL"))])
        assert "Version 3" in str(err.value)
        assert "half_done" not in _tables(db) and db.schema_version() == 2  # PostgreSQL DDL is transactional
        assert migrate(db) == LATEST_VERSION  # the real migrations still apply afterwards


def test_database_newer_than_the_program_is_refused(empty_dsn) -> None:
    with PgDatabase(empty_dsn) as db:
        migrate(db)
        db.execute("INSERT INTO schema_version VALUES (999,'future','x')")
        with pytest.raises(DatabaseError, match="aktualisieren"):
            migrate(db)


def test_clients_starting_at_once_migrate_exactly_once(empty_dsn) -> None:
    results: list = []

    def start() -> None:
        try:
            with PgDatabase(empty_dsn) as db:
                results.append(migrate(db))
        except Exception as exc:  # noqa: BLE001
            results.append(exc)

    threads = [threading.Thread(target=start) for _ in range(5)]
    [t.start() for t in threads]
    [t.join(120) for t in threads]
    assert results == [LATEST_VERSION] * 5


def test_ledger_is_append_only(storage) -> None:
    db = storage.db
    pid = db.insert("INSERT INTO parties(role,name,name_norm,created_at) VALUES ('supplier','S','s','2024-01-01')")
    eid = db.insert(
        "INSERT INTO ledger_entries(entry_date,supplier_id,entry_type,category_type,amount_cents,created_at)"
        " VALUES ('2024-01-01',?,'INVOICE','INVOICE',100,'x')", (pid,))
    with pytest.raises(INTEGRITY_ERRORS):
        db.execute("UPDATE ledger_entries SET amount_cents=5 WHERE id=?", (eid,))
    with pytest.raises(INTEGRITY_ERRORS):
        db.execute("DELETE FROM ledger_entries WHERE id=?", (eid,))


def test_ledger_check_constraints(storage) -> None:
    db = storage.db
    pid = db.insert("INSERT INTO parties(role,name,name_norm,created_at) VALUES ('supplier','S','s','2024-01-01')")
    base = ("INSERT INTO ledger_entries(entry_date,supplier_id,entry_type,category_type,amount_cents,created_at)"
            " VALUES ('2024-01-01',?,?,?,?,'x')")
    with pytest.raises(INTEGRITY_ERRORS):
        db.execute(base, (pid, "PAYMENT", "PAYMENT", 100))  # payment must be negative
    with pytest.raises(INTEGRITY_ERRORS):
        db.execute(base, (pid, "INVOICE", "INVOICE", 0))
    with pytest.raises(INTEGRITY_ERRORS):
        db.execute(base, (pid, "REVERSAL", "INVOICE", -5))  # reversal needs reverses_entry_id
    with pytest.raises(INTEGRITY_ERRORS):
        db.execute(base, (pid, "BOGUS", "INVOICE", 5))
