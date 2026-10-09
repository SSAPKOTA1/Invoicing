"""Rotating file log."""

from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

_FMT = "%(asctime)s %(levelname)-7s %(name)s: %(message)s"


def setup_logging(log_dir: Path, level: int = logging.INFO) -> None:
    """Configure the root logger with a rotating file handler (idempotent)."""
    root = logging.getLogger()
    root.setLevel(level)
    log_dir.mkdir(parents=True, exist_ok=True)
    target = str(log_dir / "supplier_app.log")
    for h in root.handlers:
        if isinstance(h, RotatingFileHandler) and h.baseFilename == str(Path(target).resolve()):
            return
    handler = RotatingFileHandler(target, maxBytes=1_000_000, backupCount=5, encoding="utf-8")
    handler.setFormatter(logging.Formatter(_FMT))
    root.addHandler(handler)


def shutdown_logging() -> None:
    """Close and detach the rotating file handlers (needed before deleting the log folder on Windows)."""
    root = logging.getLogger()
    for h in list(root.handlers):
        if isinstance(h, RotatingFileHandler):
            h.close()
            root.removeHandler(h)
