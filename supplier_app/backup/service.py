"""Backup (database + documents as .zip) and restore with integrity checks."""

from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
import tempfile
import zipfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from supplier_app import __version__
from supplier_app.backup.dump import TABLES, clear_database, decode_row, encode_row, iter_rows, load_tables
from supplier_app.database.connection import Database
from supplier_app.database.migrations import LATEST_VERSION
from supplier_app.database.migrator import migrate
from supplier_app.errors import BackupError, DatabaseError
from supplier_app.settings.paths import AppPaths

MANIFEST = "manifest.json"
TABLE_FORMAT = "tables-v1"
DB_NAME = "supplier.db"


@dataclass(frozen=True)
class RestoreResult:
    schema_version: int
    documents: int
    safety_backup: Path


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


class BackupService:
    """Creates and restores backups. ``db`` is reconnected after a restore."""

    def __init__(self, db: Database, paths: AppPaths) -> None:
        self.db = db
        self.paths = paths

    # -- backup ----------------------------------------------------------------
    @property
    def server_mode(self) -> bool:
        return getattr(self.db, "backend", "sqlite") == "postgres"

    def create_backup(self, target: Path | None = None) -> Path:
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        target = Path(target) if target else self.paths.backups / f"SupplierApp-Backup-{stamp}.zip"
        if target.is_dir() or target.suffix.lower() != ".zip":
            target = target / f"SupplierApp-Backup-{stamp}.zip"
        target.parent.mkdir(parents=True, exist_ok=True)
        if self.server_mode:
            return self._create_server_backup(target)
        try:
            with tempfile.TemporaryDirectory(prefix="supplierapp-bk-") as tmp:
                snap = Path(tmp) / DB_NAME
                dst = sqlite3.connect(str(snap))
                try:
                    self.db.conn.backup(dst)
                finally:
                    dst.close()
                docs = sorted(p for p in self.paths.documents.glob("*") if p.is_file())
                manifest = {
                    "app_version": __version__, "schema_version": self.db.schema_version(),
                    "created": datetime.now().isoformat(timespec="seconds"), "db_sha256": _sha256(snap),
                    "documents": {p.name: _sha256(p) for p in docs},
                }
                with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as zf:
                    zf.write(snap, DB_NAME)
                    for p in docs:
                        zf.write(p, f"documents/{p.name}")
                    zf.writestr(MANIFEST, json.dumps(manifest, indent=1))
        except (OSError, sqlite3.Error) as exc:
            target.unlink(missing_ok=True)
            raise BackupError(f"Die Sicherung konnte nicht erstellt werden: {exc}") from exc
        return target

    def _create_server_backup(self, target: Path) -> Path:
        """All tables (incl. the document files) as JSON lines in a zip; works from every client PC."""
        try:
            with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as zf:
                counts: dict[str, int] = {}
                for table in TABLES:
                    n = 0
                    with zf.open(f"tables/{table}.jsonl", "w") as fh:
                        for row in iter_rows(self.db, table):
                            fh.write((encode_row(table, row) + "\n").encode("utf-8"))
                            n += 1
                    counts[table] = n
                manifest = {"format": TABLE_FORMAT, "app_version": __version__, "schema_version": self.db.schema_version(),
                            "created": datetime.now().isoformat(timespec="seconds"), "rows": counts}
                zf.writestr(MANIFEST, json.dumps(manifest, indent=1))
        except (OSError, DatabaseError) as exc:
            target.unlink(missing_ok=True)
            raise BackupError(f"Die Sicherung konnte nicht erstellt werden: {exc}") from exc
        return target

    @staticmethod
    def _verify_server_backup(zf: zipfile.ZipFile) -> dict:
        manifest = json.loads(zf.read(MANIFEST))
        if manifest.get("format") != TABLE_FORMAT:
            raise BackupError("Diese Sicherung stammt aus dem Einzelplatz-Modus und kann nicht in den Server eingespielt werden.")
        for table, count in manifest.get("rows", {}).items():
            if f"tables/{table}.jsonl" not in zf.namelist():
                raise BackupError(f"Tabelle '{table}' fehlt in der Sicherung.")
            if sum(1 for _ in zf.open(f"tables/{table}.jsonl")) != count:
                raise BackupError(f"Tabelle '{table}' ist unvollständig (Zeilenzahl stimmt nicht).")
        return manifest

    def _restore_server_backup(self, zip_path: Path, manifest: dict) -> RestoreResult:
        safety = self.create_backup(self.paths.backups / f"pre-restore-{datetime.now():%Y%m%d-%H%M%S}.zip")
        try:
            with zipfile.ZipFile(zip_path) as zf, self.db.transaction():
                clear_database(self.db)

                def rows(table: str):  # type: ignore[no-untyped-def]
                    name = f"tables/{table}.jsonl"
                    if name not in zf.namelist():
                        return iter(())
                    return (decode_row(table, line.decode("utf-8")) for line in zf.open(name))

                load_tables(self.db, rows)
        except (OSError, DatabaseError) as exc:
            raise BackupError(f"Die Wiederherstellung ist fehlgeschlagen: {exc}. Sicherung des alten Stands: {safety}") from exc
        for cached in self.paths.documents.glob("*"):  # the local cache is refilled from the database on demand
            if cached.is_file():
                cached.unlink()
        return RestoreResult(int(manifest["schema_version"]), int(manifest["rows"].get("documents", 0)), safety)

    # -- restore ---------------------------------------------------------------
    @staticmethod
    def verify_backup(zip_path: Path) -> dict:
        """Check structure, hashes and database integrity; returns the manifest."""
        try:
            with zipfile.ZipFile(zip_path) as zf:
                names = zf.namelist()
                for n in names:
                    if n.startswith("/") or ".." in Path(n).parts:
                        raise BackupError("Die Sicherung enthält unzulässige Pfade.")
                if MANIFEST in names and json.loads(zf.read(MANIFEST)).get("format") == TABLE_FORMAT:
                    if int(json.loads(zf.read(MANIFEST)).get("schema_version", 0)) > LATEST_VERSION:
                        raise BackupError("Die Sicherung stammt von einer neueren Programmversion.")
                    return BackupService._verify_server_backup(zf)
                for n in names:
                    if n.startswith("/") or ".." in Path(n).parts:
                        raise BackupError("Die Sicherung enthält unzulässige Pfade.")
                if MANIFEST not in names or DB_NAME not in names:
                    raise BackupError("Die Datei ist keine gültige Sicherung (Manifest oder Datenbank fehlt).")
                bad = zf.testzip()
                if bad:
                    raise BackupError(f"Die Sicherung ist beschädigt (Eintrag '{bad}').")
                manifest = json.loads(zf.read(MANIFEST))
                with tempfile.TemporaryDirectory(prefix="supplierapp-vf-") as tmp:
                    dbp = Path(tmp) / DB_NAME
                    dbp.write_bytes(zf.read(DB_NAME))
                    if _sha256(dbp) != manifest.get("db_sha256"):
                        raise BackupError("Die Datenbank in der Sicherung ist verändert oder beschädigt (Prüfsumme).")
                    con = sqlite3.connect(str(dbp))
                    try:
                        if con.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                            raise BackupError("Die Datenbank in der Sicherung ist beschädigt.")
                    finally:
                        con.close()
                for name, digest in manifest.get("documents", {}).items():
                    if f"documents/{name}" not in names:
                        raise BackupError(f"Dokument '{name}' fehlt in der Sicherung.")
                    if hashlib.sha256(zf.read(f"documents/{name}")).hexdigest() != digest:
                        raise BackupError(f"Dokument '{name}' ist beschädigt (Prüfsumme).")
        except (zipfile.BadZipFile, json.JSONDecodeError, OSError) as exc:
            raise BackupError(f"Die Datei ist keine lesbare Sicherung: {exc}") from exc
        if int(manifest.get("schema_version", 0)) > LATEST_VERSION:
            raise BackupError("Die Sicherung stammt von einer neueren Programmversion.")
        return manifest

    def restore_backup(self, zip_path: Path) -> RestoreResult:
        """Replace the current data with the backup; the old state is kept as a safety backup."""
        zip_path = Path(zip_path)
        manifest = self.verify_backup(zip_path)
        if self.server_mode:
            if manifest.get("format") != TABLE_FORMAT:
                raise BackupError("Diese Sicherung stammt aus dem Einzelplatz-Modus und kann nicht in den Server eingespielt werden.")
            return self._restore_server_backup(zip_path, manifest)
        if manifest.get("format") == TABLE_FORMAT:
            raise BackupError("Diese Sicherung stammt aus dem Server-Modus und kann nicht in den Einzelplatz-Modus eingespielt werden.")
        safety = self.create_backup(self.paths.backups / f"pre-restore-{datetime.now():%Y%m%d-%H%M%S}.zip")
        db_path = Path(self.db.path)
        with tempfile.TemporaryDirectory(prefix="supplierapp-rs-") as tmp:
            tmp_dir = Path(tmp)
            with zipfile.ZipFile(zip_path) as zf:
                zf.extractall(tmp_dir)
            self.db.close()
            try:
                for suffix in ("-wal", "-shm"):
                    Path(str(db_path) + suffix).unlink(missing_ok=True)
                shutil.copy2(tmp_dir / DB_NAME, db_path)
                self.paths.documents.mkdir(parents=True, exist_ok=True)
                for existing in self.paths.documents.glob("*"):
                    if existing.is_file():
                        existing.unlink()
                for src in (tmp_dir / "documents").glob("*"):
                    shutil.copy2(src, self.paths.documents / src.name)
            except OSError as exc:
                self.db.connect()
                raise BackupError(
                    f"Die Wiederherstellung ist fehlgeschlagen: {exc}. Sicherung des alten Stands: {safety}") from exc
        migrate(db_path, self.paths.backups / "migrations")
        self.db.connect()
        return RestoreResult(int(manifest["schema_version"]), len(manifest.get("documents", {})), safety)
