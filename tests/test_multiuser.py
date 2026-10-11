"""Real multi-user behaviour against a PostgreSQL server: concurrent users, live refresh, login flow, settings."""

from __future__ import annotations

import threading
from datetime import date

import pytest

from supplier_app.bootstrap import open_storage
from supplier_app.errors import DuplicateError
from supplier_app.models.enums import UserRole
from supplier_app.services.container import build_services
from supplier_app.settings.local_prefs import LocalPrefs
from supplier_app.settings.paths import AppPaths
from tests.helpers import make_scenario


@pytest.fixture()
def clients(pg_dsn, tmp_path):
    """Factory for independent client connections (like several PCs) to one database."""
    opened = []

    def make(name: str):
        paths = AppPaths(tmp_path / f"pc-{name}").ensure()
        storage = open_storage(paths, pg_dsn)
        svc = build_services(storage, multi_user=True, prefs=LocalPrefs(paths.root / "prefs.json"))
        opened.append(storage)
        return svc

    yield make
    for st in opened:
        st.close()


def _run_parallel(jobs):
    barrier = threading.Barrier(len(jobs))
    results: list = [None] * len(jobs)

    def worker(i, job):
        barrier.wait()
        try:
            results[i] = ("ok", job())
        except Exception as exc:  # noqa: BLE001
            results[i] = ("err", exc)

    threads = [threading.Thread(target=worker, args=(i, j)) for i, j in enumerate(jobs)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(60)
    return results


def test_simultaneous_payments_never_pay_an_invoice_twice(clients) -> None:
    first = clients("a")
    sc = make_scenario(first, gross=100000)
    users = [clients(f"u{i}") for i in range(6)]
    results = _run_parallel([
        (lambda s=s: s.payments.record_payment(sc.supplier.id, date(2024, 2, 1), 100000, [sc.invoice.id])) for s in users])
    assert all(kind == "ok" for kind, _ in results), results
    bal = first.ledger.invoice_balance(sc.invoice.id)
    assert bal.balance_cents == 0 and bal.paid_cents == 100000  # exactly one payment was allocated to the invoice
    assert first.ledger.supplier_balance(sc.supplier.id).total_cents == -500000  # the other five are credit on account


def test_simultaneous_invoice_with_the_same_number_is_rejected_once(clients) -> None:
    first = clients("a")
    sc = make_scenario(first)
    users = [clients(f"u{i}") for i in range(5)]
    results = _run_parallel([
        (lambda s=s: s.invoices.create_invoice(sc.supplier.id, "DOPPELT-1", date(2024, 3, 1), gross_cents=1000)) for s in users])
    assert sum(1 for kind, _ in results if kind == "ok") == 1
    assert all(isinstance(r, DuplicateError) for kind, r in results if kind == "err")
    assert len([i for i in first.invoices.list() if i.invoice_number == "DOPPELT-1"]) == 1


def test_changes_of_a_colleague_are_visible_and_attributed(clients) -> None:
    anna, ben = clients("anna"), clients("ben")
    anna.users.create_user("anna", "passwort1", UserRole.ADMIN)
    anna.users.login("anna", "passwort1")
    ben_user = ben.users.users()[0]  # visible on the other PC immediately
    assert ben_user.username == "anna"
    ben.users.create_user("ben", "passwort2", UserRole.EDITOR)
    ben.users.login("ben", "passwort2")
    before = anna.repos.db.data_version()
    sc = make_scenario(ben)
    assert anna.repos.db.data_version() != before and anna.repos.db.data_changed_by() == "ben"
    assert anna.invoices.get(sc.invoice.id).invoice_number == "RE-2024/001"
    audit = anna.repos.audit.list(limit=20)
    assert any(a.username == "ben" and a.entity == "invoice" for a in audit)


def test_documents_are_shared_between_pcs(clients, tmp_path) -> None:
    anna, ben = clients("anna"), clients("ben")
    src = tmp_path / "scan.txt"
    src.write_text("Rechnung Nr. 5\nBrutto 119,00", encoding="utf-8")
    doc, _ = anna.documents.store_file(src)
    seen = ben.documents.get(doc.id)
    path = ben.documents.file_path(seen)  # fetched from the server into Ben's local cache
    assert path.read_text(encoding="utf-8") == src.read_text(encoding="utf-8")
    assert str(path).startswith(str(tmp_path / "pc-ben"))
    again, created = ben.documents.store_file(src)
    assert again.id == doc.id and not created


def test_two_clients_migrating_at_the_same_time(pg_template, tmp_path) -> None:
    """A brand new empty database started by several PCs at once is migrated exactly once."""
    import uuid

    import psycopg

    name = f"t_{uuid.uuid4().hex[:10]}"
    admin = psycopg.connect(pg_template, autocommit=True)
    admin.execute(f'CREATE DATABASE "{name}"')
    dsn = psycopg.conninfo.make_conninfo(pg_template, dbname=name)
    try:
        def start(i: int):
            st = open_storage(AppPaths(tmp_path / f"m{i}").ensure(), dsn)
            version = st.db.schema_version()
            st.close()
            return version

        results = _run_parallel([lambda i=i: start(i) for i in range(4)])
        assert all(kind == "ok" for kind, _ in results), results
        from supplier_app.database.migrations import LATEST_VERSION

        assert {v for _k, v in results} == {LATEST_VERSION}
    finally:
        admin.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
        admin.close()


def test_lost_connection_is_reported_and_recovers(clients) -> None:
    from supplier_app.errors import DatabaseError

    svc = clients("a")
    sc = make_scenario(svc)
    db = svc.repos.db
    db._conn.close()  # simulate a dropped network connection between two operations
    assert svc.invoices.get(sc.invoice.id).invoice_number == "RE-2024/001"  # transparent reconnect
    db._conn.close()
    with pytest.raises(DatabaseError):
        with db.transaction():  # a drop in the middle of a booking is an error, never a half booking
            db._conn.close()
            db.execute("SELECT 1")
    assert svc.invoices.get(sc.invoice.id).id == sc.invoice.id
