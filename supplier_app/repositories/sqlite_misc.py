"""SQLite repositories for settings, interest rates, categories and the audit log."""

from __future__ import annotations

import sqlite3
from datetime import date
from decimal import Decimal

from supplier_app.errors import DuplicateError
from supplier_app.models.entities import AuditLogEntry, Category, InterestRate
from supplier_app.repositories.interfaces import (
    AuditRepository,
    CategoryRepository,
    RateRepository,
    SettingsRepository,
)
from supplier_app.repositories.sqlite_base import SqliteRepo, d2s, must_date, stamp


class SqliteSettingsRepository(SqliteRepo, SettingsRepository):
    def get(self, key: str, default: str | None = None) -> str | None:
        row = self.db.query_one("SELECT value FROM settings WHERE key=?", (key,))
        return row[0] if row else default

    def set(self, key: str, value: str) -> None:
        self.db.execute(
            "INSERT INTO settings(key, value) VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, value),
        )

    def delete(self, key: str) -> None:
        self.db.execute("DELETE FROM settings WHERE key=?", (key,))

    def all(self) -> dict[str, str]:
        return {r[0]: r[1] for r in self.db.query_all("SELECT key, value FROM settings")}


class SqliteRateRepository(SqliteRepo, RateRepository):
    def list(self) -> list[InterestRate]:
        return [
            InterestRate(id=r["id"], valid_from=must_date(r["valid_from"]), base_rate=Decimal(r["base_rate"]))
            for r in self.db.query_all("SELECT * FROM interest_rates ORDER BY valid_from")
        ]

    def upsert(self, rate: InterestRate) -> None:
        self.db.execute(
            "INSERT INTO interest_rates(valid_from, base_rate) VALUES (?,?)"
            " ON CONFLICT(valid_from) DO UPDATE SET base_rate=excluded.base_rate",
            (d2s(rate.valid_from), str(rate.base_rate)),
        )

    def delete(self, valid_from: date) -> None:
        self.db.execute("DELETE FROM interest_rates WHERE valid_from=?", (d2s(valid_from),))


class SqliteCategoryRepository(SqliteRepo, CategoryRepository):
    def list(self) -> list[Category]:
        return [Category(id=r["id"], name=r["name"]) for r in self.db.query_all("SELECT * FROM categories ORDER BY name")]

    def add(self, name: str) -> Category:
        try:
            return Category(id=self.db.insert("INSERT INTO categories(name) VALUES (?)", (name.strip(),)), name=name.strip())
        except sqlite3.IntegrityError as exc:
            raise DuplicateError(f"Kategorie '{name}' existiert bereits oder ist leer.") from exc

    def delete(self, category_id: int) -> None:
        self.db.execute("DELETE FROM categories WHERE id=?", (category_id,))


class SqliteAuditRepository(SqliteRepo, AuditRepository):
    def add(self, entry: AuditLogEntry) -> AuditLogEntry:
        entry.created_at = stamp(entry.created_at)
        entry.id = self.db.insert(
            "INSERT INTO audit_log(created_at, action, entity, entity_id, details) VALUES (?,?,?,?,?)",
            (entry.created_at, entry.action, entry.entity, entry.entity_id, entry.details),
        )
        return entry

    def list(self, *, limit: int = 200, entity: str | None = None) -> list[AuditLogEntry]:
        sql, params = "SELECT * FROM audit_log WHERE 1=1", []
        if entity:
            sql += " AND entity=?"
            params.append(entity)
        sql += " ORDER BY id DESC LIMIT ?"
        params.append(limit)
        return [
            AuditLogEntry(id=r["id"], created_at=r["created_at"], action=r["action"], entity=r["entity"],
                          entity_id=r["entity_id"], details=r["details"])
            for r in self.db.query_all(sql, params)
        ]
