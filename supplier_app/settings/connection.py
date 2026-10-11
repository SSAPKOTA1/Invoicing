"""How the application reaches its data: local SQLite file (single user) or a PostgreSQL server (several users).

The choice is stored on this PC (``connection.json`` in the application data folder); the environment variable
``SUPPLIERAPP_PG_DSN`` overrides it (IT roll-out, tests).
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import asdict, dataclass
from pathlib import Path

from supplier_app.errors import ValidationError

log = logging.getLogger(__name__)

MODE_LOCAL = "local"
MODE_SERVER = "server"
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
    dsn_override: str = ""  # complete libpq connection string (environment variable); not saved

    @property
    def is_server(self) -> bool:
        return self.mode == MODE_SERVER

    def validate(self) -> None:
        if self.mode not in (MODE_LOCAL, MODE_SERVER):
            raise ValidationError("Unbekannter Betriebsmodus.")
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


def test_connection(config: ConnectionConfig) -> str:
    """Try to log in; returns the server version text or raises :class:`DatabaseError`-like errors with a hint."""
    from supplier_app.database.pg import PgDatabase

    db = PgDatabase(config.dsn()).connect()
    try:
        return str(db.scalar("SHOW server_version", default=""))
    finally:
        db.close()
