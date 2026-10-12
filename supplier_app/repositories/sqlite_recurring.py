"""SQLite implementation of :class:`RecurringRepository`."""

from __future__ import annotations

import sqlite3
from datetime import date
from decimal import Decimal

from supplier_app.database.errors import INTEGRITY_ERRORS
from supplier_app.errors import DuplicateError
from supplier_app.models.entities import RecurringAmount, RecurringInvoice
from supplier_app.models.enums import RecurrencePeriod
from supplier_app.repositories.interfaces import RecurringRepository
from supplier_app.repositories.sqlite_base import SqliteRepo, d2s, must_date, s2d, stamp


class SqliteRecurringRepository(SqliteRepo, RecurringRepository):
    def _hydrate(self, row: sqlite3.Row) -> RecurringInvoice:
        amounts = [RecurringAmount(must_date(r["valid_from"]), r["gross_cents"]) for r in self.db.query_all(
            "SELECT valid_from, gross_cents FROM recurring_amounts WHERE recurring_id=? ORDER BY valid_from", (row["id"],))]
        return RecurringInvoice(
            id=row["id"], supplier_id=row["supplier_id"], title=row["title"], period=RecurrencePeriod(row["period"]),
            start_date=must_date(row["start_date"]), day_of_month=row["day_of_month"], end_date=s2d(row["end_date"]),
            due_days=row["due_days"], number_pattern=row["number_pattern"], vat_rate=Decimal(row["vat_rate"]),
            notes=row["notes"], category_id=row["category_id"], company_id=row["company_id"], hotel_id=row["hotel_id"],
            active=bool(row["active"]), amounts=amounts, created_at=row["created_at"])

    def _save_amounts(self, rec: RecurringInvoice) -> None:
        self.db.execute("DELETE FROM recurring_amounts WHERE recurring_id=?", (rec.id,))
        self.db.executemany(
            "INSERT INTO recurring_amounts(recurring_id, valid_from, gross_cents) VALUES (?,?,?)",
            [(rec.id, d2s(a.valid_from), a.gross_cents) for a in rec.amounts])

    def add(self, rec: RecurringInvoice) -> RecurringInvoice:
        rec.created_at = stamp(rec.created_at)
        try:
            rec.id = self.db.insert(
                "INSERT INTO recurring_invoices(supplier_id, title, period, day_of_month, start_date, end_date, due_days,"
                " number_pattern, vat_rate, notes, category_id, company_id, hotel_id, active, created_at)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (rec.supplier_id, rec.title.strip(), rec.period.value, rec.day_of_month, d2s(rec.start_date),
                 d2s(rec.end_date), rec.due_days, rec.number_pattern, str(rec.vat_rate), rec.notes, rec.category_id,
                 rec.company_id, rec.hotel_id, int(rec.active), rec.created_at))
            self._save_amounts(rec)
        except INTEGRITY_ERRORS as exc:
            raise DuplicateError("Die wiederkehrende Rechnung ist ungültig oder doppelt (Beträge mit gleichem Datum?).") from exc
        return rec

    def update(self, rec: RecurringInvoice) -> None:
        try:
            self.db.execute(
                "UPDATE recurring_invoices SET supplier_id=?, title=?, period=?, day_of_month=?, start_date=?, end_date=?,"
                " due_days=?, number_pattern=?, vat_rate=?, notes=?, category_id=?, company_id=?, hotel_id=?, active=?"
                " WHERE id=?",
                (rec.supplier_id, rec.title.strip(), rec.period.value, rec.day_of_month, d2s(rec.start_date),
                 d2s(rec.end_date), rec.due_days, rec.number_pattern, str(rec.vat_rate), rec.notes, rec.category_id,
                 rec.company_id, rec.hotel_id, int(rec.active), rec.id))
            self._save_amounts(rec)
        except INTEGRITY_ERRORS as exc:
            raise DuplicateError("Die wiederkehrende Rechnung ist ungültig oder doppelt (Beträge mit gleichem Datum?).") from exc

    def get(self, rec_id: int) -> RecurringInvoice | None:
        row = self.db.query_one("SELECT * FROM recurring_invoices WHERE id=?", (rec_id,))
        return self._hydrate(row) if row else None

    def list(self, *, supplier_id: int | None = None, active_only: bool = False) -> list[RecurringInvoice]:
        sql, params = "SELECT * FROM recurring_invoices WHERE 1=1", []
        if supplier_id is not None:
            sql += " AND supplier_id=?"
            params.append(supplier_id)
        if active_only:
            sql += " AND active=1"
        return [self._hydrate(r) for r in self.db.query_all(sql + " ORDER BY lower(title), id", params)]

    def delete(self, rec_id: int) -> None:
        self.db.execute("DELETE FROM recurring_invoices WHERE id=?", (rec_id,))

    def log_run(self, rec_id: int, occurrence: date, invoice_id: int) -> bool:
        try:
            self.db.insert("INSERT INTO recurring_runs(recurring_id, occurrence, invoice_id, created_at) VALUES (?,?,?,?)",
                           (rec_id, d2s(occurrence), invoice_id, stamp("")))
        except INTEGRITY_ERRORS:
            return False
        return True

    def runs(self, rec_id: int) -> dict[date, int]:
        return {must_date(r["occurrence"]): r["invoice_id"] for r in self.db.query_all(
            "SELECT occurrence, invoice_id FROM recurring_runs WHERE recurring_id=?", (rec_id,))}

    def template_of_invoice(self, invoice_id: int) -> int | None:
        row = self.db.query_one("SELECT recurring_id FROM recurring_runs WHERE invoice_id=?", (invoice_id,))
        return row["recurring_id"] if row else None
