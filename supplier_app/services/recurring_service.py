"""Recurring invoices (rent, leasing, service contracts): templates that book their invoices when they fall due."""

from __future__ import annotations

import calendar
import re
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation

from supplier_app.errors import NotFoundError, ValidationError
from supplier_app.i18n import tr
from supplier_app.models.entities import Invoice, RecurringAmount, RecurringInvoice
from supplier_app.models.enums import PartyRole, RecurrencePeriod
from supplier_app.repositories.interfaces import Repositories
from supplier_app.services.base import ServiceBase, atomic, today
from supplier_app.services.invoice_service import InvoiceService
from supplier_app.services.organization_service import OrganizationService
from supplier_app.util.money import format_cents

MAX_PER_RUN = 60  # occurrences generated per template and run (a long-unused installation catches up in one go)
DEFAULT_PATTERNS = {
    RecurrencePeriod.MONTHLY: "{prefix}-{year}-{month}",
    RecurrencePeriod.QUARTERLY: "{prefix}-{year}-Q{quarter}",
    RecurrencePeriod.HALF_YEARLY: "{prefix}-{year}-H{half}",
    RecurrencePeriod.YEARLY: "{prefix}-{year}",
}
_TOKENS = ("prefix", "year", "month", "quarter", "half")


@dataclass
class GenerationReport:
    created: list[tuple[RecurringInvoice, Invoice]] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)  # human readable reasons (no amount, already booked ...)


def add_months(start: date, months: int, day: int) -> date:
    """The date ``months`` after ``start``'s month, on day ``day`` (31 or a day beyond the month end = last day)."""
    index = start.year * 12 + (start.month - 1) + months
    year, month = divmod(index, 12)
    return date(year, month + 1, min(day, calendar.monthrange(year, month + 1)[1]))


def _prefix(title: str) -> str:
    word = re.sub(r"[^A-Za-z0-9ÄÖÜäöüß]", "", (title.split() or ["R"])[0])
    return (word or "R")[:12].upper()


class RecurringService(ServiceBase):
    def __init__(self, repos: Repositories, invoices: InvoiceService, organization: OrganizationService | None = None) -> None:
        super().__init__(repos)
        self.invoices = invoices
        self.organization = organization or OrganizationService(repos)

    # -- schedule ------------------------------------------------------------------------------------------
    @staticmethod
    def occurrences(rec: RecurringInvoice, until: date, limit: int | None = None) -> list[date]:
        """Due dates from the start up to ``until`` (and the end date), at most ``limit``."""
        out: list[date] = []
        k = 0
        while True:
            day = add_months(rec.start_date, k * rec.period.months, rec.day_of_month)
            k += 1
            if day > until or (rec.end_date and day > rec.end_date):
                break
            if day < rec.start_date:
                continue
            out.append(day)
            if limit and len(out) >= limit:
                break
            if k > 1200:  # 100 years of months: a safety net against endless loops
                break
        return out

    @staticmethod
    def amount_on(rec: RecurringInvoice, day: date) -> int | None:
        valid = [a for a in rec.amounts if a.valid_from <= day]
        return max(valid, key=lambda a: a.valid_from).gross_cents if valid else None

    @staticmethod
    def number_for(rec: RecurringInvoice, occurrence: date) -> str:
        pattern = rec.number_pattern.strip() or DEFAULT_PATTERNS[rec.period]
        values = {"prefix": _prefix(rec.title), "year": f"{occurrence.year}", "month": f"{occurrence.month:02d}",
                  "quarter": str((occurrence.month - 1) // 3 + 1), "half": str((occurrence.month - 1) // 6 + 1)}
        return re.sub(r"\{(\w+)\}", lambda m: values.get(m.group(1), m.group(0)), pattern)

    def upcoming(self, rec: RecurringInvoice, count: int = 6) -> list[tuple[date, str, int | None]]:
        """The next due dates with number and amount (for the preview in the dialog)."""
        start = max(today(), rec.start_date)
        out: list[tuple[date, str, int | None]] = []
        horizon = add_months(start, rec.period.months * (count + 1), 31)
        for day in self.occurrences(rec, horizon):
            if day >= start:
                out.append((day, self.number_for(rec, day), self.amount_on(rec, day)))
            if len(out) >= count:
                break
        return out

    # -- master data ---------------------------------------------------------------------------------------
    def get(self, rec_id: int) -> RecurringInvoice:
        rec = self.repos.recurring.get(rec_id)
        if rec is None:
            raise NotFoundError("Wiederkehrende Rechnung nicht gefunden.")
        return rec

    def list(self, supplier_id: int | None = None, active_only: bool = False) -> list[RecurringInvoice]:
        return self.repos.recurring.list(supplier_id=supplier_id, active_only=active_only)

    def _validate(self, rec: RecurringInvoice) -> None:
        supplier = self.repos.parties.get(rec.supplier_id)
        if supplier is None or supplier.role == PartyRole.COLLECTION_AGENCY:
            raise ValidationError("Bitte einen gültigen Lieferanten wählen.")
        if not rec.title.strip():
            raise ValidationError("Bitte eine Bezeichnung angeben (z. B. Miete Hotel Alpenblick).")
        if not 1 <= rec.day_of_month <= 31:
            raise ValidationError("Der Tag im Monat muss zwischen 1 und 31 liegen.")
        if rec.end_date and rec.end_date < rec.start_date:
            raise ValidationError("Das Ende liegt vor dem Beginn.")
        if rec.due_days < 0:
            raise ValidationError("Das Zahlungsziel darf nicht negativ sein.")
        try:
            if not Decimal(0) <= Decimal(rec.vat_rate) <= Decimal(100):
                raise ValidationError("Der MwSt-Satz muss zwischen 0 und 100 liegen.")
        except InvalidOperation as exc:
            raise ValidationError("Der MwSt-Satz muss zwischen 0 und 100 liegen.") from exc
        if not rec.amounts or any(a.gross_cents <= 0 for a in rec.amounts):
            raise ValidationError("Bitte mindestens einen Betrag größer als 0 angeben.")
        if len({a.valid_from for a in rec.amounts}) != len(rec.amounts):
            raise ValidationError("Zwei Beträge gelten ab dem gleichen Datum.")
        if self.amount_on(rec, rec.start_date) is None:
            raise ValidationError("Der erste Betrag muss ab dem Beginn der Rechnung gelten.")
        unknown = [t for t in re.findall(r"\{(\w+)\}", rec.number_pattern) if t not in _TOKENS]
        if unknown:
            raise ValidationError(f"Unbekannter Platzhalter in der Rechnungsnummer: {{{unknown[0]}}}")
        first = self.occurrences(rec, add_months(rec.start_date, rec.period.months * 2, 31), 3)
        if len({self.number_for(rec, d) for d in first}) < len(first):
            raise ValidationError("Die Rechnungsnummer muss sich mit jedem Zeitraum ändern (z. B. {year}-{month}).")

    @atomic
    def create(self, rec: RecurringInvoice) -> RecurringInvoice:
        rec.amounts = sorted(rec.amounts, key=lambda a: a.valid_from)
        rec.company_id, rec.hotel_id = self.organization.resolve(rec.company_id, rec.hotel_id)
        self._validate(rec)
        with self.repos.transaction():
            self.repos.recurring.add(rec)
            self._audit("create", "recurring", rec.id, rec.title)
        return rec

    @atomic
    def update(self, rec: RecurringInvoice) -> RecurringInvoice:
        self.get(rec.id or 0)
        rec.amounts = sorted(rec.amounts, key=lambda a: a.valid_from)
        rec.company_id, rec.hotel_id = self.organization.resolve(rec.company_id, rec.hotel_id)
        self._validate(rec)
        with self.repos.transaction():
            self.repos.recurring.update(rec)
            self._audit("update", "recurring", rec.id, rec.title)
        return rec

    @atomic
    def set_amount(self, rec_id: int, valid_from: date, gross_cents: int) -> RecurringInvoice:
        """A new amount from ``valid_from`` on (rent increase); an existing row with that date is replaced."""
        rec = self.get(rec_id)
        rec.amounts = [a for a in rec.amounts if a.valid_from != valid_from] + [RecurringAmount(valid_from, gross_cents)]
        return self.update(rec)

    @atomic
    def set_active(self, rec_id: int, active: bool) -> None:
        rec = self.get(rec_id)
        rec.active = active
        with self.repos.transaction():
            self.repos.recurring.update(rec)
            self._audit("activate" if active else "deactivate", "recurring", rec_id, rec.title)

    @atomic
    def delete(self, rec_id: int) -> None:
        """Remove the template; invoices it already generated stay."""
        rec = self.get(rec_id)
        with self.repos.transaction():
            self.repos.recurring.delete(rec_id)
            self._audit("delete", "recurring", rec_id, rec.title)

    def runs(self, rec_id: int) -> dict[date, int]:
        return self.repos.recurring.runs(rec_id)

    # -- generation ----------------------------------------------------------------------------------------
    @atomic
    def generate_due(self, until: date | None = None, rec_id: int | None = None) -> GenerationReport:
        """Book every invoice that fell due until today and does not exist yet (safe to call as often as you like)."""
        until = until or today()
        report = GenerationReport()
        recs = [self.get(rec_id)] if rec_id else self.repos.recurring.list(active_only=True)
        for rec in recs:
            if not rec.active and rec_id is None:
                continue
            done = self.repos.recurring.runs(rec.id or 0)
            for occurrence in self.occurrences(rec, until):
                if occurrence in done:
                    continue
                number = self.number_for(rec, occurrence)
                gross = self.amount_on(rec, occurrence)
                if gross is None:
                    report.skipped.append(tr("recurring.skip.no_amount", title=rec.title, date=occurrence.strftime("%d.%m.%Y")))
                    continue
                existing = self.repos.invoices.get_by_number(rec.supplier_id, number)
                if existing is not None and existing.id is not None:  # entered by hand or delivered by the supplier
                    self.repos.recurring.log_run(rec.id or 0, occurrence, existing.id)
                    report.skipped.append(tr("recurring.skip.exists", title=rec.title, number=number))
                    continue
                invoice = self.invoices.create_invoice(
                    rec.supplier_id, number, occurrence, gross_cents=gross, vat_rate=rec.vat_rate,
                    due_date=occurrence + timedelta(days=rec.due_days), category_id=rec.category_id,
                    notes=(rec.notes + "\n" if rec.notes else "") + tr("recurring.note", title=rec.title),
                    company_id=rec.company_id, hotel_id=rec.hotel_id)
                assert invoice.id is not None
                self.repos.recurring.log_run(rec.id or 0, occurrence, invoice.id)
                self._audit("generate", "recurring", rec.id, f"{number} {format_cents(gross)}")
                report.created.append((rec, invoice))
                if len(report.created) >= MAX_PER_RUN * max(1, len(recs)):
                    break
        return report
