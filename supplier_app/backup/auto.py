"""Automatic daily copy of the shared database (the safety net of the shared-folder mode)."""

from __future__ import annotations

import logging
import sqlite3
from datetime import date
from pathlib import Path

from supplier_app.database.connection import Database

log = logging.getLogger(__name__)
KEEP_DAYS = 14


def ensure_daily_backup(db: Database, folder: Path, keep: int = KEEP_DAYS, today: date | None = None) -> Path | None:
    """Create ``supplier-YYYY-MM-DD.db`` once per day (consistent copy through SQLite's backup API) and keep the last
    ``keep`` copies. Returns the new file or ``None`` when today's copy exists or the copy failed (never fatal)."""
    day = (today or date.today()).isoformat()
    target = folder / f"supplier-{day}.db"
    try:
        folder.mkdir(parents=True, exist_ok=True)
        if target.exists():
            return None
        tmp = folder / f".{target.name}.part"
        dst = sqlite3.connect(str(tmp))
        try:
            db.conn.backup(dst)
        finally:
            dst.close()
        tmp.replace(target)
        for old in sorted(folder.glob("supplier-*.db"))[:-keep]:
            old.unlink(missing_ok=True)
        return target
    except (OSError, sqlite3.Error):
        log.warning("daily backup failed", exc_info=True)
        return None
