"""SQLite implementations of :class:`InvoiceRepository` and :class:`LedgerRepository`."""

from __future__ import annotations

import sqlite3
from datetime import date
from decimal import Decimal

from supplier_app.errors import DuplicateError, LedgerError, NotFoundError
from supplier_app.models.entities import Invoice, LedgerEntry
from supplier_app.models.enums import InvoiceStatus, LedgerEntryType
from supplier_app.repositories.interfaces import InvoiceRepository, LedgerRepository
from supplier_app.repositories.sqlite_base import SqliteRepo, d2s, like_escape, must_date, s2d, stamp
from supplier_app.util.normalize import normalize_reference

_INV_COLS = (
    "id, supplier_id, invoice_number, invoice_date, due_date, net_cents, vat_rate, vat_cents, gross_cents,"
    " currency, status, notes, category_id, created_at"
)


def _invoice(row: sqlite3.Row) -> Invoice:
    return Invoice(
        id=row["id"], supplier_id=row["supplier_id"], invoice_number=row["invoice_number"],
        invoice_date=must_date(row["invoice_date"]), due_date=s2d(row["due_date"]), net_cents=row["net_cents"],
        vat_rate=Decimal(row["vat_rate"]), vat_cents=row["vat_cents"], gross_cents=row["gross_cents"],
        currency=row["currency"], status=InvoiceStatus(row["status"]), notes=row["notes"],
        category_id=row["category_id"], created_at=row["created_at"],
    )


class SqliteInvoiceRepository(SqliteRepo, InvoiceRepository):
    def add(self, invoice: Invoice) -> Invoice:
        invoice.created_at = stamp(invoice.created_at)
        try:
            invoice.id = self.db.insert(
                "INSERT INTO invoices(supplier_id, invoice_number, invoice_number_norm, invoice_date, due_date,"
                " net_cents, vat_rate, vat_cents, gross_cents, currency, status, notes, category_id, created_at)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (invoice.supplier_id, invoice.invoice_number.strip(), normalize_reference(invoice.invoice_number),
                 d2s(invoice.invoice_date), d2s(invoice.due_date), invoice.net_cents, str(invoice.vat_rate),
                 invoice.vat_cents, invoice.gross_cents, invoice.currency, invoice.status.value, invoice.notes,
                 invoice.category_id, invoice.created_at),
            )
        except sqlite3.IntegrityError as exc:
            raise DuplicateError(
                f"Rechnung '{invoice.invoice_number}' existiert für diesen Lieferanten bereits oder ist ungültig."
            ) from exc
        return invoice

    def update(self, invoice: Invoice) -> None:
        if invoice.id is None:
            raise NotFoundError("Rechnung ohne ID.")
        try:
            self.db.execute(
                "UPDATE invoices SET invoice_number=?, invoice_number_norm=?, invoice_date=?, due_date=?, net_cents=?,"
                " vat_rate=?, vat_cents=?, gross_cents=?, currency=?, status=?, notes=?, category_id=? WHERE id=?",
                (invoice.invoice_number.strip(), normalize_reference(invoice.invoice_number), d2s(invoice.invoice_date),
                 d2s(invoice.due_date), invoice.net_cents, str(invoice.vat_rate), invoice.vat_cents,
                 invoice.gross_cents, invoice.currency, invoice.status.value, invoice.notes, invoice.category_id,
                 invoice.id),
            )
        except sqlite3.IntegrityError as exc:
            raise DuplicateError("Rechnungsnummer ist bereits vergeben oder ungültig.") from exc

    def get(self, invoice_id: int) -> Invoice | None:
        row = self.db.query_one(f"SELECT {_INV_COLS} FROM invoices WHERE id=?", (invoice_id,))
        return _invoice(row) if row else None

    def get_by_number(self, supplier_id: int, invoice_number: str) -> Invoice | None:
        row = self.db.query_one(
            f"SELECT {_INV_COLS} FROM invoices WHERE supplier_id=? AND invoice_number=?",
            (supplier_id, invoice_number.strip()),
        )
        return _invoice(row) if row else None

    def find_by_number_norm(self, norm: str, supplier_id: int | None = None, prefix: bool = False) -> list[Invoice]:
        if not norm:
            return []
        cond = "invoice_number_norm LIKE ? ESCAPE '\\'" if prefix else "invoice_number_norm = ?"
        arg = f"%{like_escape(norm)}%" if prefix else norm
        sql = f"SELECT {_INV_COLS} FROM invoices WHERE {cond}"
        params: list[object] = [arg]
        if supplier_id is not None:
            sql += " AND supplier_id=?"
            params.append(supplier_id)
        return [_invoice(r) for r in self.db.query_all(sql + " ORDER BY invoice_date", params)]

    def list(self, supplier_id: int | None = None, status: InvoiceStatus | None = None) -> list[Invoice]:
        sql, params = f"SELECT {_INV_COLS} FROM invoices WHERE 1=1", []
        if supplier_id is not None:
            sql += " AND supplier_id=?"
            params.append(supplier_id)
        if status is not None:
            sql += " AND status=?"
            params.append(status.value)
        return [_invoice(r) for r in self.db.query_all(sql + " ORDER BY invoice_date, id", params)]

    def set_status(self, invoice_id: int, status: InvoiceStatus) -> None:
        self.db.execute("UPDATE invoices SET status=? WHERE id=?", (status.value, invoice_id))

    def find_by_gross(self, gross_cents: int, supplier_id: int | None = None) -> list[Invoice]:
        sql, params = f"SELECT {_INV_COLS} FROM invoices WHERE gross_cents=?", [gross_cents]
        if supplier_id is not None:
            sql += " AND supplier_id=?"
            params.append(supplier_id)
        return [_invoice(r) for r in self.db.query_all(sql + " ORDER BY invoice_date", params)]


_LEDGER_COLS = (
    "id, entry_date, supplier_id, invoice_id, entry_type, category_type, amount_cents, document_id, notice_id,"
    " payment_id, reverses_entry_id, comment, created_at"
)


def _entry(row: sqlite3.Row) -> LedgerEntry:
    return LedgerEntry(
        id=row["id"], entry_date=must_date(row["entry_date"]), supplier_id=row["supplier_id"],
        invoice_id=row["invoice_id"], entry_type=LedgerEntryType(row["entry_type"]),
        category_type=LedgerEntryType(row["category_type"]), amount_cents=row["amount_cents"],
        document_id=row["document_id"], notice_id=row["notice_id"], payment_id=row["payment_id"],
        reverses_entry_id=row["reverses_entry_id"], comment=row["comment"], created_at=row["created_at"],
    )


class SqliteLedgerRepository(SqliteRepo, LedgerRepository):
    def append(self, entry: LedgerEntry) -> LedgerEntry:
        entry.created_at = stamp(entry.created_at)
        try:
            entry.id = self.db.insert(
                "INSERT INTO ledger_entries(entry_date, supplier_id, invoice_id, entry_type, category_type,"
                " amount_cents, document_id, notice_id, payment_id, reverses_entry_id, comment, created_at)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (d2s(entry.entry_date), entry.supplier_id, entry.invoice_id, entry.entry_type.value,
                 entry.category_type.value, entry.amount_cents, entry.document_id, entry.notice_id,
                 entry.payment_id, entry.reverses_entry_id, entry.comment, entry.created_at),
            )
        except sqlite3.IntegrityError as exc:
            raise LedgerError(f"Buchung verletzt eine Ledger-Regel: {exc}") from exc
        return entry

    def get(self, entry_id: int) -> LedgerEntry | None:
        row = self.db.query_one(f"SELECT {_LEDGER_COLS} FROM ledger_entries WHERE id=?", (entry_id,))
        return _entry(row) if row else None

    def list(
        self, *, invoice_id: int | None = None, supplier_id: int | None = None, date_from: date | None = None,
        date_to: date | None = None, notice_id: int | None = None, payment_id: int | None = None,
    ) -> list[LedgerEntry]:
        sql, params = f"SELECT {_LEDGER_COLS} FROM ledger_entries WHERE 1=1", []
        for col, val in (("invoice_id", invoice_id), ("supplier_id", supplier_id), ("notice_id", notice_id),
                         ("payment_id", payment_id)):
            if val is not None:
                sql += f" AND {col}=?"
                params.append(val)
        if date_from:
            sql += " AND entry_date>=?"
            params.append(d2s(date_from))
        if date_to:
            sql += " AND entry_date<=?"
            params.append(d2s(date_to))
        return [_entry(r) for r in self.db.query_all(sql + " ORDER BY entry_date, id", params)]

    def is_reversed(self, entry_id: int) -> bool:
        return self.db.query_one("SELECT 1 FROM ledger_entries WHERE reverses_entry_id=?", (entry_id,)) is not None

    def sums_by_invoice(self, *, as_of: date | None = None, supplier_id: int | None = None) -> list[tuple[int, int, str, int]]:
        sql = ("SELECT invoice_id, supplier_id, category_type, SUM(amount_cents) FROM ledger_entries"
               " WHERE invoice_id IS NOT NULL")
        params: list[object] = []
        if as_of:
            sql += " AND entry_date<=?"
            params.append(d2s(as_of))
        if supplier_id is not None:
            sql += " AND supplier_id=?"
            params.append(supplier_id)
        sql += " GROUP BY invoice_id, supplier_id, category_type"
        return [(r[0], r[1], r[2], r[3]) for r in self.db.query_all(sql, params)]

    def unapplied_by_supplier(self, *, as_of: date | None = None) -> dict[int, int]:
        sql = "SELECT supplier_id, SUM(amount_cents) FROM ledger_entries WHERE invoice_id IS NULL"
        params: list[object] = []
        if as_of:
            sql += " AND entry_date<=?"
            params.append(d2s(as_of))
        sql += " GROUP BY supplier_id"
        return {r[0]: r[1] for r in self.db.query_all(sql, params)}

    def sums_by_type(
        self, *, date_from: date | None = None, date_to: date | None = None, supplier_id: int | None = None,
        month_buckets: bool = False,
    ) -> list[tuple[str, str, int]]:
        bucket = "substr(entry_date,1,7)" if month_buckets else "''"
        sql = f"SELECT {bucket}, category_type, SUM(amount_cents) FROM ledger_entries WHERE 1=1"
        params: list[object] = []
        if date_from:
            sql += " AND entry_date>=?"
            params.append(d2s(date_from))
        if date_to:
            sql += " AND entry_date<=?"
            params.append(d2s(date_to))
        if supplier_id is not None:
            sql += " AND supplier_id=?"
            params.append(supplier_id)
        sql += f" GROUP BY {bucket}, category_type"
        return [(r[0], r[1], r[2]) for r in self.db.query_all(sql, params)]

    def count(self) -> int:
        return int(self.db.scalar("SELECT COUNT(*) FROM ledger_entries", default=0))
