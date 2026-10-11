"""How the application reaches its data: local SQLite file (single user) or a PostgreSQL server (several users).

The choice is stored on this PC (``connection.json`` in the application data folder); the environment variable
``SUPPLIERAPP_PG_DSN`` overrides it (IT roll-out, tests).
"""

from __future__ import annotations

import json
import logging
import os
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path

from supplier_app.errors import ValidationError

log = logging.getLogger(__name__)

MODE_LOCAL = "local"
MODE_SERVER = "server"
MODE_SHARED = "shared"
FILE_NAME = "connection.json"


@dataclass
class ConnectionConfig:
    mode: str = MODE_LOCAL
    host: str = ""
    port: int = 5432
    dbname: str = "supplierapp"
    user: str = "supplierapp"
    password: str = ""
    sslmode: str = "prefer"
    shared_path: str = ""  # shared folder mode: the folder (network drive) that holds database and documents
    dsn_override: str = ""  # complete libpq connection string (environment variable); not saved

    @property
    def is_server(self) -> bool:
        return self.mode == MODE_SERVER

    @property
    def is_shared(self) -> bool:
        return self.mode == MODE_SHARED

    @property
    def is_multi_user(self) -> bool:
        return self.mode in (MODE_SERVER, MODE_SHARED)

    def validate(self) -> None:
        if self.mode not in (MODE_LOCAL, MODE_SERVER, MODE_SHARED):
            raise ValidationError("Unbekannter Betriebsmodus.")
        if self.is_shared:
            check_shared_folder(self.shared_path)
        if self.is_server and not self.dsn_override:
            if not self.host.strip():
                raise ValidationError("Bitte den Namen oder die Adresse des Datenbank-Servers angeben.")
            if not 1 <= int(self.port) <= 65535:
                raise ValidationError("Der Port muss zwischen 1 und 65535 liegen.")
            if not self.dbname.strip() or not self.user.strip():
                raise ValidationError("Bitte Datenbankname und Benutzer des Servers angeben.")

    def dsn(self) -> str:
        """libpq connection string."""
        if self.dsn_override:
            return self.dsn_override
        from psycopg.conninfo import make_conninfo

        return make_conninfo(host=self.host.strip(), port=int(self.port), dbname=self.dbname.strip(), user=self.user.strip(),
                             password=self.password or None, sslmode=self.sslmode, application_name="SupplierApp",
                             connect_timeout=8)

    @property
    def server_label(self) -> str:
        if self.is_shared:
            return self.shared_path
        if self.dsn_override:
            return "Datenbank-Server"
        return f"{self.host}:{self.port}/{self.dbname}"

    # -- persistence ------------------------------------------------------------------------------------
    @classmethod
    def load(cls, folder: Path | str) -> ConnectionConfig:
        env = os.environ.get("SUPPLIERAPP_PG_DSN", "").strip()
        if env:
            return cls(mode=MODE_SERVER, dsn_override=env)
        path = Path(folder) / FILE_NAME
        try:
            if path.exists():
                data = json.loads(path.read_text(encoding="utf-8"))
                known = {k: v for k, v in data.items() if k in cls.__dataclass_fields__ and k != "dsn_override"}
                cfg = cls(**known)
                cfg.port = int(cfg.port)
                return cfg
        except (OSError, ValueError, TypeError):
            log.warning("connection settings unreadable, using local mode", exc_info=True)
        return cls()

    def save(self, folder: Path | str, *, keep_password: bool = True) -> None:
        path = Path(folder) / FILE_NAME
        path.parent.mkdir(parents=True, exist_ok=True)
        data = asdict(self)
        data.pop("dsn_override", None)
        if not keep_password:
            data["password"] = ""
        path.write_text(json.dumps(data, indent=1), encoding="utf-8")
        try:
            path.chmod(0o600)  # the password is stored here: owner only (Windows: the user profile is private anyway)
        except OSError:
            pass


#: folders that synchronise files in the background: a database file there gets corrupted sooner or later
_SYNC_FOLDERS = ("onedrive", "dropbox", "google drive", "googledrive", "icloud", "icloudrive", "nextcloud", "owncloud", "box sync",
                 "sync.com", "pcloud", "mega")


def check_shared_folder(folder: str) -> Path:
    """The shared folder must exist, be writable and must not be a cloud-synchronised folder."""
    text = (folder or "").strip()
    if not text:
        raise ValidationError("Bitte den gemeinsamen Ordner (Netzlaufwerk) angeben.")
    path = Path(text)
    lowered = [part.lower() for part in path.parts]
    if any(any(marker in part for marker in _SYNC_FOLDERS) for part in lowered):
        raise ValidationError(
            "Dieser Ordner wird von einem Cloud-Dienst (OneDrive, Dropbox …) synchronisiert. Dort wird die Datenbank "
            "beschädigt. Bitte einen normalen Ordner auf einem Netzlaufwerk oder Server-PC wählen.")
    if not path.is_dir():
        raise ValidationError(f"Der Ordner '{text}' ist nicht erreichbar. Prüfen Sie Netzwerk und Laufwerksverbindung.")
    probe = path / f".schreibtest-{uuid.uuid4().hex[:12]}"  # unique: colleagues test at the same time
    try:
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
    except OSError as exc:
        raise ValidationError(f"In den Ordner '{text}' kann nicht geschrieben werden: {exc}") from exc
    return path


def test_connection(config: ConnectionConfig) -> str:
    """Try to log in; returns the server version text or raises :class:`DatabaseError`-like errors with a hint."""
    if config.is_shared:
        check_shared_folder(config.shared_path)
        return "gemeinsamer Ordner"
    from supplier_app.database.pg import PgDatabase

    db = PgDatabase(config.dsn()).connect()
    try:
        return str(db.scalar("SHOW server_version", default=""))
    finally:
        db.close()
