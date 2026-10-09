"""Dunning notices: booking, de-duplication, reconciliation and claimed-vs-calculated comparison."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import date

from supplier_app.errors import DuplicateError, NotFoundError, ValidationError
from supplier_app.i18n import level_label
from supplier_app.models.entities import DocumentReference, DunningNotice, LedgerEntry, NoticeInvoiceClaim
from supplier_app.models.enums import DunningLevel, EntityKind, PartyRole, ReferenceType
from supplier_app.repositories.interfaces import Repositories
from supplier_app.services.base import ServiceBase
from supplier_app.services.case_service import CaseService
from supplier_app.services.ledger import NoticeClaim, NoticeReconciliation, plan_notice_postings
from supplier_app.services.ledger_service import LedgerService
from supplier_app.services.settings_service import SettingsService
from supplier_app.util.dates import format_date
from supplier_app.util.money import format_cents
from supplier_app.util.normalize import normalize_reference


@dataclass
class NoticeDraft:
    """Confirmed data of a notice (what the user accepted in the review form)."""

    sender_party_id: int
    notice_date: date
    level: DunningLevel
    claims: list[NoticeClaim]
    supplier_id: int | None = None
    new_deadline: date | None = None
    total_claimed_cents: int = 0  # 0 = sum of the claims
    credited_cents: int = 0
    document_id: int | None = None
    references: list[tuple[ReferenceType, str]] = field(default_factory=list)
    notes: str = ""


@dataclass
class BookedNotice:
    notice: DunningNotice
    entries: list[LedgerEntry]
    reconciliation: NoticeReconciliation
    warnings: list[str]


@dataclass(frozen=True)
class ComparisonRow:
    invoice_id: int
    label: str
    claimed_cents: int
    calculated_cents: int

    @property
    def difference_cents(self) -> int:
        return self.claimed_cents - self.calculated_cents


class DunningService(ServiceBase):
    def __init__(
        self, repos: Repositories, ledger: LedgerService, cases: CaseService, settings: SettingsService
    ) -> None:
        super().__init__(repos)
        self.ledger = ledger
        self.cases = cases
        self.settings = settings

    # -- helpers -----------------------------------------------------------------
    def resolve_supplier(self, sender_party_id: int, supplier_id: int | None = None) -> int:
        """Supplier whose ledger a letter of ``sender`` belongs to."""
        if supplier_id is not None:
            return supplier_id
        sender = self.repos.parties.get(sender_party_id)
        if sender is None:
            raise NotFoundError("Absender nicht gefunden.")
        if sender.role == PartyRole.COLLECTION_AGENCY:
            if sender.represents_supplier_id is None:
                raise ValidationError(
                    f"Das Inkassobüro '{sender.name}' ist keinem Lieferanten zugeordnet. "
                    "Bitte im Stammdatensatz 'vertritt Lieferant' setzen."
                )
            return sender.represents_supplier_id
        assert sender.id is not None
        return sender.id

    @staticmethod
    def dedup_key(supplier_id: int, draft: NoticeDraft) -> str:
        parts = [str(supplier_id), str(draft.sender_party_id), draft.notice_date.isoformat(), str(int(draft.level)),
                 str(draft.total_claimed_cents)]
        for c in sorted(draft.claims, key=lambda x: x.invoice_id):
            parts.append(f"{c.invoice_id}:{c.principal_cents}:{c.fees_cents}:{c.interest_cents}:{c.flat_fee_cents}:"
                         f"{c.other_costs_cents}:{c.total_cents}")
        return hashlib.sha256("|".join(parts).encode()).hexdigest()

    def is_duplicate(self, draft: NoticeDraft) -> DunningNotice | None:
        supplier_id = self.resolve_supplier(draft.sender_party_id, draft.supplier_id)
        return self.repos.notices.find_by_dedup_key(self.dedup_key(supplier_id, draft))

    # -- booking -----------------------------------------------------------------
    def book_notice(self, draft: NoticeDraft) -> BookedNotice:
        """Store the notice, post only the additional charges, open the case, remember references."""
        if not draft.claims:
            raise ValidationError("Das Schreiben verweist auf keine Rechnung.")
        supplier_id = self.resolve_supplier(draft.sender_party_id, draft.supplier_id)
        seen: set[int] = set()
        for claim in draft.claims:
            if claim.invoice_id in seen:
                raise ValidationError("Eine Rechnung kommt im Schreiben mehrfach vor.")
            seen.add(claim.invoice_id)
            invoice = self.repos.invoices.get(claim.invoice_id)
            if invoice is None or invoice.supplier_id != supplier_id:
                raise ValidationError("Die Rechnung gehört nicht zum Lieferanten des Schreibens.")
        key = self.dedup_key(supplier_id, draft)
        if self.repos.notices.find_by_dedup_key(key) is not None:
            raise DuplicateError("Dieses Schreiben wurde bereits erfasst (gleicher Absender, Datum, Stufe und Beträge).")

        total = draft.total_claimed_cents or sum(c.claimed_total for c in draft.claims)
        notice = DunningNotice(
            sender_party_id=draft.sender_party_id, supplier_id=supplier_id, notice_date=draft.notice_date,
            level=draft.level, new_deadline=draft.new_deadline,
            principal_cents=sum(c.principal_cents for c in draft.claims),
            fees_cents=sum(c.fees_cents for c in draft.claims),
            interest_cents=sum(c.interest_cents for c in draft.claims),
            flat_fee_cents=sum(c.flat_fee_cents for c in draft.claims),
            other_costs_cents=sum(c.other_costs_cents for c in draft.claims),
            total_claimed_cents=total, credited_cents=draft.credited_cents, document_id=draft.document_id,
            notes=draft.notes,
            claims=[NoticeInvoiceClaim(
                invoice_id=c.invoice_id, principal_cents=c.principal_cents, fees_cents=c.fees_cents,
                interest_cents=c.interest_cents, flat_fee_cents=c.flat_fee_cents,
                other_costs_cents=c.other_costs_cents, total_cents=c.claimed_total) for c in draft.claims])
        entries: list[LedgerEntry] = []
        warnings: list[str] = []
        label = level_label(int(draft.level))
        with self.repos.transaction():
            self.repos.notices.add(notice, key)
            assert notice.id is not None
            first_case_id: int | None = None
            for claim in draft.claims:
                invoice = self.repos.invoices.get(claim.invoice_id)
                assert invoice is not None
                case = self.cases.ensure_for_invoice(claim.invoice_id, on=draft.notice_date)
                first_case_id = first_case_id or case.id
                plan = plan_notice_postings(claim, self.ledger.booked_charges(claim.invoice_id))
                for charge in plan.charges:
                    entries.append(self.ledger.post(
                        entry_date=draft.notice_date, supplier_id=supplier_id, entry_type=charge.entry_type,
                        amount_cents=charge.amount_cents, invoice_id=claim.invoice_id, notice_id=notice.id,
                        document_id=draft.document_id, comment=f"{label} vom {format_date(draft.notice_date)}"))
                for etype, diff in plan.lower_than_booked.items():
                    warnings.append(
                        f"{label}: Rechnung {invoice.invoice_number} – {etype.value} im Schreiben um "
                        f"{format_cents(diff)} niedriger als bereits gebucht (keine Buchung erzeugt)."
                    )
                assert case.id is not None
                self.cases.add_event(
                    case.id, "notice",
                    f"{label} von {self._name(draft.sender_party_id)} vom {format_date(draft.notice_date)}: "
                    f"fordert {format_cents(claim.claimed_total)}", draft.notice_date)
                self._remember_references(draft, claim.invoice_id, case.id)
                self.ledger.refresh_status(claim.invoice_id)
                self.cases.sync_with_invoice(claim.invoice_id)
            self.repos.notices.set_case(notice.id, first_case_id)
            notice.case_id = first_case_id
            self._audit("create", "notice", notice.id, f"{label} {format_cents(total)}")
        recon = self.ledger.reconcile_notice(notice.id)
        return BookedNotice(notice, entries, recon, warnings)

    def _name(self, party_id: int) -> str:
        party = self.repos.parties.get(party_id)
        return party.name if party else "?"

    def _remember_references(self, draft: NoticeDraft, invoice_id: int, case_id: int) -> None:
        """Store all references on document, invoice and case so a new agency reference is found later."""
        for ref_type, raw in draft.references:
            norm = normalize_reference(raw)
            if not norm:
                continue
            owners = [(EntityKind.INVOICE, invoice_id), (EntityKind.CASE, case_id)]
            if draft.document_id:
                owners.append((EntityKind.DOCUMENT, draft.document_id))
            for kind, owner_id in owners:
                self.repos.references.add(DocumentReference(kind.value, owner_id, ref_type, raw.strip(), norm))

    # -- queries -------------------------------------------------------------------
    def get(self, notice_id: int) -> DunningNotice:
        notice = self.repos.notices.get(notice_id)
        if notice is None:
            raise NotFoundError("Schreiben nicht gefunden.")
        return notice

    def list(self, supplier_id: int | None = None, invoice_id: int | None = None) -> list[DunningNotice]:
        return self.repos.notices.list(supplier_id=supplier_id, invoice_id=invoice_id)

    def reconcile(self, notice_id: int) -> NoticeReconciliation:
        return self.ledger.reconcile_notice(notice_id)

    def compare_with_calculation(self, notice_id: int) -> list[ComparisonRow]:
        """'Claimed by sender' vs 'calculated by app' for interest and flat fee."""
        notice = self.get(notice_id)
        rows: list[ComparisonRow] = []
        for claim in notice.claims:
            result = self.ledger.calculate_interest(claim.invoice_id, notice.notice_date)
            if claim.interest_cents > 0 or (result and result.total_cents > 0):
                rows.append(ComparisonRow(claim.invoice_id, "Verzugszinsen", claim.interest_cents,
                                          result.total_cents if result else 0))
            if claim.flat_fee_cents > 0:
                rows.append(ComparisonRow(claim.invoice_id, "Verzugspauschale", claim.flat_fee_cents,
                                          self.settings.flat_fee_cents))
        return rows

    def escalated_invoice_ids(self) -> set[int]:
        """Invoices with a collection letter or court order."""
        ids: set[int] = set()
        for notice in self.repos.notices.list():
            if notice.level >= DunningLevel.COLLECTION:
                ids.update(c.invoice_id for c in notice.claims)
        return ids

    def latest_level(self, invoice_id: int) -> DunningLevel | None:
        notices = self.repos.notices.list(invoice_id=invoice_id)
        return max((n.level for n in notices), default=None)

