"""Application data locations (``%APPDATA%/SupplierApp`` on Windows)."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from platformdirs import user_data_dir

from supplier_app import APP_NAME


@dataclass(frozen=True)
class AppPaths:
    """``root`` holds the data (database, documents, backups). In the shared-folder mode it is the shared folder and
    ``local_root`` keeps everything that belongs to this PC (logs, exports, connection settings, preferences)."""

    root: Path
    local_root: Path | None = None

    @property
    def local(self) -> Path:
        return self.local_root or self.root

    @property
    def database(self) -> Path:
        return self.root / "supplier.db"

    @property
    def documents(self) -> Path:
        return self.root / "documents"

    @property
    def backups(self) -> Path:
        return self.root / "backups"

    @property
    def logs(self) -> Path:
        return self.local / "logs"

    @property
    def exports(self) -> Path:
        return self.local / "exports"

    def ensure(self) -> AppPaths:
        for p in (self.root, self.local, self.documents, self.backups, self.logs, self.exports):
            p.mkdir(parents=True, exist_ok=True)
        return self


def default_paths() -> AppPaths:
    """Data folder; override with env ``SUPPLIERAPP_DATA`` (tests, portable use)."""
    override = os.environ.get("SUPPLIERAPP_DATA")
    if override:
        return AppPaths(Path(override))
    return AppPaths(Path(user_data_dir(APP_NAME, appauthor=False, roaming=True)))
