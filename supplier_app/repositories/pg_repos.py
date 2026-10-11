"""Composition of all PostgreSQL repositories."""

from __future__ import annotations

from contextlib import AbstractContextManager

from supplier_app.database.pg import PgDatabase
from supplier_app.repositories.interfaces import Repositories
from supplier_app.repositories.pg_documents import (
    PgCaseRepository,
    PgDocumentRepository,
    PgReferenceRepository,
)
from supplier_app.repositories.pg_invoices import PgInvoiceRepository, PgLedgerRepository
from supplier_app.repositories.pg_misc import (
    PgAuditRepository,
    PgCategoryRepository,
    PgRateRepository,
    PgSettingsRepository,
)
from supplier_app.repositories.pg_notices import PgNoticeRepository, PgPaymentRepository
from supplier_app.repositories.pg_organization import PgOrganizationRepository
from supplier_app.repositories.pg_parties import PgPartyRepository
from supplier_app.repositories.pg_users import PgUserRepository


class PgRepositories(Repositories):
    """All repositories bound to one :class:`PgDatabase`."""

    def __init__(self, db: PgDatabase) -> None:
        self.db = db
        self.parties = PgPartyRepository(db)
        self.invoices = PgInvoiceRepository(db)
        self.ledger = PgLedgerRepository(db)
        self.notices = PgNoticeRepository(db)
        self.payments = PgPaymentRepository(db)
        self.documents = PgDocumentRepository(db)
        self.references = PgReferenceRepository(db)
        self.cases = PgCaseRepository(db)
        self.settings = PgSettingsRepository(db)
        self.rates = PgRateRepository(db)
        self.categories = PgCategoryRepository(db)
        self.audit = PgAuditRepository(db)
        self.organization = PgOrganizationRepository(db)
        self.users = PgUserRepository(db)

    def transaction(self) -> AbstractContextManager[None]:
        return self.db.transaction()
