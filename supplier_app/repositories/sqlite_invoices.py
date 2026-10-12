"""SQLite implementations of :class:`InvoiceRepository` and :class:`LedgerRepository`."""

from __future__ import annotations

import sqlite3
from datetime import date
from decimal import Decimal

from supplier_app.database.errors import INTEGRITY_ERRORS
from supplier_app.errors import DuplicateError, LedgerError, NotFoundError
from supplier_app.models.entities import Invoice, LedgerEntry
from supplier_app.models.enums import InvoiceStatus, LedgerEntryType
from supplier_app.models.scope import Scope
from supplier_app.repositories.interfaces import InvoiceRepository, LedgerRepository
from supplier_app.repositories.sqlite_base import SqliteRepo, d2s, like_escape, must_date, s2d, stamp
from supplier_app.util.normalize import normalize_reference

_INV_COLS = (
    "id, supplier_id, invoice_number, invoice_date, due_date, net_cents, vat_rate, vat_cents, gross_cents,"
    " currency, status, notes, category_id, company_id, hotel_id, created_at"
)


def scope_clause(scope: Scope | None, alias: str = "") -> tuple[str, list[object]]:
    """``(' AND ...', params)`` restricting a query on ``invoices`` (optionally aliased) to a scope."""
    if scope is None or scope.is_all:
        return "", []
    prefix = f"{alias}." if alias else ""
    col, val = ("hotel_id", scope.hotel_id) if scope.hotel_id is not None else ("company_id", scope.company_id)
    return f" AND {prefix}{col} = ?", [val]


def ledger_scope(scope: Scope | None) -> tuple[str, str, list[object]]:
    """Joins/condition for ``ledger_entries e``: entries of invoices in scope, or unapplied payments in scope."""
    if scope is None or scope.is_all:
        return "", "", []
    col, val = ("hotel_id", scope.hotel_id) if scope.hotel_id is not None else ("company_id", scope.company_id)
    joins = " LEFT JOIN invoices si ON si.id = e.invoice_id LEFT JOIN payments sp ON sp.id = e.payment_id"
    cond = f" AND (si.{col} = ? OR (e.invoice_id IS NULL AND sp.{col} = ?))"
    return joins, cond, [val, val]


def _invoice(row: sqlite3.Row) -> Invoice:
    return Invoice(
        id=row["id"], supplier_id=row["supplier_id"], invoice_number=row["invoice_number"],
        invoice_date=must_date(row["invoice_date"]), due_date=s2d(row["due_date"]), net_cents=row["net_cents"],
        vat_rate=Decimal(row["vat_rate"]), vat_cents=row["vat_cents"], gross_cents=row["gross_cents"],
        currency=row["currency"], status=InvoiceStatus(row["status"]), notes=row["notes"],
        category_id=row["category_id"], company_id=row["company_id"], hotel_id=row["hotel_id"],
        created_at=row["created_at"],
    )


class SqliteInvoiceRepository(SqliteRepo, InvoiceRepository):
    def add(self, invoice: Invoice) -> Invoice:
        invoice.created_at = stamp(invoice.created_at)
        try:
            invoice.id = self.db.insert(
                "INSERT INTO invoices(supplier_id, invoice_number, invoice_number_norm, invoice_date, due_date,"
                " net_cents, vat_rate, vat_cents, gross_cents, currency, status, notes, category_id, company_id,"
                " hotel_id, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (invoice.supplier_id, invoice.invoice_number.strip(), normalize_reference(invoice.invoice_number),
                 d2s(invoice.invoice_date), d2s(invoice.due_date), invoice.net_cents, str(invoice.vat_rate),
                 invoice.vat_cents, invoice.gross_cents, invoice.currency, invoice.status.value, invoice.notes,
                 invoice.category_id, invoice.company_id, invoice.hotel_id, invoice.created_at),
            )
        except INTEGRITY_ERRORS as exc:
            raise DuplicateError(
                f"Rechnung '{invoice.invoice_number}' existiert für diesen Lieferanten bereits oder ist ungültig."
            ) from exc
        return invoice

    def set_supplier(self, invoice_id: int, supplier_id: int) -> None:
        try:
            self.db.execute("UPDATE invoices SET supplier_id=? WHERE id=?", (supplier_id, invoice_id))
        except INTEGRITY_ERRORS as exc:
            raise DuplicateError("Rechnungsnummer ist bereits vergeben oder ungültig.") from exc

    def update(self, invoice: Invoice) -> None:
        if invoice.id is None:
            raise NotFoundError("Rechnung ohne ID.")
        try:
            self.db.execute(
                "UPDATE invoices SET invoice_number=?, invoice_number_norm=?, invoice_date=?, due_date=?, net_cents=?,"
                " vat_rate=?, vat_cents=?, gross_cents=?, currency=?, status=?, notes=?, category_id=?, company_id=?,"
                " hotel_id=? WHERE id=?",
                (invoice.invoice_number.strip(), normalize_reference(invoice.invoice_number), d2s(invoice.invoice_date),
                 d2s(invoice.due_date), invoice.net_cents, str(invoice.vat_rate), invoice.vat_cents,
                 invoice.gross_cents, invoice.currency, invoice.status.value, invoice.notes, invoice.category_id,
                 invoice.company_id, invoice.hotel_id, invoice.id),
            )
        except INTEGRITY_ERRORS as exc:
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

    def list(
        self, supplier_id: int | None = None, status: InvoiceStatus | None = None, scope: Scope | None = None
    ) -> list[Invoice]:
        sql, params = f"SELECT {_INV_COLS} FROM invoices WHERE 1=1", []
        clause, extra = scope_clause(scope)
        sql += clause
        params.extend(extra)
        if supplier_id is not None:
            sql += " AND supplier_id=?"
            params.append(supplier_id)
        if status is not None:
            sql += " AND status=?"
            params.append(status.value)
        return [_invoice(r) for r in self.db.query_all(sql + " ORDER BY invoice_date, id", params)]

    def set_status(self, invoice_id: int, status: InvoiceStatus) -> None:
        self.db.execute("UPDATE invoices SET status=? WHERE id=?", (status.value, invoice_id))

    def set_scope(self, invoice_id: int, company_id: int | None, hotel_id: int | None) -> None:
        try:
            self.db.execute("UPDATE invoices SET company_id=?, hotel_id=? WHERE id=?", (company_id, hotel_id, invoice_id))
        except INTEGRITY_ERRORS as exc:
            raise DuplicateError("Das Hotel gehört nicht zu dieser Gesellschaft.") from exc

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


_LEDGER_COLS_E = ", ".join(f"e.{c.strip()}" for c in _LEDGER_COLS.split(","))


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
        except INTEGRITY_ERRORS as exc:
            raise LedgerError(f"Buchung verletzt eine Ledger-Regel: {exc}") from exc
        return entry

    def get(self, entry_id: int) -> LedgerEntry | None:
        row = self.db.query_one(f"SELECT {_LEDGER_COLS} FROM ledger_entries WHERE id=?", (entry_id,))
        return _entry(row) if row else None

    def list(
        self, *, invoice_id: int | None = None, supplier_id: int | None = None, date_from: date | None = None,
        date_to: date | None = None, notice_id: int | None = None, payment_id: int | None = None,
        scope: Scope | None = None,
    ) -> list[LedgerEntry]:
        joins, cond, params = ledger_scope(scope)
        sql = f"SELECT {_LEDGER_COLS_E} FROM ledger_entries e{joins} WHERE 1=1{cond}"
        for col, val in (("invoice_id", invoice_id), ("supplier_id", supplier_id), ("notice_id", notice_id),
                         ("payment_id", payment_id)):
            if val is not None:
                sql += f" AND e.{col}=?"
                params.append(val)
        if date_from:
            sql += " AND e.entry_date>=?"
            params.append(d2s(date_from))
        if date_to:
            sql += " AND e.entry_date<=?"
            params.append(d2s(date_to))
        return [_entry(r) for r in self.db.query_all(sql + " ORDER BY e.entry_date, e.id", params)]

    def is_reversed(self, entry_id: int) -> bool:
        return self.db.query_one("SELECT 1 FROM ledger_entries WHERE reverses_entry_id=?", (entry_id,)) is not None

    def _filtered(self, select: str, tail: str, where: str, *, as_of: date | None, supplier_id: int | None,
                  scope: Scope | None, date_from: date | None = None, date_to: date | None = None) -> list:
        """Shared builder for the aggregate queries (alias ``e`` for ledger_entries)."""
        joins, cond, params = ledger_scope(scope)
        sql = f"SELECT {select} FROM ledger_entries e{joins} WHERE {where}{cond}"
        for clause, value in (("e.entry_date<=?", as_of), ("e.entry_date>=?", date_from), ("e.entry_date<=?", date_to)):
            if value:
                sql += f" AND {clause}"
                params.append(d2s(value))
        if supplier_id is not None:
            sql += " AND e.supplier_id=?"
            params.append(supplier_id)
        return self.db.query_all(sql + tail, params)

    def sums_by_invoice(
        self, *, as_of: date | None = None, supplier_id: int | None = None, scope: Scope | None = None
    ) -> list[tuple[int, int, str, int]]:
        rows = self._filtered("e.invoice_id, e.supplier_id, e.category_type, SUM(e.amount_cents)",
                              " GROUP BY e.invoice_id, e.supplier_id, e.category_type", "e.invoice_id IS NOT NULL",
                              as_of=as_of, supplier_id=supplier_id, scope=scope)
        return [(r[0], r[1], r[2], r[3]) for r in rows]

    def unapplied_by_supplier(self, *, as_of: date | None = None, scope: Scope | None = None) -> dict[int, int]:
        rows = self._filtered("e.supplier_id, SUM(e.amount_cents)", " GROUP BY e.supplier_id", "e.invoice_id IS NULL",
                              as_of=as_of, supplier_id=None, scope=scope)
        return {r[0]: r[1] for r in rows}

    def balances_by_invoice(
        self, *, as_of: date | None = None, supplier_id: int | None = None, scope: Scope | None = None
    ) -> dict[int, int]:
        rows = self._filtered("e.invoice_id, SUM(e.amount_cents)", " GROUP BY e.invoice_id", "e.invoice_id IS NOT NULL",
                              as_of=as_of, supplier_id=supplier_id, scope=scope)
        return {r[0]: r[1] for r in rows}

    def unapplied_entries(
        self, *, supplier_id: int | None = None, as_of: date | None = None, scope: Scope | None = None
    ) -> list[LedgerEntry]:
        rows = self._filtered(
            _LEDGER_COLS_E, " ORDER BY e.entry_date, e.id",
            "e.invoice_id IS NULL AND e.entry_type='PAYMENT' AND e.payment_id IS NOT NULL AND NOT EXISTS "
            "(SELECT 1 FROM ledger_entries r WHERE r.reverses_entry_id=e.id)",
            as_of=as_of, supplier_id=supplier_id, scope=scope)
        return [_entry(r) for r in rows]

    def sums_by_type(
        self, *, date_from: date | None = None, date_to: date | None = None, supplier_id: int | None = None,
        month_buckets: bool = False, scope: Scope | None = None,
    ) -> list[tuple[str, str, int]]:
        bucket = "substr(e.entry_date,1,7)" if month_buckets else "''"
        group = f"{bucket}, e.category_type" if month_buckets else "e.category_type"
        rows = self._filtered(f"{bucket}, e.category_type, SUM(e.amount_cents)", f" GROUP BY {group}",
                              "1=1", as_of=None, supplier_id=supplier_id, scope=scope, date_from=date_from,
                              date_to=date_to)
        return [(r[0], r[1], r[2]) for r in rows]

    def count(self) -> int:
        return int(self.db.scalar("SELECT COUNT(*) FROM ledger_entries", default=0))
