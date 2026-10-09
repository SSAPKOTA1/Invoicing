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
from supplier_app.database.connection import Database
from supplier_app.database.migrations import LATEST_VERSION
from supplier_app.database.migrator import migrate
from supplier_app.errors import BackupError
from supplier_app.settings.paths import AppPaths

MANIFEST = "manifest.json"
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
    def create_backup(self, target: Path | None = None) -> Path:
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        target = Path(target) if target else self.paths.backups / f"SupplierApp-Backup-{stamp}.zip"
        if target.is_dir() or target.suffix.lower() != ".zip":
            target = target / f"SupplierApp-Backup-{stamp}.zip"
        target.parent.mkdir(parents=True, exist_ok=True)
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
