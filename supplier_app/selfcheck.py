"""Headless start-up check: database, migrations and (when available) all screens offscreen."""

from __future__ import annotations

import logging
import os
import sys
import tempfile
from pathlib import Path

log = logging.getLogger(__name__)


def run_selfcheck(verbose: bool = True) -> int:
    """Return 0 when everything starts, otherwise 1. Uses a temporary data folder."""
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from supplier_app.bootstrap import open_storage
    from supplier_app.settings.paths import AppPaths

    def say(msg: str) -> None:
        if verbose:
            print(f"[selfcheck] {msg}", flush=True)

    try:
        with tempfile.TemporaryDirectory(prefix="supplierapp-selfcheck-") as tmp:
            storage = open_storage(AppPaths(Path(tmp)))
            version = storage.db.schema_version()
            say(f"database ok, schema version {version}")
            if not storage.db.integrity_ok():
                say("integrity check failed")
                return 1
            try:
                from supplier_app.views.selfcheck_ui import check_all_screens
            except ImportError:
                say("UI not available yet; skipping screens")
            else:
                from supplier_app.main import build_context

                storage.close()
                ctx = build_context(AppPaths(Path(tmp) / "ui"))
                try:
                    count = check_all_screens(ctx)
                finally:
                    ctx.close()
                say(f"{count} screen/theme combinations built offscreen")
                return 0
            storage.close()
        return 0
    except Exception as exc:  # noqa: BLE001 - report any failure as exit code 1
        log.exception("selfcheck failed")
        print(f"[selfcheck] FAILED: {exc!r}", file=sys.stderr, flush=True)
        return 1
