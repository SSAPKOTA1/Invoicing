"""Shared fixtures."""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from supplier_app.bootstrap import Storage, open_memory_storage, open_storage  # noqa: E402
from supplier_app.settings.paths import AppPaths  # noqa: E402

FIXTURES = Path(__file__).parent / "fixtures"


PG_BASE_DSN = os.environ.get("SUPPLIER_TEST_PG_DSN", "")
BACKENDS = ["sqlite", "postgres"] if PG_BASE_DSN else ["sqlite"]


@pytest.fixture(scope="session")
def pg_template() -> Iterator[str]:
    """A migrated template database; every test gets a fresh copy (fast) on the test server."""
    if not PG_BASE_DSN:
        pytest.skip("SUPPLIER_TEST_PG_DSN not set (no PostgreSQL test server)")
    import psycopg

    from supplier_app.database.migrator import migrate_postgres
    from supplier_app.database.pg import PgDatabase

    admin = psycopg.connect(PG_BASE_DSN, autocommit=True)
    admin.execute("DROP DATABASE IF EXISTS supplier_tpl WITH (FORCE)")
    admin.execute("CREATE DATABASE supplier_tpl")
    tpl_dsn = psycopg.conninfo.make_conninfo(PG_BASE_DSN, dbname="supplier_tpl")
    db = PgDatabase(tpl_dsn).connect()
    migrate_postgres(db)
    db.close()
    yield PG_BASE_DSN
    admin.execute("DROP DATABASE IF EXISTS supplier_tpl WITH (FORCE)")
    admin.close()


@pytest.fixture()
def pg_dsn(pg_template: str, request: pytest.FixtureRequest) -> Iterator[str]:
    """DSN of a private, freshly migrated database for one test."""
    import uuid

    import psycopg

    name = f"t_{uuid.uuid4().hex[:12]}"
    admin = psycopg.connect(pg_template, autocommit=True)
    admin.execute(f'CREATE DATABASE "{name}" TEMPLATE supplier_tpl')
    yield psycopg.conninfo.make_conninfo(pg_template, dbname=name)
    admin.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
    admin.close()


@pytest.fixture(params=BACKENDS)
def storage(request: pytest.FixtureRequest, tmp_path: Path) -> Iterator[Storage]:
    """In-memory SQLite and (when a test server is configured) PostgreSQL: the same tests run on both."""
    if request.param == "sqlite":
        st = open_memory_storage()
    else:
        from supplier_app.bootstrap import open_pg_storage

        st = open_pg_storage(AppPaths(tmp_path / "pgdata").ensure(), request.getfixturevalue("pg_dsn"))
    yield st
    st.close()


@pytest.fixture()
def repos(storage: Storage):
    return storage.repos


@pytest.fixture()
def file_storage(tmp_path: Path) -> Iterator[Storage]:
    st = open_storage(AppPaths(tmp_path / "data"))
    yield st
    st.close()


from supplier_app.services.container import Services, build_services  # noqa: E402


@pytest.fixture()
def svc(storage: Storage) -> Services:
    return build_services(storage)


@pytest.fixture()
def file_svc(file_storage: Storage) -> Services:
    return build_services(file_storage)


@pytest.fixture(autouse=True)
def _german_by_default():
    """Tests that switch the interface language must not leak it into other tests."""
    from supplier_app.i18n import set_language

    set_language("de")
    yield
    set_language("de")


@pytest.fixture(autouse=True)
def _no_modal_dialogs(monkeypatch):
    """Modal dialogs would block a headless test run: make exec() return immediately."""
    try:
        from PySide6.QtWidgets import QDialog, QMessageBox
    except ImportError:  # pragma: no cover
        return
    monkeypatch.setattr(QMessageBox, "exec", lambda self: 0)
    monkeypatch.setattr(QDialog, "exec", lambda self: 0)


@pytest.fixture(scope="session", autouse=True)
def _qt_cleanup():
    """Tear Qt down in a defined order so the interpreter does not crash at exit."""
    yield
    try:
        import gc

        from PySide6.QtCore import QEvent
        from PySide6.QtWidgets import QApplication
    except ImportError:  # pragma: no cover
        return
    app = QApplication.instance()
    if app is not None:
        for top in app.topLevelWidgets():
            top.deleteLater()
        app.closeAllWindows()
        app.processEvents()
        QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        gc.collect()
