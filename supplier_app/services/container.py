"""Wires all services together (constructor injection, no globals)."""

from __future__ import annotations

from dataclasses import dataclass

from supplier_app.backup.service import BackupService
from supplier_app.bootstrap import Storage
from supplier_app.repositories.interfaces import Repositories
from supplier_app.services.bank_service import BankService
from supplier_app.services.case_service import CaseService
from supplier_app.services.document_service import DocumentService
from supplier_app.services.dunning_service import DunningService
from supplier_app.services.history_service import HistoryService
from supplier_app.services.ingest_service import IngestService, make_text_extractor
from supplier_app.services.invoice_service import InvoiceService
from supplier_app.services.ledger_service import LedgerService
from supplier_app.services.organization_service import OrganizationService
from supplier_app.services.payment_service import PaymentService
from supplier_app.services.pin_service import PinService
from supplier_app.services.recurring_service import RecurringService
from supplier_app.services.search_service import SearchService
from supplier_app.services.session import Session
from supplier_app.services.settings_service import SettingsService
from supplier_app.services.supplier_service import SupplierService
from supplier_app.services.user_service import UserService
from supplier_app.settings.local_prefs import LocalPrefs


@dataclass
class Services:
    repos: Repositories
    settings: SettingsService
    pin: PinService
    suppliers: SupplierService
    ledger: LedgerService
    cases: CaseService
    invoices: InvoiceService
    payments: PaymentService
    dunning: DunningService
    history: HistoryService
    search: SearchService
    documents: DocumentService
    backup: BackupService
    ingest: IngestService
    organization: OrganizationService
    recurring: RecurringService
    bank: BankService
    users: UserService
    session: Session


def build_services(storage: Storage, *, multi_user: bool = False, prefs: LocalPrefs | None = None,
                   files_in_database: bool | None = None) -> Services:
    repos = storage.repos
    settings = SettingsService(repos, prefs if multi_user else None)
    settings.ensure_defaults()
    session = Session(multi_user=multi_user)
    ledger = LedgerService(repos, settings)
    cases = CaseService(repos)
    suppliers = SupplierService(repos)
    invoices = InvoiceService(repos, ledger, cases, settings)
    payments = PaymentService(repos, ledger, cases, settings)
    dunning = DunningService(repos, ledger, cases, settings)
    if files_in_database is None:
        files_in_database = multi_user and storage.db.backend == "postgres"  # shared folder mode keeps the files in the folder
    documents = DocumentService(repos, storage.paths, files_in_database=files_in_database)
    extractor = make_text_extractor(settings)
    ingest = IngestService(repos, documents, extractor, settings, ledger, suppliers, invoices,
                           payments, dunning)
    return Services(
        repos=repos,
        settings=settings,
        pin=PinService(repos),
        suppliers=suppliers,
        ledger=ledger,
        cases=cases,
        invoices=invoices,
        payments=payments,
        dunning=dunning,
        history=HistoryService(repos, ledger),
        search=SearchService(repos),
        documents=documents,
        backup=BackupService(storage.db, storage.paths),
        ingest=ingest,
        organization=OrganizationService(repos),
        recurring=RecurringService(repos, invoices),
        bank=BankService(repos, ledger, payments, pdf_text=lambda p: extractor.extract(p).text),
        users=UserService(repos, session),
        session=session,
    )
