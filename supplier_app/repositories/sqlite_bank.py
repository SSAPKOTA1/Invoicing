"""SQLite implementation of :class:`BankRepository`."""

from __future__ import annotations

import json
import sqlite3

from supplier_app.database.errors import INTEGRITY_ERRORS
from supplier_app.errors import DuplicateError
from supplier_app.models.entities import BankAccount, BankStatement, BankTransaction
from supplier_app.models.enums import BankTxStatus
from supplier_app.repositories.interfaces import BankRepository
from supplier_app.repositories.sqlite_base import SqliteRepo, d2s, must_date, s2d, stamp
from supplier_app.util.normalize import normalize_iban


def _account(row: sqlite3.Row) -> BankAccount:
    return BankAccount(id=row["id"], name=row["name"], iban=row["iban"], bic=row["bic"], company_id=row["company_id"],
                       hotel_id=row["hotel_id"], notes=row["notes"], created_at=row["created_at"])


def _statement(row: sqlite3.Row) -> BankStatement:
    return BankStatement(
        id=row["id"], account_id=row["account_id"], source_name=row["source_name"], file_hash=row["file_hash"],
        format=row["format"], date_from=s2d(row["date_from"]), date_to=s2d(row["date_to"]),
        opening_cents=row["opening_cents"], closing_cents=row["closing_cents"], tx_count=row["tx_count"],
        imported_at=row["imported_at"])


def _tx(row: sqlite3.Row) -> BankTransaction:
    return BankTransaction(
        id=row["id"], statement_id=row["statement_id"], account_id=row["account_id"],
        booking_date=must_date(row["booking_date"]), value_date=s2d(row["value_date"]), amount_cents=row["amount_cents"],
        currency=row["currency"], counterparty_name=row["counterparty_name"], counterparty_iban=row["counterparty_iban"],
        purpose=row["purpose"], booking_text=row["booking_text"], reference=row["reference"],
        fingerprint=row["fingerprint"], status=BankTxStatus(row["status"]), supplier_id=row["supplier_id"],
        invoice_ids=[int(x) for x in row["invoice_ids"].split(",") if x], confidence=float(row["confidence"]),
        reasons=json.loads(row["reasons"]) if row["reasons"] else [], payment_id=row["payment_id"], note=row["note"],
        created_at=row["created_at"])


class SqliteBankRepository(SqliteRepo, BankRepository):
    # -- accounts ---------------------------------------------------------------------------------------
    def add_account(self, account: BankAccount) -> BankAccount:
        account.created_at = stamp(account.created_at)
        account.iban = normalize_iban(account.iban)
        try:
            account.id = self.db.insert(
                "INSERT INTO bank_accounts(name, iban, bic, company_id, hotel_id, notes, created_at) VALUES (?,?,?,?,?,?,?)",
                (account.name.strip(), account.iban, account.bic, account.company_id, account.hotel_id, account.notes,
                 account.created_at))
        except INTEGRITY_ERRORS as exc:
            raise DuplicateError("Dieses Bankkonto existiert bereits oder ist ungültig.") from exc
        return account

    def update_account(self, account: BankAccount) -> None:
        try:
            self.db.execute(
                "UPDATE bank_accounts SET name=?, iban=?, bic=?, company_id=?, hotel_id=?, notes=? WHERE id=?",
                (account.name.strip(), normalize_iban(account.iban), account.bic, account.company_id, account.hotel_id,
                 account.notes, account.id))
        except INTEGRITY_ERRORS as exc:
            raise DuplicateError("Dieses Bankkonto existiert bereits oder ist ungültig.") from exc

    def get_account(self, account_id: int) -> BankAccount | None:
        row = self.db.query_one("SELECT * FROM bank_accounts WHERE id=?", (account_id,))
        return _account(row) if row else None

    def account_by_iban(self, iban: str) -> BankAccount | None:
        row = self.db.query_one("SELECT * FROM bank_accounts WHERE iban=?", (normalize_iban(iban),))
        return _account(row) if row else None

    def accounts(self) -> list[BankAccount]:
        return [_account(r) for r in self.db.query_all("SELECT * FROM bank_accounts ORDER BY lower(name), id")]

    def delete_account(self, account_id: int) -> None:
        if self.db.query_one("SELECT 1 FROM bank_statements WHERE account_id=? LIMIT 1", (account_id,)):
            raise DuplicateError("Zu diesem Konto gibt es importierte Kontoauszüge und es kann nicht gelöscht werden.")
        self.db.execute("DELETE FROM bank_accounts WHERE id=?", (account_id,))

    # -- statements -------------------------------------------------------------------------------------
    def add_statement(self, statement: BankStatement) -> BankStatement:
        statement.imported_at = stamp(statement.imported_at)
        try:
            statement.id = self.db.insert(
                "INSERT INTO bank_statements(account_id, source_name, file_hash, format, date_from, date_to, opening_cents,"
                " closing_cents, tx_count, imported_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (statement.account_id, statement.source_name, statement.file_hash, statement.format,
                 d2s(statement.date_from), d2s(statement.date_to), statement.opening_cents, statement.closing_cents,
                 statement.tx_count, statement.imported_at))
        except INTEGRITY_ERRORS as exc:
            raise DuplicateError("Dieser Kontoauszug wurde bereits importiert.") from exc
        return statement

    def update_statement(self, statement: BankStatement) -> None:
        self.db.execute(
            "UPDATE bank_statements SET account_id=?, date_from=?, date_to=?, opening_cents=?, closing_cents=?, tx_count=?"
            " WHERE id=?",
            (statement.account_id, d2s(statement.date_from), d2s(statement.date_to), statement.opening_cents,
             statement.closing_cents, statement.tx_count, statement.id))

    def statement_by_hash(self, file_hash: str) -> BankStatement | None:
        row = self.db.query_one("SELECT * FROM bank_statements WHERE file_hash=?", (file_hash,))
        return _statement(row) if row else None

    def statements(self) -> list[BankStatement]:
        return [_statement(r) for r in self.db.query_all("SELECT * FROM bank_statements ORDER BY imported_at DESC, id DESC")]

    # -- transactions -----------------------------------------------------------------------------------
    @staticmethod
    def _params(tx: BankTransaction) -> tuple:
        return (tx.account_id, d2s(tx.booking_date), d2s(tx.value_date), tx.amount_cents, tx.currency, tx.counterparty_name,
                tx.counterparty_iban, tx.purpose, tx.booking_text, tx.reference, tx.status.value, tx.supplier_id,
                ",".join(str(i) for i in tx.invoice_ids), tx.confidence, json.dumps(tx.reasons, ensure_ascii=False),
                tx.payment_id, tx.note)

    def add_transaction(self, tx: BankTransaction) -> BankTransaction:
        tx.created_at = stamp(tx.created_at)
        try:
            tx.id = self.db.insert(
                "INSERT INTO bank_transactions(statement_id, fingerprint, created_at, account_id, booking_date, value_date,"
                " amount_cents, currency, counterparty_name, counterparty_iban, purpose, booking_text, reference, status,"
                " supplier_id, invoice_ids, confidence, reasons, payment_id, note)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (tx.statement_id, tx.fingerprint, tx.created_at, *self._params(tx)))
        except INTEGRITY_ERRORS as exc:
            raise DuplicateError("Diese Buchung wurde bereits importiert.") from exc
        return tx

    def update_transaction(self, tx: BankTransaction) -> None:
        self.db.execute(
            "UPDATE bank_transactions SET account_id=?, booking_date=?, value_date=?, amount_cents=?, currency=?,"
            " counterparty_name=?, counterparty_iban=?, purpose=?, booking_text=?, reference=?, status=?, supplier_id=?,"
            " invoice_ids=?, confidence=?, reasons=?, payment_id=?, note=? WHERE id=?", (*self._params(tx), tx.id))

    def get_transaction(self, tx_id: int) -> BankTransaction | None:
        row = self.db.query_one("SELECT * FROM bank_transactions WHERE id=?", (tx_id,))
        return _tx(row) if row else None

    def existing_fingerprints(self, fingerprints: list[str]) -> set[str]:
        found: set[str] = set()
        for i in range(0, len(fingerprints), 400):
            chunk = fingerprints[i:i + 400]
            marks = ",".join("?" * len(chunk))
            found.update(r["fingerprint"] for r in self.db.query_all(
                f"SELECT fingerprint FROM bank_transactions WHERE fingerprint IN ({marks})", chunk))
        return found

    def transactions(
        self, *, status: BankTxStatus | None = None, account_id: int | None = None, statement_id: int | None = None,
        supplier_id: int | None = None,
    ) -> list[BankTransaction]:
        sql, params = "SELECT * FROM bank_transactions WHERE 1=1", []
        for column, value in (("status", status.value if status else None), ("account_id", account_id),
                              ("statement_id", statement_id), ("supplier_id", supplier_id)):
            if value is not None:
                sql += f" AND {column}=?"
                params.append(value)
        return [_tx(r) for r in self.db.query_all(sql + " ORDER BY booking_date DESC, id DESC", params)]

    def count_by_status(self) -> dict[str, int]:
        return {r["status"]: r["n"] for r in self.db.query_all(
            "SELECT status, COUNT(*) AS n FROM bank_transactions GROUP BY status")}

    def release_payment(self, payment_id: int) -> None:
        self.db.execute(
            "UPDATE bank_transactions SET status='new', payment_id=NULL, note=? WHERE payment_id=?", ("Zahlung storniert", payment_id))

    def by_payment(self, payment_id: int) -> BankTransaction | None:
        row = self.db.query_one("SELECT * FROM bank_transactions WHERE payment_id=?", (payment_id,))
        return _tx(row) if row else None
