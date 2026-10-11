"""How the program reaches its PostgreSQL server.

The settings are stored on this PC (``connection.json`` in the application data folder). A ``connection.json`` next to the
program (when the program lives in a shared folder) pre-fills them for every PC - without the password, which each PC
enters once. The environment variable ``SUPPLIERAPP_PG_DSN`` overrides everything (IT roll-out, tests).
"""

from __future__ import annotations

import json
import logging
import os
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

from supplier_app.errors import ValidationError

log = logging.getLogger(__name__)

FILE_NAME = "connection.json"


@dataclass
class ConnectionConfig:
    host: str = ""
    port: int = 5432
    dbname: str = "supplierapp"
    user: str = "supplierapp"
    password: str = ""
    sslmode: str = "prefer"
    dsn_override: str = ""  # complete libpq connection string (environment variable); not saved

    @property
    def is_configured(self) -> bool:
        return bool(self.dsn_override or self.host.strip())

    def validate(self) -> None:
        if self.dsn_override:
            return
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
        if self.dsn_override:
            return "Datenbank-Server"
        return f"{self.host}:{self.port}/{self.dbname}"

    # -- persistence ------------------------------------------------------------------------------------
    @classmethod
    def load(cls, folder: Path | str) -> ConnectionConfig:
        env = os.environ.get("SUPPLIERAPP_PG_DSN", "").strip()
        if env:
            return cls(dsn_override=env)
        path = Path(folder) / FILE_NAME
        if not path.exists():
            path = program_config_path()  # settings next to the program (shared program folder): same for every PC
        try:
            if path.exists():
                data = json.loads(path.read_text(encoding="utf-8"))
                known = {k: v for k, v in data.items() if k in cls.__dataclass_fields__ and k != "dsn_override"}
                cfg = cls(**known)
                cfg.port = int(cfg.port)
                return cfg
        except (OSError, ValueError, TypeError):
            log.warning("connection settings unreadable", exc_info=True)
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

    def save_for_all_pcs(self) -> Path:
        """Store server, database and user next to the program (never the password), so that every PC that starts the
        program from there is pre-configured."""
        target = program_config_path()
        if target.parent.name == "__none__":
            raise ValidationError("Das Programm läuft nicht aus einem Programmordner (nur im installierten Paket möglich).")
        try:
            self.save(target.parent, keep_password=False)
        except OSError as exc:
            raise ValidationError(f"In den Programmordner kann nicht geschrieben werden: {exc}") from exc
        return target


def program_config_path() -> Path:
    """``connection.json`` next to the program (``SupplierApp.exe``)."""
    override = os.environ.get("SUPPLIERAPP_PROGRAM_DIR")
    base = Path(override) if override else Path(sys.executable).parent if getattr(sys, "frozen", False) else None
    return (base / FILE_NAME) if base is not None else Path("__none__") / FILE_NAME


def test_connection(config: ConnectionConfig) -> str:
    """Try to log in; returns the server version text or raises :class:`DatabaseError` (with a hint)."""
    from supplier_app.database.pg import PgDatabase

    db = PgDatabase(config.dsn()).connect()
    try:
        return str(db.scalar("SHOW server_version", default=""))
    finally:
        db.close()
