"""Backend independent table dump/load: server backups (JSON lines in a zip) and the transfer local -> server."""

from __future__ import annotations

import base64
import json
from collections.abc import Callable, Iterator
from typing import Any

#: parents before children (foreign keys); ledger entries are ordered by id so reversals come after their originals
TABLES = [
    "settings", "categories", "interest_rates", "parties", "party_aliases", "party_ibans", "companies", "hotels", "documents",
    "document_files", "document_references", "invoices", "cases", "case_events", "dunning_notices", "notice_invoices", "payments",
    "payment_allocations", "ledger_entries", "audit_log", "app_users",
]
ORDER_BY = {"settings": "key", "document_files": "document_id"}
BLOB_COLUMNS = {"document_files": {"content"}}
#: rows with this self reference are inserted first without it and linked afterwards
SELF_REFERENCES = {"parties": "represents_supplier_id"}
#: business data (what makes a database "not empty")
BUSINESS_TABLES = ("parties", "invoices", "documents", "payments", "ledger_entries", "dunning_notices", "cases")
#: tables that a fresh database is seeded with (defaults) - replaced when loading
SEEDED_TABLES = ("settings", "categories", "interest_rates")


def is_empty(db: Any) -> bool:
    return all(int(db.scalar(f"SELECT COUNT(*) FROM {t}", default=0)) == 0 for t in BUSINESS_TABLES)


def iter_rows(db: Any, table: str) -> Iterator[dict[str, Any]]:
    order = ORDER_BY.get(table, "id")
    for row in db.query_all(f"SELECT * FROM {table} ORDER BY {order}"):
        yield {k: (bytes(row[k]) if k in BLOB_COLUMNS.get(table, ()) and row[k] is not None else row[k]) for k in row.keys()}


def encode_row(table: str, row: dict[str, Any]) -> str:
    out = {k: (base64.b64encode(v).decode("ascii") if k in BLOB_COLUMNS.get(table, ()) and v is not None else v)
           for k, v in row.items()}
    return json.dumps(out, ensure_ascii=False)


def decode_row(table: str, line: str) -> dict[str, Any]:
    row = json.loads(line)
    for col in BLOB_COLUMNS.get(table, ()):
        if row.get(col) is not None:
            row[col] = base64.b64decode(row[col])
    return row


def _insert(db: Any, table: str, row: dict[str, Any], *, skip: str | None = None) -> None:
    data = dict(row)
    if skip is not None:
        data[skip] = None
    cols = list(data)
    db.execute(f"INSERT INTO {table}({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})", [data[c] for c in cols])


def clear_database(db: Any) -> None:
    """Remove all rows (TRUNCATE ignores the append-only ledger trigger); keeps the schema."""
    db.execute("TRUNCATE " + ", ".join(TABLES) + " RESTART IDENTITY CASCADE")


def load_tables(db: Any, rows_by_table: Callable[[str], Iterator[dict[str, Any]]], progress: Callable[[str], None] | None = None) -> int:
    """Insert all tables (the database must be empty) inside one transaction. Returns the number of rows."""
    total = 0
    with db.transaction():
        for table in TABLES:
            if progress:
                progress(table)
            if table in SEEDED_TABLES:
                db.execute(f"DELETE FROM {table}")
            link = SELF_REFERENCES.get(table)
            pending: list[tuple[Any, Any]] = []
            for row in rows_by_table(table):
                if link and row.get(link) is not None:
                    pending.append((row["id"], row[link]))
                    _insert(db, table, row, skip=link)
                else:
                    _insert(db, table, row)
                total += 1
            for pid, target in pending:
                db.execute(f"UPDATE {table} SET {link}=? WHERE id=?", (target, pid))
        reset_sequences(db)
        db.execute("UPDATE data_version SET version = version + 1 WHERE id = 1")
    return total


def reset_sequences(db: Any) -> None:
    """After inserting rows with explicit ids the identity counters must continue behind the highest id."""
    for table in TABLES:
        if table in ORDER_BY:
            continue
        db.execute(
            f"SELECT setval(pg_get_serial_sequence('{table}', 'id'), COALESCE(MAX(id), 1), MAX(id) IS NOT NULL) FROM {table}")
