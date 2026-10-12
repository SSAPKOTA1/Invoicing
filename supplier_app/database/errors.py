"""Backend independent database error classes."""

from __future__ import annotations

import sqlite3

try:  # psycopg is only needed for the server (multi-user) mode
    import psycopg
    import psycopg.errors as _pgerr

    PG_AVAILABLE = True
except ImportError:  # pragma: no cover - psycopg is a requirement, the fallback keeps local mode usable
    psycopg = None  # type: ignore[assignment]
    _pgerr = None  # type: ignore[assignment]
    PG_AVAILABLE = False

#: raised by constraint violations (UNIQUE, CHECK, FOREIGN KEY, triggers) in either backend
INTEGRITY_ERRORS: tuple[type[BaseException], ...] = (
    (sqlite3.IntegrityError, _pgerr.IntegrityError) if PG_AVAILABLE else (sqlite3.IntegrityError,)
)
