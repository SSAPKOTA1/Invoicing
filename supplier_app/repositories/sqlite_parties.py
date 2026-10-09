"""SQLite implementation of :class:`PartyRepository`."""

from __future__ import annotations

import sqlite3

from supplier_app.errors import DuplicateError, NotFoundError
from supplier_app.models.entities import Party
from supplier_app.models.enums import PartyRole
from supplier_app.repositories.interfaces import PartyRepository
from supplier_app.repositories.sqlite_base import SqliteRepo, like_escape, stamp
from supplier_app.util.normalize import normalize_iban, normalize_name

_COLS = (
    "id, role, name, address, vat_id, tax_number, email, phone, contact, payment_terms, notes, "
    "represents_supplier_id, created_at"
)


class SqlitePartyRepository(SqliteRepo, PartyRepository):
    def _hydrate(self, row: sqlite3.Row) -> Party:
        pid = row["id"]
        aliases = [r[0] for r in self.db.query_all("SELECT alias FROM party_aliases WHERE party_id=? ORDER BY alias", (pid,))]
        ibans = [r[0] for r in self.db.query_all("SELECT iban FROM party_ibans WHERE party_id=? ORDER BY iban", (pid,))]
        return Party(
            id=pid, role=PartyRole(row["role"]), name=row["name"], aliases=aliases, ibans=ibans,
            address=row["address"], vat_id=row["vat_id"], tax_number=row["tax_number"], email=row["email"],
            phone=row["phone"], contact=row["contact"], payment_terms=row["payment_terms"], notes=row["notes"],
            represents_supplier_id=row["represents_supplier_id"], created_at=row["created_at"],
        )

    def _write_children(self, party: Party) -> None:
        assert party.id is not None
        self.db.execute("DELETE FROM party_aliases WHERE party_id=?", (party.id,))
        self.db.execute("DELETE FROM party_ibans WHERE party_id=?", (party.id,))
        seen: set[str] = set()
        for alias in party.aliases:
            norm = normalize_name(alias)
            if alias.strip() and norm and norm not in seen:
                seen.add(norm)
                self.db.execute(
                    "INSERT INTO party_aliases(party_id, alias, alias_norm) VALUES (?,?,?)",
                    (party.id, alias.strip(), norm),
                )
        for iban in dict.fromkeys(normalize_iban(i) for i in party.ibans if i.strip()):
            self.db.execute("INSERT INTO party_ibans(party_id, iban) VALUES (?,?)", (party.id, iban))

    def add(self, party: Party) -> Party:
        party.created_at = stamp(party.created_at)
        try:
            party.id = self.db.insert(
                "INSERT INTO parties(role, name, name_norm, address, vat_id, tax_number, email, phone, contact,"
                " payment_terms, notes, represents_supplier_id, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (party.role.value, party.name.strip(), normalize_name(party.name), party.address, party.vat_id,
                 party.tax_number, party.email, party.phone, party.contact, party.payment_terms, party.notes,
                 party.represents_supplier_id, party.created_at),
            )
            self._write_children(party)
        except sqlite3.IntegrityError as exc:
            raise DuplicateError(f"Der Datensatz '{party.name}' ist ungültig oder doppelt.") from exc
        return party

    def update(self, party: Party) -> None:
        if party.id is None:
            raise NotFoundError("Partei ohne ID kann nicht aktualisiert werden.")
        try:
            self.db.execute(
                "UPDATE parties SET role=?, name=?, name_norm=?, address=?, vat_id=?, tax_number=?, email=?,"
                " phone=?, contact=?, payment_terms=?, notes=?, represents_supplier_id=? WHERE id=?",
                (party.role.value, party.name.strip(), normalize_name(party.name), party.address, party.vat_id,
                 party.tax_number, party.email, party.phone, party.contact, party.payment_terms, party.notes,
                 party.represents_supplier_id, party.id),
            )
            self._write_children(party)
        except sqlite3.IntegrityError as exc:
            raise DuplicateError(f"Der Datensatz '{party.name}' ist ungültig oder doppelt.") from exc

    def get(self, party_id: int) -> Party | None:
        row = self.db.query_one(f"SELECT {_COLS} FROM parties WHERE id=?", (party_id,))
        return self._hydrate(row) if row else None

    def list(self, role: PartyRole | None = None) -> list[Party]:
        if role is None:
            rows = self.db.query_all(f"SELECT {_COLS} FROM parties ORDER BY name COLLATE NOCASE")
        else:
            rows = self.db.query_all(
                f"SELECT {_COLS} FROM parties WHERE role=? ORDER BY name COLLATE NOCASE", (role.value,)
            )
        return [self._hydrate(r) for r in rows]

    def has_dependents(self, party_id: int) -> bool:
        checks = [
            "SELECT 1 FROM invoices WHERE supplier_id=?",
            "SELECT 1 FROM ledger_entries WHERE supplier_id=?",
            "SELECT 1 FROM payments WHERE supplier_id=?",
            "SELECT 1 FROM dunning_notices WHERE supplier_id=? OR sender_party_id=?",
        ]
        for sql in checks:
            args = (party_id, party_id) if sql.count("?") == 2 else (party_id,)
            if self.db.query_one(sql + " LIMIT 1", args):
                return True
        return False

    def delete(self, party_id: int) -> None:
        if self.has_dependents(party_id):
            raise DuplicateError("Die Partei hat Buchungen und kann nicht gelöscht werden.")
        self.db.execute("DELETE FROM parties WHERE id=?", (party_id,))

    def find_by_iban(self, iban: str) -> list[Party]:
        rows = self.db.query_all(
            f"SELECT {_COLS} FROM parties WHERE id IN (SELECT party_id FROM party_ibans WHERE iban=?)",
            (normalize_iban(iban),),
        )
        return [self._hydrate(r) for r in rows]

    def find_by_vat_id(self, vat_id: str) -> list[Party]:
        key = vat_id.replace(" ", "").upper()
        rows = self.db.query_all(
            f"SELECT {_COLS} FROM parties WHERE upper(replace(vat_id,' ','')) = ? AND vat_id <> ''", (key,)
        )
        return [self._hydrate(r) for r in rows]

    def name_variants(self) -> list[tuple[int, str, str]]:
        rows = self.db.query_all(
            "SELECT id, name_norm, name FROM parties UNION ALL SELECT party_id, alias_norm, alias FROM party_aliases"
        )
        return [(r[0], r[1], r[2]) for r in rows]

    def search_names(self, norm_fragment: str) -> list[Party]:
        pattern = f"%{like_escape(norm_fragment)}%"
        rows = self.db.query_all(
            f"SELECT {_COLS} FROM parties WHERE name_norm LIKE ? ESCAPE '\\' OR lower(name) LIKE ? ESCAPE '\\'"
            " OR id IN (SELECT party_id FROM party_aliases WHERE alias_norm LIKE ? ESCAPE '\\')"
            " ORDER BY name COLLATE NOCASE",
            (pattern, f"%{like_escape(norm_fragment.lower())}%", pattern),
        )
        return [self._hydrate(r) for r in rows]
