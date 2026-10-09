"""Dunning notices: which ledger entries a notice creates, and reconciliation against the ledger."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date

from supplier_app.models.enums import LedgerEntryType as T
from supplier_app.util.dates import format_date
from supplier_app.util.money import format_cents

from .ledger_types import LedgerLine


@dataclass(frozen=True)
class NoticeClaim:
    """What a notice claims for ONE invoice (cumulative, as printed by the sender)."""

    invoice_id: int
    principal_cents: int = 0
    fees_cents: int = 0
    interest_cents: int = 0
    flat_fee_cents: int = 0
    other_costs_cents: int = 0
    total_cents: int = 0  # 0 = not stated

    @property
    def computed_total(self) -> int:
        return (
            self.principal_cents + self.fees_cents + self.interest_cents + self.flat_fee_cents + self.other_costs_cents
        )

    @property
    def claimed_total(self) -> int:
        return self.total_cents if self.total_cents > 0 else self.computed_total


@dataclass(frozen=True)
class PlannedCharge:
    entry_type: T
    amount_cents: int


@dataclass(frozen=True)
class NoticePostingPlan:
    charges: list[PlannedCharge]
    lower_than_booked: dict[T, int]


_CLAIM_FIELDS: tuple[tuple[str, T], ...] = (
    ("fees_cents", T.DUNNING_FEE),
    ("interest_cents", T.LATE_INTEREST),
    ("flat_fee_cents", T.LATE_PAYMENT_FLAT_FEE),
    ("other_costs_cents", T.COLLECTION_COST),
)


def plan_notice_postings(claim: NoticeClaim, booked: Mapping[T, int]) -> NoticePostingPlan:
    """Only additional charges become ledger entries.

    ``booked`` is the net amount already in the ledger per charge category for this invoice. A claim
    is cumulative, so restated charges produce nothing; only the delta is posted. The principal is
    never posted (a Mahnung is not a new debt).
    """
    charges: list[PlannedCharge] = []
    lower: dict[T, int] = {}
    for attr, entry_type in _CLAIM_FIELDS:
        claimed = getattr(claim, attr)
        already = booked.get(entry_type, 0)
        if claimed > already:
            charges.append(PlannedCharge(entry_type, claimed - already))
        elif claimed < already and claimed > 0:
            lower[entry_type] = already - claimed
    return NoticePostingPlan(charges, lower)


@dataclass(frozen=True)
class Issue:
    code: str  # DIFF | PAYMENT_IGNORED | SUM_MISMATCH
    message: str
    invoice_id: int | None = None


@dataclass(frozen=True)
class InvoiceReconciliation:
    invoice_id: int
    claimed_cents: int
    expected_cents: int

    @property
    def difference_cents(self) -> int:
        return self.claimed_cents - self.expected_cents


@dataclass(frozen=True)
class NoticeReconciliation:
    claimed_total_cents: int
    expected_total_cents: int
    per_invoice: list[InvoiceReconciliation]
    issues: list[Issue] = field(default_factory=list)

    @property
    def difference_cents(self) -> int:
        return self.claimed_total_cents - self.expected_total_cents

    @property
    def ok(self) -> bool:
        return not self.issues


def _expected_at(lines: Sequence[LedgerLine], day: date) -> int:
    return sum(x.amount_cents for x in lines if x.entry_date <= day)


def reconcile_notice(
    notice_date: date,
    claims: Sequence[NoticeClaim],
    lines_by_invoice: Mapping[int, Sequence[LedgerLine]],
    credited_cents: int = 0,
) -> NoticeReconciliation:
    """Compare what the sender claims with what the ledger expects at the notice date."""
    issues: list[Issue] = []
    per_invoice: list[InvoiceReconciliation] = []
    for claim in claims:
        lines = lines_by_invoice.get(claim.invoice_id, [])
        rec = InvoiceReconciliation(claim.invoice_id, claim.claimed_total, _expected_at(lines, notice_date))
        per_invoice.append(rec)
        if claim.total_cents > 0 and claim.total_cents != claim.computed_total:
            issues.append(Issue(
                "SUM_MISMATCH",
                f"Summe der Einzelposten ({format_cents(claim.computed_total)}) weicht vom genannten "
                f"Gesamtbetrag ({format_cents(claim.total_cents)}) ab.",
                claim.invoice_id,
            ))
        diff = rec.difference_cents
        if diff > 0:
            issues.append(Issue(
                "DIFF",
                f"Mahnung fordert {format_cents(rec.claimed_cents)}, Konto zeigt {format_cents(rec.expected_cents)}, "
                f"Differenz {format_cents(diff)}: Gebühr doppelt? Zahlung nicht berücksichtigt?",
                claim.invoice_id,
            ))
            payments = [
                x for x in lines
                if x.category == T.PAYMENT and x.entry_type == T.PAYMENT and x.entry_date < notice_date
                and x.invoice_id is not None
            ]
            reversed_ids = {x.reverses_id for x in lines if x.reverses_id is not None and x.entry_date <= notice_date}
            payments = [p for p in payments if p.entry_id not in reversed_ids]
            paid_before = -sum(p.amount_cents for p in payments)
            if paid_before > 0 and credited_cents < paid_before:
                parts = ", ".join(f"{format_date(p.entry_date)} über {format_cents(-p.amount_cents)}" for p in payments)
                issues.append(Issue(
                    "PAYMENT_IGNORED",
                    f"Zahlung vom {parts} wird im Schreiben nicht (vollständig) berücksichtigt "
                    f"(Gutschrift laut Schreiben: {format_cents(credited_cents)}).",
                    claim.invoice_id,
                ))
        elif diff < 0:
            issues.append(Issue(
                "DIFF",
                f"Mahnung fordert weniger als das Konto zeigt: {format_cents(rec.claimed_cents)} statt "
                f"{format_cents(rec.expected_cents)}, Differenz {format_cents(-diff)}. "
                "Gebühren/Zinsen nicht gebucht oder Zahlung berücksichtigt?",
                claim.invoice_id,
            ))
    return NoticeReconciliation(
        claimed_total_cents=sum(r.claimed_cents for r in per_invoice),
        expected_total_cents=sum(r.expected_cents for r in per_invoice),
        per_invoice=per_invoice,
        issues=issues,
    )
