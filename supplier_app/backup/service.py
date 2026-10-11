"""Backup and restore of the server database: all tables (including the document files) as JSON lines in a zip."""

from __future__ import annotations

import json
import zipfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from supplier_app import __version__
from supplier_app.backup.dump import TABLES, clear_database, decode_row, encode_row, iter_rows, load_tables
from supplier_app.database.migrations import LATEST_VERSION
from supplier_app.database.pg import PgDatabase
from supplier_app.errors import BackupError, DatabaseError
from supplier_app.settings.paths import AppPaths

MANIFEST = "manifest.json"
TABLE_FORMAT = "tables-v1"


@dataclass(frozen=True)
class RestoreResult:
    schema_version: int
    documents: int
    safety_backup: Path


class BackupService:
    """Creates and restores backups. Works from every PC; the server itself should additionally be backed up with
    ``pg_dump``."""

    def __init__(self, db: PgDatabase, paths: AppPaths) -> None:
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

    # -- restore ---------------------------------------------------------------
    @staticmethod
    def verify_backup(zip_path: Path) -> dict:
        """Check structure and row counts; returns the manifest."""
        try:
            with zipfile.ZipFile(zip_path) as zf:
                names = zf.namelist()
                for n in names:
                    if n.startswith("/") or ".." in Path(n).parts:
                        raise BackupError("Die Sicherung enthält unzulässige Pfade.")
                if MANIFEST not in names:
                    raise BackupError("Die Datei ist keine gültige Sicherung (Manifest fehlt).")
                bad = zf.testzip()
                if bad:
                    raise BackupError(f"Die Sicherung ist beschädigt (Eintrag '{bad}').")
                manifest = json.loads(zf.read(MANIFEST))
                if manifest.get("format") != TABLE_FORMAT:
                    raise BackupError("Die Datei ist keine Sicherung dieser Programmversion.")
                for table, count in manifest.get("rows", {}).items():
                    if f"tables/{table}.jsonl" not in names:
                        raise BackupError(f"Tabelle '{table}' fehlt in der Sicherung.")
                    if sum(1 for _ in zf.open(f"tables/{table}.jsonl")) != count:
                        raise BackupError(f"Tabelle '{table}' ist unvollständig (Zeilenzahl stimmt nicht).")
        except (zipfile.BadZipFile, json.JSONDecodeError, OSError) as exc:
            raise BackupError(f"Die Datei ist keine lesbare Sicherung: {exc}") from exc
        if int(manifest.get("schema_version", 0)) > LATEST_VERSION:
            raise BackupError("Die Sicherung stammt von einer neueren Programmversion.")
        return manifest

    def restore_backup(self, zip_path: Path) -> RestoreResult:
        """Replace ALL server data with the backup (the old state is kept as a safety backup)."""
        zip_path = Path(zip_path)
        manifest = self.verify_backup(zip_path)
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
