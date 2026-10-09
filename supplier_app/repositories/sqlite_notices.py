"""SQLite implementations of :class:`NoticeRepository` and :class:`PaymentRepository`."""

from __future__ import annotations

import sqlite3
from datetime import date

from supplier_app.errors import DuplicateError
from supplier_app.models.entities import DunningNotice, NoticeInvoiceClaim, Payment, PaymentAllocation
from supplier_app.models.enums import AllocationComponent, DunningLevel, PaymentMethod
from supplier_app.repositories.interfaces import NoticeRepository, PaymentRepository
from supplier_app.repositories.sqlite_base import SqliteRepo, d2s, must_date, s2d, stamp

_N_COLS = (
    "id, sender_party_id, supplier_id, notice_date, level, new_deadline, principal_cents, fees_cents,"
    " interest_cents, flat_fee_cents, other_costs_cents, total_claimed_cents, credited_cents, document_id,"
    " case_id, notes, created_at"
)


class SqliteNoticeRepository(SqliteRepo, NoticeRepository):
    def _hydrate(self, row: sqlite3.Row) -> DunningNotice:
        claims = [
            NoticeInvoiceClaim(
                id=c["id"], notice_id=c["notice_id"], invoice_id=c["invoice_id"],
                principal_cents=c["principal_cents"], fees_cents=c["fees_cents"],
                interest_cents=c["interest_cents"], flat_fee_cents=c["flat_fee_cents"],
                other_costs_cents=c["other_costs_cents"], total_cents=c["total_cents"],
            )
            for c in self.db.query_all("SELECT * FROM notice_invoices WHERE notice_id=? ORDER BY id", (row["id"],))
        ]
        return DunningNotice(
            id=row["id"], sender_party_id=row["sender_party_id"], supplier_id=row["supplier_id"],
            notice_date=must_date(row["notice_date"]), level=DunningLevel(row["level"]),
            new_deadline=s2d(row["new_deadline"]), principal_cents=row["principal_cents"],
            fees_cents=row["fees_cents"], interest_cents=row["interest_cents"], flat_fee_cents=row["flat_fee_cents"],
            other_costs_cents=row["other_costs_cents"], total_claimed_cents=row["total_claimed_cents"],
            credited_cents=row["credited_cents"], document_id=row["document_id"], case_id=row["case_id"],
            notes=row["notes"], claims=claims, created_at=row["created_at"],
        )

    def add(self, notice: DunningNotice, dedup_key: str) -> DunningNotice:
        notice.created_at = stamp(notice.created_at)
        try:
            notice.id = self.db.insert(
                "INSERT INTO dunning_notices(sender_party_id, supplier_id, notice_date, level, new_deadline,"
                " principal_cents, fees_cents, interest_cents, flat_fee_cents, other_costs_cents,"
                " total_claimed_cents, credited_cents, document_id, case_id, notes, dedup_key, created_at)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (notice.sender_party_id, notice.supplier_id, d2s(notice.notice_date), int(notice.level),
                 d2s(notice.new_deadline), notice.principal_cents, notice.fees_cents, notice.interest_cents,
                 notice.flat_fee_cents, notice.other_costs_cents, notice.total_claimed_cents,
                 notice.credited_cents, notice.document_id, notice.case_id, notice.notes, dedup_key,
                 notice.created_at),
            )
            for claim in notice.claims:
                claim.notice_id = notice.id
                claim.id = self.db.insert(
                    "INSERT INTO notice_invoices(notice_id, invoice_id, principal_cents, fees_cents,"
                    " interest_cents, flat_fee_cents, other_costs_cents, total_cents) VALUES (?,?,?,?,?,?,?,?)",
                    (notice.id, claim.invoice_id, claim.principal_cents, claim.fees_cents, claim.interest_cents,
                     claim.flat_fee_cents, claim.other_costs_cents, claim.total_cents),
                )
        except sqlite3.IntegrityError as exc:
            raise DuplicateError("Dieses Schreiben wurde bereits erfasst.") from exc
        return notice

    def get(self, notice_id: int) -> DunningNotice | None:
        row = self.db.query_one(f"SELECT {_N_COLS} FROM dunning_notices WHERE id=?", (notice_id,))
        return self._hydrate(row) if row else None

    def find_by_dedup_key(self, key: str) -> DunningNotice | None:
        row = self.db.query_one(f"SELECT {_N_COLS} FROM dunning_notices WHERE dedup_key=?", (key,))
        return self._hydrate(row) if row else None

    def list(
        self, *, supplier_id: int | None = None, invoice_id: int | None = None, case_id: int | None = None
    ) -> list[DunningNotice]:
        sql, params = f"SELECT {_N_COLS} FROM dunning_notices WHERE 1=1", []
        if supplier_id is not None:
            sql += " AND supplier_id=?"
            params.append(supplier_id)
        if invoice_id is not None:
            sql += " AND id IN (SELECT notice_id FROM notice_invoices WHERE invoice_id=?)"
            params.append(invoice_id)
        if case_id is not None:
            sql += " AND case_id=?"
            params.append(case_id)
        return [self._hydrate(r) for r in self.db.query_all(sql + " ORDER BY notice_date, id", params)]

    def set_case(self, notice_id: int, case_id: int | None) -> None:
        self.db.execute("UPDATE dunning_notices SET case_id=? WHERE id=?", (case_id, notice_id))


class SqlitePaymentRepository(SqliteRepo, PaymentRepository):
    @staticmethod
    def _payment(row: sqlite3.Row) -> Payment:
        return Payment(
            id=row["id"], supplier_id=row["supplier_id"], payment_date=must_date(row["payment_date"]),
            amount_cents=row["amount_cents"], method=PaymentMethod(row["method"]),
            bank_reference=row["bank_reference"], iban=row["iban"], notes=row["notes"],
            document_id=row["document_id"], created_at=row["created_at"],
        )

    def add(self, payment: Payment) -> Payment:
        payment.created_at = stamp(payment.created_at)
        payment.id = self.db.insert(
            "INSERT INTO payments(supplier_id, payment_date, amount_cents, method, bank_reference, iban, notes,"
            " document_id, created_at) VALUES (?,?,?,?,?,?,?,?,?)",
            (payment.supplier_id, d2s(payment.payment_date), payment.amount_cents, payment.method.value,
             payment.bank_reference, payment.iban, payment.notes, payment.document_id, payment.created_at),
        )
        return payment

    def get(self, payment_id: int) -> Payment | None:
        row = self.db.query_one("SELECT * FROM payments WHERE id=?", (payment_id,))
        return self._payment(row) if row else None

    def list(
        self, *, supplier_id: int | None = None, date_from: date | None = None, date_to: date | None = None
    ) -> list[Payment]:
        sql, params = "SELECT * FROM payments WHERE 1=1", []
        if supplier_id is not None:
            sql += " AND supplier_id=?"
            params.append(supplier_id)
        if date_from:
            sql += " AND payment_date>=?"
            params.append(d2s(date_from))
        if date_to:
            sql += " AND payment_date<=?"
            params.append(d2s(date_to))
        return [self._payment(r) for r in self.db.query_all(sql + " ORDER BY payment_date, id", params)]

    def add_allocation(self, alloc: PaymentAllocation) -> PaymentAllocation:
        alloc.id = self.db.insert(
            "INSERT INTO payment_allocations(payment_id, invoice_id, component, amount_cents) VALUES (?,?,?,?)",
            (alloc.payment_id, alloc.invoice_id, alloc.component.value, alloc.amount_cents),
        )
        return alloc

    def allocations(self, *, payment_id: int | None = None, invoice_id: int | None = None) -> list[PaymentAllocation]:
        sql, params = "SELECT * FROM payment_allocations WHERE 1=1", []
        if payment_id is not None:
            sql += " AND payment_id=?"
            params.append(payment_id)
        if invoice_id is not None:
            sql += " AND invoice_id=?"
            params.append(invoice_id)
        return [
            PaymentAllocation(id=r["id"], payment_id=r["payment_id"], invoice_id=r["invoice_id"],
                              component=AllocationComponent(r["component"]), amount_cents=r["amount_cents"])
            for r in self.db.query_all(sql + " ORDER BY id", params)
        ]

    def allocation_sums(self, *, as_of: date | None = None) -> list[tuple[int, str, int]]:
        sql = ("SELECT a.invoice_id, a.component, SUM(a.amount_cents) FROM payment_allocations a"
               " JOIN payments p ON p.id = a.payment_id")
        params: list[object] = []
        if as_of:
            sql += " WHERE p.payment_date <= ?"
            params.append(d2s(as_of))
        sql += " GROUP BY a.invoice_id, a.component"
        return [(r[0], r[1], r[2]) for r in self.db.query_all(sql, params)]
