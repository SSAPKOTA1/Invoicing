"""SQLite implementation of :class:`OrganizationRepository` (companies and hotels)."""

from __future__ import annotations

import sqlite3

from supplier_app.errors import DuplicateError, NotFoundError
from supplier_app.models.entities import Company, Hotel
from supplier_app.repositories.interfaces import OrganizationRepository
from supplier_app.repositories.sqlite_base import SqliteRepo, stamp


class SqliteOrganizationRepository(SqliteRepo, OrganizationRepository):
    @staticmethod
    def _company(row: sqlite3.Row) -> Company:
        return Company(id=row["id"], name=row["name"], notes=row["notes"], created_at=row["created_at"])

    @staticmethod
    def _hotel(row: sqlite3.Row) -> Hotel:
        return Hotel(id=row["id"], company_id=row["company_id"], name=row["name"], notes=row["notes"],
                     created_at=row["created_at"])

    def add_company(self, company: Company) -> Company:
        company.created_at = stamp(company.created_at)
        try:
            company.id = self.db.insert("INSERT INTO companies(name, notes, created_at) VALUES (?,?,?)",
                                        (company.name.strip(), company.notes, company.created_at))
        except sqlite3.IntegrityError as exc:
            raise DuplicateError(f"Die Gesellschaft '{company.name}' existiert bereits oder ist leer.") from exc
        return company

    def update_company(self, company: Company) -> None:
        try:
            self.db.execute("UPDATE companies SET name=?, notes=? WHERE id=?", (company.name.strip(), company.notes, company.id))
        except sqlite3.IntegrityError as exc:
            raise DuplicateError(f"Die Gesellschaft '{company.name}' existiert bereits oder ist leer.") from exc

    def get_company(self, company_id: int) -> Company | None:
        row = self.db.query_one("SELECT * FROM companies WHERE id=?", (company_id,))
        return self._company(row) if row else None

    def companies(self) -> list[Company]:
        return [self._company(r) for r in self.db.query_all("SELECT * FROM companies ORDER BY name COLLATE NOCASE")]

    def company_has_items(self, company_id: int) -> bool:
        checks = ("SELECT 1 FROM invoices WHERE company_id=? LIMIT 1", "SELECT 1 FROM payments WHERE company_id=? LIMIT 1",
                  "SELECT 1 FROM documents WHERE company_id=? LIMIT 1", "SELECT 1 FROM hotels WHERE company_id=? LIMIT 1")
        return any(self.db.query_one(sql, (company_id,)) for sql in checks)

    def delete_company(self, company_id: int) -> None:
        if self.company_has_items(company_id):
            raise DuplicateError("Die Gesellschaft hat Hotels, Rechnungen oder Dokumente und kann nicht gelöscht werden.")
        self.db.execute("DELETE FROM companies WHERE id=?", (company_id,))

    def add_hotel(self, hotel: Hotel) -> Hotel:
        hotel.created_at = stamp(hotel.created_at)
        try:
            hotel.id = self.db.insert("INSERT INTO hotels(company_id, name, notes, created_at) VALUES (?,?,?,?)",
                                      (hotel.company_id, hotel.name.strip(), hotel.notes, hotel.created_at))
        except sqlite3.IntegrityError as exc:
            raise DuplicateError(f"Das Hotel '{hotel.name}' existiert in dieser Gesellschaft bereits oder ist ungültig.") from exc
        return hotel

    def update_hotel(self, hotel: Hotel) -> None:
        if hotel.id is None:
            raise NotFoundError("Hotel ohne ID.")
        try:
            self.db.execute("UPDATE hotels SET name=?, notes=? WHERE id=?", (hotel.name.strip(), hotel.notes, hotel.id))
        except sqlite3.IntegrityError as exc:
            raise DuplicateError(f"Das Hotel '{hotel.name}' existiert in dieser Gesellschaft bereits oder ist leer.") from exc

    def get_hotel(self, hotel_id: int) -> Hotel | None:
        row = self.db.query_one("SELECT * FROM hotels WHERE id=?", (hotel_id,))
        return self._hotel(row) if row else None

    def hotels(self, company_id: int | None = None) -> list[Hotel]:
        if company_id is None:
            rows = self.db.query_all("SELECT * FROM hotels ORDER BY name COLLATE NOCASE")
        else:
            rows = self.db.query_all("SELECT * FROM hotels WHERE company_id=? ORDER BY name COLLATE NOCASE", (company_id,))
        return [self._hotel(r) for r in rows]

    def hotel_has_items(self, hotel_id: int) -> bool:
        checks = ("SELECT 1 FROM invoices WHERE hotel_id=? LIMIT 1", "SELECT 1 FROM payments WHERE hotel_id=? LIMIT 1",
                  "SELECT 1 FROM documents WHERE hotel_id=? LIMIT 1")
        return any(self.db.query_one(sql, (hotel_id,)) for sql in checks)

    def delete_hotel(self, hotel_id: int) -> None:
        if self.hotel_has_items(hotel_id):
            raise DuplicateError("Dem Hotel sind Rechnungen oder Dokumente zugeordnet; es kann nicht gelöscht werden.")
        self.db.execute("DELETE FROM hotels WHERE id=?", (hotel_id,))
