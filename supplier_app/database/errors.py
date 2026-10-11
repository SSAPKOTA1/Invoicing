"""Database error classes (PostgreSQL)."""

from __future__ import annotations

import psycopg
import psycopg.errors as _pgerr

#: raised by constraint violations (UNIQUE, CHECK, FOREIGN KEY, triggers)
INTEGRITY_ERRORS: tuple[type[BaseException], ...] = (_pgerr.IntegrityError,)

__all__ = ["INTEGRITY_ERRORS", "psycopg"]
