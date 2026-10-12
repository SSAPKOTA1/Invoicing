"""Bank statements: import, recognise supplier and invoices, let the user correct, book the payments."""

from __future__ import annotations

import hashlib
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from supplier_app.ai.names import similarity
from supplier_app.bank.matcher import BankMatch, BankMatcher, MatchContext, SupplierEvidence
from supplier_app.bank.model import ParsedStatement, ParsedTransaction
from supplier_app.bank.parsers import parse_statement_file
from supplier_app.errors import (
    AccountRequiredError,
    DuplicateError,
    LedgerError,
    NotFoundError,
    ValidationError,
)
from supplier_app.models.entities import BankAccount, BankStatement, BankTransaction, Payment
from supplier_app.models.enums import BankTxStatus, PartyRole, PaymentMethod
from supplier_app.repositories.interfaces import Repositories
from supplier_app.services.base import ServiceBase, atomic
from supplier_app.services.ledger_service import LedgerService
from supplier_app.services.organization_service import OrganizationService
from supplier_app.services.payment_service import PaymentService
from supplier_app.util.money import format_cents
from supplier_app.util.normalize import normalize_iban, normalize_name, normalize_reference, valid_iban

SURE_CONFIDENCE = 0.85  # "matched" proposals at or above this are booked by "book all sure ones"
MATCHED_CONFIDENCE = 0.7


@dataclass
class BankImportResult:
    statement: BankStatement
    account: BankAccount
    created: int = 0
    duplicates: int = 0
    matched: int = 0
    account_created: bool = False
    warnings: list[str] = field(default_factory=list)


@dataclass
class BookReport:
    booked: list[int] = field(default_factory=list)
    failed: list[tuple[int, str]] = field(default_factory=list)


class BankService(ServiceBase):
    def __init__(self, repos: Repositories, ledger: LedgerService, payments: PaymentService,
                 organization: OrganizationService | None = None,
                 pdf_text: Callable[[Path], str] | None = None) -> None:
        super().__init__(repos)
        self.ledger = ledger
        self.payments = payments
        self.organization = organization or OrganizationService(repos)
        self.matcher = BankMatcher(repos, ledger)
        self.pdf_text = pdf_text

    # -- accounts -------------------------------------------------------------------------------------------
    def accounts(self) -> list[BankAccount]:
        return self.repos.bank.accounts()

    def _validate_account(self, account: BankAccount) -> None:
        account.iban = normalize_iban(account.iban)
        if not valid_iban(account.iban):
            raise ValidationError(f"Die IBAN '{account.iban}' ist ungültig (Prüfsumme).")
        if not account.name.strip():
            raise ValidationError("Bitte einen Namen für das Konto angeben.")
        account.company_id, account.hotel_id = self.organization.resolve(account.company_id, account.hotel_id)

    @atomic
    def add_account(self, account: BankAccount) -> BankAccount:
        self._validate_account(account)
        with self.repos.transaction():
            self.repos.bank.add_account(account)
            self._audit("create", "bank_account", account.id, account.name)
        return account

    @atomic
    def update_account(self, account: BankAccount) -> None:
        self._validate_account(account)
        with self.repos.transaction():
            self.repos.bank.update_account(account)
            self._audit("update", "bank_account", account.id, account.name)

    @atomic
    def delete_account(self, account_id: int) -> None:
        with self.repos.transaction():
            self.repos.bank.delete_account(account_id)
            self._audit("delete", "bank_account", account_id)

    # -- import ---------------------------------------------------------------------------------------------
    @staticmethod
    def fingerprints(account_key: str, txs: list[ParsedTransaction]) -> list[str]:
        """Stable identity of every line; identical lines of one file get a running number (two equal payments a day)."""
        seen: Counter[str] = Counter()
        out: list[str] = []
        for t in txs:
            # the same statement exported as CSV, CAMT or MT940 prints the purpose differently spaced: letters and digits only
            base = "|".join([account_key, t.booking_date.isoformat(), str(t.amount_cents), normalize_iban(t.counterparty_iban),
                             normalize_name(t.counterparty_name), normalize_reference(t.purpose)])
            digest = hashlib.sha1(base.encode("utf-8")).hexdigest()  # noqa: S324 - identity, not security
            out.append(f"{digest}-{seen[digest]}")
            seen[digest] += 1
        return out

    def parse(self, path: Path) -> ParsedStatement:
        return parse_statement_file(path, self.pdf_text)

    def import_file(self, path: Path, account_id: int | None = None) -> BankImportResult:
        """Read a statement file, create the transactions that are new and propose supplier and invoices for each."""
        path = Path(path)
        parsed = self.parse(path)
        if not parsed.transactions:
            raise ValidationError("Der Kontoauszug enthält keine Buchungen.")
        file_hash = hashlib.sha256(path.read_bytes()).hexdigest()
        return self._store(parsed, path.name, file_hash, account_id)

    @atomic
    def _store(self, parsed: ParsedStatement, source_name: str, file_hash: str, account_id: int | None) -> BankImportResult:
        if self.repos.bank.statement_by_hash(file_hash) is not None:
            raise DuplicateError("Dieser Kontoauszug wurde bereits importiert.")
        account, created_account = self._resolve_account(parsed, account_id)
        assert account.id is not None
        key = account.iban
        prints = self.fingerprints(key, parsed.transactions)
        known = self.repos.bank.existing_fingerprints(prints)
        result_warnings = list(parsed.warnings)
        ctx = self.matcher.context()
        with self.repos.transaction():
            statement = self.repos.bank.add_statement(BankStatement(
                source_name=source_name, file_hash=file_hash, format=parsed.format, account_id=account.id,
                date_from=parsed.date_from, date_to=parsed.date_to, opening_cents=parsed.opening_cents,
                closing_cents=parsed.closing_cents))
            assert statement.id is not None
            result = BankImportResult(statement, account, account_created=created_account, warnings=result_warnings)
            for parsed_tx, fingerprint in zip(parsed.transactions, prints, strict=True):
                if fingerprint in known:
                    result.duplicates += 1
                    continue
                tx = BankTransaction(
                    statement_id=statement.id, account_id=account.id, booking_date=parsed_tx.booking_date,
                    value_date=parsed_tx.value_date, amount_cents=parsed_tx.amount_cents, currency=parsed_tx.currency,
                    counterparty_name=parsed_tx.counterparty_name.strip(),
                    counterparty_iban=normalize_iban(parsed_tx.counterparty_iban), purpose=parsed_tx.purpose,
                    booking_text=parsed_tx.booking_text, reference=parsed_tx.reference, fingerprint=fingerprint)
                self._apply_match(tx, self.matcher.match(tx, ctx), ctx)
                self.repos.bank.add_transaction(tx)
                result.created += 1
                result.matched += tx.status == BankTxStatus.MATCHED
            statement.tx_count = result.created
            self.repos.bank.update_statement(statement)
            self._audit("import", "bank_statement", statement.id, f"{source_name}: {result.created} neu, {result.duplicates} schon vorhanden")
        return result

    def _resolve_account(self, parsed: ParsedStatement, account_id: int | None) -> tuple[BankAccount, bool]:
        if account_id is not None:
            account = self.repos.bank.get_account(account_id)
            if account is None:
                raise NotFoundError("Bankkonto nicht gefunden.")
            if parsed.account_iban and parsed.account_iban != account.iban:
                raise ValidationError(
                    f"Der Kontoauszug gehört zum Konto {parsed.account_iban}, nicht zu '{account.name}' ({account.iban}).")
            return account, False
        if parsed.account_iban:
            existing = self.repos.bank.account_by_iban(parsed.account_iban)
            if existing is not None:
                return existing, False
            account = self.repos.bank.add_account(BankAccount(
                name=f"Konto {parsed.account_iban[-4:]}", iban=parsed.account_iban, bic=parsed.bic))
            self._audit("create", "bank_account", account.id, account.name)
            return account, True
        only = self.repos.bank.accounts()
        if len(only) == 1:
            return only[0], False
        raise AccountRequiredError("Aus dem Kontoauszug ist das Bankkonto nicht ersichtlich. Bitte das Konto auswählen.")

    # -- recognition ----------------------------------------------------------------------------------------
    def _apply_match(self, tx: BankTransaction, match: BankMatch, ctx: MatchContext) -> None:
        tx.reasons = list(match.reasons)
        tx.invoice_ids, tx.confidence, tx.supplier_id = [], 0.0, None
        if tx.amount_cents > 0:
            tx.status, tx.note = BankTxStatus.IGNORED, "Eingang"
            return
        if match.own_account is not None:
            tx.status, tx.note = BankTxStatus.IGNORED, f"Umbuchung auf {match.own_account.name}"
            return
        tx.status = BankTxStatus.NEW
        if match.supplier_id is None:
            return
        tx.supplier_id = match.supplier_id
        tx.invoice_ids = list(match.proposal.invoice_ids)
        tx.confidence = match.confidence
        tx.reasons = [*match.reasons, *match.proposal.reasons]
        paid = self.matcher.existing_payment(match.supplier_id, tx.booking_date, abs(tx.amount_cents))
        if paid is not None:
            tx.note = "Zahlung wohl schon gebucht"
            tx.reasons.append("gleiche Zahlung ist bereits gebucht")
            return
        if match.proposal.exact and match.confidence >= MATCHED_CONFIDENCE:
            tx.status = BankTxStatus.MATCHED

    @atomic
    def rematch(self, tx_id: int) -> BankTransaction:
        """Recognise a still open transaction again (master data changed since the import)."""
        tx = self._open_tx(tx_id)
        ctx = self.matcher.context()
        self._apply_match(tx, self.matcher.match(tx, ctx), ctx)
        self.repos.bank.update_transaction(tx)
        return tx

    @atomic
    def rematch_open(self) -> int:
        """Recognise all open transactions again; returns how many are now matched."""
        ctx = self.matcher.context()
        matched = 0
        with self.repos.transaction():
            for tx in self.repos.bank.transactions():
                if tx.status in (BankTxStatus.NEW, BankTxStatus.MATCHED) and tx.amount_cents < 0:
                    self._apply_match(tx, self.matcher.match(tx, ctx), ctx)
                    self.repos.bank.update_transaction(tx)
                    matched += tx.status == BankTxStatus.MATCHED
        return matched

    def propose(self, tx_id: int, supplier_id: int) -> list[int]:
        """Invoice proposal after the user picked another supplier."""
        tx = self.get(tx_id)
        ctx = self.matcher.context()
        text = " ".join(x for x in (tx.purpose, tx.reference) if x)
        return self.matcher.propose_invoices(supplier_id, abs(tx.amount_cents), text, ctx).invoice_ids

    def candidates(self, tx_id: int) -> list[SupplierEvidence]:
        tx = self.get(tx_id)
        return self.matcher.match(tx, self.matcher.context()).candidates

    # -- queries --------------------------------------------------------------------------------------------
    def get(self, tx_id: int) -> BankTransaction:
        tx = self.repos.bank.get_transaction(tx_id)
        if tx is None:
            raise NotFoundError("Buchung nicht gefunden.")
        return tx

    def transactions(self, status: BankTxStatus | None = None, account_id: int | None = None) -> list[BankTransaction]:
        return self.repos.bank.transactions(status=status, account_id=account_id)

    def counts(self) -> dict[str, int]:
        return self.repos.bank.count_by_status()

    def statements(self) -> list[BankStatement]:
        return self.repos.bank.statements()

    def _open_tx(self, tx_id: int) -> BankTransaction:
        tx = self.get(tx_id)
        if tx.status == BankTxStatus.BOOKED:
            raise LedgerError("Diese Buchung ist bereits als Zahlung gebucht. Bitte zuerst die Zahlung stornieren.")
        return tx

    # -- user decisions -------------------------------------------------------------------------------------
    @atomic
    def assign(self, tx_id: int, supplier_id: int | None, invoice_ids: list[int] | None = None, note: str | None = None) -> BankTransaction:
        """The user chose the supplier and invoices (any time before booking); nothing is booked yet."""
        tx = self._open_tx(tx_id)
        if supplier_id is not None:
            party = self.repos.parties.get(supplier_id)
            if party is None or party.role == PartyRole.COLLECTION_AGENCY:
                raise ValidationError("Bitte einen gültigen Lieferanten wählen.")
        tx.supplier_id = supplier_id
        tx.invoice_ids = list(invoice_ids or [])
        if note is not None:
            tx.note = note
        if supplier_id is None:
            tx.status, tx.confidence = BankTxStatus.NEW, 0.0
        else:
            tx.status = BankTxStatus.MATCHED if tx.amount_cents < 0 else BankTxStatus.NEW
            tx.confidence = 1.0 if tx.status == BankTxStatus.MATCHED else 0.0
            tx.reasons = ["vom Benutzer zugeordnet"]
        self.repos.bank.update_transaction(tx)
        return tx

    @atomic
    def ignore(self, tx_id: int, note: str = "") -> BankTransaction:
        tx = self._open_tx(tx_id)
        tx.status, tx.note = BankTxStatus.IGNORED, note or tx.note
        self.repos.bank.update_transaction(tx)
        return tx

    @atomic
    def reopen(self, tx_id: int) -> BankTransaction:
        """Take an ignored transaction back into the list to check."""
        tx = self._open_tx(tx_id)
        ctx = self.matcher.context()
        tx.status = BankTxStatus.NEW
        tx.note = ""
        if tx.amount_cents < 0:
            self._apply_match(tx, self.matcher.match(tx, ctx), ctx)
            if tx.status == BankTxStatus.IGNORED:  # own account transfer stays what it is unless the user decides otherwise
                tx.status = BankTxStatus.NEW
        self.repos.bank.update_transaction(tx)
        return tx

    # -- booking --------------------------------------------------------------------------------------------
    def duplicate_payment(self, tx_id: int) -> Payment | None:
        tx = self.get(tx_id)
        if tx.supplier_id is None:
            return None
        return self.matcher.existing_payment(tx.supplier_id, tx.booking_date, abs(tx.amount_cents))

    @atomic
    def book(self, tx_id: int, *, learn: bool = True, force: bool = False) -> Payment:
        """Book the transaction as a payment to its supplier, distributed over the chosen invoices."""
        tx = self._open_tx(tx_id)
        if tx.amount_cents >= 0:
            raise ValidationError("Eingänge können nicht als Zahlung an einen Lieferanten gebucht werden.")
        if tx.supplier_id is None:
            raise ValidationError("Bitte zuerst den Lieferanten wählen.")
        if not force and self.duplicate_payment(tx_id) is not None:
            raise DuplicateError("Zu dieser Buchung gibt es bereits eine gleiche Zahlung. Bitte prüfen, ob sie schon gebucht ist.")
        account = self.repos.bank.get_account(tx.account_id) if tx.account_id else None
        scope = (account.company_id, account.hotel_id) if account else (None, None)
        with self.repos.transaction():
            payment = self.payments.record_payment(
                tx.supplier_id, tx.booking_date, abs(tx.amount_cents), tx.invoice_ids, method=PaymentMethod.BANK_TRANSFER,
                bank_reference=tx.reference if tx.reference and tx.reference != "NOTPROVIDED" else "",
                iban=tx.counterparty_iban, notes=self._payment_note(tx),
                company_id=scope[0] if not tx.invoice_ids else None, hotel_id=scope[1] if not tx.invoice_ids else None)
            tx.status, tx.payment_id = BankTxStatus.BOOKED, payment.id
            self.repos.bank.update_transaction(tx)
            if learn:
                self._learn(tx)
            self._audit("book", "bank_transaction", tx.id, f"{format_cents(abs(tx.amount_cents))} {tx.counterparty_name}".strip())
        return payment

    @staticmethod
    def _payment_note(tx: BankTransaction) -> str:
        return " – ".join(x for x in (tx.counterparty_name, tx.purpose) if x)[:300]

    def _learn(self, tx: BankTransaction) -> None:
        """Remember IBAN and printed name of the payee so that the next statement is recognised without help."""
        if tx.supplier_id is None:
            return
        party = self.repos.parties.get(tx.supplier_id)
        if party is None:
            return
        changed = False
        iban = normalize_iban(tx.counterparty_iban)
        if iban and valid_iban(iban) and iban not in party.ibans and not any(
                iban in other.ibans for other in self.repos.parties.list() if other.id != party.id):
            party.ibans.append(iban)
            changed = True
        name = tx.counterparty_name.strip()
        if name and similarity(name, party.name) < 0.9 and all(similarity(name, a) < 0.9 for a in party.aliases) \
                and not any(similarity(name, other.name) >= 0.9 for other in self.repos.parties.list() if other.id != party.id):
            party.aliases.append(name)
            changed = True
        if changed:
            self.repos.parties.update(party)

    @atomic
    def book_sure(self, min_confidence: float = SURE_CONFIDENCE) -> BookReport:
        """Book every matched transaction whose proposal is certain; the others stay for the user."""
        report = BookReport()
        for tx in self.repos.bank.transactions(status=BankTxStatus.MATCHED):
            if tx.confidence < min_confidence or tx.id is None:
                continue
            try:
                with self.repos.transaction():
                    self.book(tx.id)
                report.booked.append(tx.id)
            except (ValidationError, DuplicateError, LedgerError) as exc:
                report.failed.append((tx.id, exc.message))
        return report

    def overview(self, tx: BankTransaction) -> dict[str, str]:
        """Names for display."""
        supplier = self.repos.parties.get(tx.supplier_id) if tx.supplier_id else None
        account = self.repos.bank.get_account(tx.account_id) if tx.account_id else None
        return {"supplier": supplier.name if supplier else "", "account": account.name if account else ""}


