"""Composition of all SQLite repositories."""

from __future__ import annotations

from contextlib import AbstractContextManager

from supplier_app.database.connection import Database
from supplier_app.repositories.interfaces import Repositories
from supplier_app.repositories.sqlite_documents import (
    SqliteCaseRepository,
    SqliteDocumentRepository,
    SqliteReferenceRepository,
)
from supplier_app.repositories.sqlite_invoices import SqliteInvoiceRepository, SqliteLedgerRepository
from supplier_app.repositories.sqlite_misc import (
    SqliteAuditRepository,
    SqliteCategoryRepository,
    SqliteRateRepository,
    SqliteSettingsRepository,
)
from supplier_app.repositories.sqlite_notices import SqliteNoticeRepository, SqlitePaymentRepository
from supplier_app.repositories.sqlite_parties import SqlitePartyRepository


class SqliteRepositories(Repositories):
    """All repositories bound to one :class:`Database`."""

    def __init__(self, db: Database) -> None:
        self.db = db
        self.parties = SqlitePartyRepository(db)
        self.invoices = SqliteInvoiceRepository(db)
        self.ledger = SqliteLedgerRepository(db)
        self.notices = SqliteNoticeRepository(db)
        self.payments = SqlitePaymentRepository(db)
        self.documents = SqliteDocumentRepository(db)
        self.references = SqliteReferenceRepository(db)
        self.cases = SqliteCaseRepository(db)
        self.settings = SqliteSettingsRepository(db)
        self.rates = SqliteRateRepository(db)
        self.categories = SqliteCategoryRepository(db)
        self.audit = SqliteAuditRepository(db)

    def transaction(self) -> AbstractContextManager[None]:
        return self.db.transaction()
