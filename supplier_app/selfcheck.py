"""Headless start-up check against a PostgreSQL server: driver, schema, migrations and all screens offscreen."""

from __future__ import annotations

import logging
import os
import sys
import tempfile
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

log = logging.getLogger(__name__)


@contextmanager
def temporary_database(config) -> Iterator[object]:  # type: ignore[no-untyped-def]
    """A throw-away schema on the configured server (needs no special rights); yields a config that uses it."""
    import psycopg
    from psycopg.conninfo import make_conninfo

    from supplier_app.settings.connection import ConnectionConfig

    schema = f"selfcheck_{uuid.uuid4().hex[:10]}"
    with psycopg.connect(config.dsn(), autocommit=True) as admin:
        admin.execute(f'CREATE SCHEMA "{schema}"')
        try:
            yield ConnectionConfig(dsn_override=make_conninfo(config.dsn(), options=f"-csearch_path={schema}"))
        finally:
            admin.execute(f'DROP SCHEMA "{schema}" CASCADE')


def run_selfcheck(verbose: bool = True) -> int:
    """Return 0 when everything starts, otherwise 1. Needs the server connection (saved settings or SUPPLIERAPP_PG_DSN);
    works in a temporary schema and removes it again."""
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

    def say(msg: str) -> None:
        if verbose:
            print(f"[selfcheck] {msg}", flush=True)

    try:
        import psycopg

        say(f"PostgreSQL driver psycopg {psycopg.__version__}, libpq {psycopg.pq.version()}")
        from supplier_app.main import build_context
        from supplier_app.selfcheck_ui import check_all_screens
        from supplier_app.settings.connection import ConnectionConfig
        from supplier_app.settings.paths import AppPaths, default_paths

        config = ConnectionConfig.load(default_paths().root)
        if not config.is_configured:
            say("kein Datenbank-Server eingerichtet (Verbindung in der App einstellen oder SUPPLIERAPP_PG_DSN setzen)")
            return 1
        with tempfile.TemporaryDirectory(prefix="supplierapp-selfcheck-") as tmp, temporary_database(config) as temp_cfg:
            ctx = build_context(AppPaths(Path(tmp)), temp_cfg)  # type: ignore[arg-type]
            try:
                say(f"database ok, schema version {ctx.storage.db.schema_version()}, server {ctx.storage.db.scalar('SHOW server_version')}")
                ctx.demo.load()
                count = check_all_screens(ctx)
            finally:
                ctx.close()
            say(f"{count} screen/theme combinations built offscreen")
        return 0
    except Exception as exc:  # noqa: BLE001 - report any failure as exit code 1
        log.exception("selfcheck failed")
        print(f"[selfcheck] FAILED: {exc!r}", file=sys.stderr, flush=True)
        return 1
