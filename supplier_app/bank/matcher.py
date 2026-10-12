"""Which supplier and which invoices does a bank transaction pay? Evidence based, like the letter recognition.

Evidence for a supplier (combined as a noisy OR, so several weak hints add up and one strong hint is enough):

* the counterparty IBAN is one of the supplier's IBANs, or an earlier payment went to this IBAN
* the counterparty name resembles the supplier's name or alias
* an open invoice number of the supplier appears in the purpose
* a reference number (customer, file, contract number ...) in the purpose is known for the supplier
* the amount equals an open invoice or the sum of several, or a recurring payment of the supplier
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from itertools import combinations

from supplier_app.ai.names import NameWeights, contains_name, similarity
from supplier_app.ai.references import LabelledReferenceExtractor
from supplier_app.bank.model import ParsedTransaction
from supplier_app.models.entities import BankAccount, BankTransaction, Invoice, Party
from supplier_app.models.enums import InvoiceStatus, PartyRole
from supplier_app.repositories.interfaces import Repositories
from supplier_app.services.ledger_service import LedgerService
from supplier_app.util.money import format_cents
from supplier_app.util.normalize import normalize_iban, normalize_reference

NAME_FLOOR = 0.75  # name similarity below this is no evidence
MAX_SUBSET_INVOICES = 14
MAX_SUBSET_SIZE = 5


@dataclass
class SupplierEvidence:
    supplier_id: int
    reasons: list[tuple[float, str]] = field(default_factory=list)

    def add(self, weight: float, reason: str) -> None:
        if all(reason != r for _w, r in self.reasons):
            self.reasons.append((weight, reason))

    @property
    def score(self) -> float:
        miss = 1.0
        for w, _r in self.reasons:
            miss *= 1.0 - min(0.99, w)
        return 1.0 - miss

    @property
    def texts(self) -> list[str]:
        return [r for _w, r in sorted(self.reasons, key=lambda x: -x[0])]


@dataclass
class InvoiceProposal:
    invoice_ids: list[int] = field(default_factory=list)
    exact: bool = False  # the invoices add up to the amount
    reasons: list[str] = field(default_factory=list)


@dataclass
class BankMatch:
    supplier_id: int | None = None
    candidates: list[SupplierEvidence] = field(default_factory=list)  # best first
    proposal: InvoiceProposal = field(default_factory=InvoiceProposal)
    confidence: float = 0.0
    reasons: list[str] = field(default_factory=list)
    own_account: BankAccount | None = None  # transfer between own accounts


class MatchContext:
    """Master data read once for a whole statement."""

    def __init__(self, repos: Repositories, ledger: LedgerService) -> None:
        self.repos = repos
        self.parties = [p for p in repos.parties.list() if p.id is not None]
        self.suppliers: dict[int, Party] = {p.id: p for p in self.parties if p.role != PartyRole.COLLECTION_AGENCY}  # type: ignore[misc]
        self.agency_of: dict[int, int] = {p.id: p.represents_supplier_id for p in self.parties  # type: ignore[misc]
                                          if p.role == PartyRole.COLLECTION_AGENCY and p.represents_supplier_id}
        self.weights = NameWeights([p.name for p in self.parties])
        self.accounts = repos.bank.accounts()
        self.open: dict[int, list[tuple[Invoice, int]]] = {}
        for state in ledger.invoice_states():
            if state.balance.balance_cents > 0 and state.invoice.status != InvoiceStatus.CANCELLED:
                self.open.setdefault(state.invoice.supplier_id, []).append((state.invoice, state.balance.balance_cents))
        for items in self.open.values():
            items.sort(key=lambda x: (x[0].due_date or x[0].invoice_date, x[0].invoice_date, x[0].id or 0))
        self._name_cache: dict[str, list[tuple[int, Party, float]]] = {}
        self.refs = LabelledReferenceExtractor()
        self.recurring = repos.recurring.list(active_only=True)
        self.payment_ibans: dict[str, int] = {}
        for pay in repos.payments.list():
            if pay.iban:
                self.payment_ibans.setdefault(normalize_iban(pay.iban), pay.supplier_id)

    def name_scores(self, name: str) -> list[tuple[int, Party, float]]:
        """(supplier id, party, similarity) of every party whose name resembles ``name`` (cached per printed name)."""
        cached = self._name_cache.get(name)
        if cached is None:
            cached = []
            for p in self.parties:
                sid = self.supplier_of(p.id or 0)  # type: ignore[arg-type]
                best = max((similarity(name, n, self.weights) for n in [p.name, *p.aliases]), default=0.0)
                if sid is not None and best >= NAME_FLOOR:
                    cached.append((sid, p, best))
            self._name_cache[name] = cached
        return cached

    def supplier_of(self, party_id: int) -> int | None:
        if party_id in self.suppliers:
            return party_id
        return self.agency_of.get(party_id)


class BankMatcher:
    def __init__(self, repos: Repositories, ledger: LedgerService) -> None:
        self.repos = repos
        self.ledger = ledger

    def context(self) -> MatchContext:
        return MatchContext(self.repos, self.ledger)

    # -- supplier -------------------------------------------------------------------------------------------
    def match(self, tx: ParsedTransaction | BankTransaction, ctx: MatchContext) -> BankMatch:
        result = BankMatch()
        iban = normalize_iban(tx.counterparty_iban)
        own = next((a for a in ctx.accounts if iban and a.iban == iban), None)
        if own is not None:
            result.own_account = own
            result.reasons = ["Umbuchung zwischen eigenen Konten"]
            return result
        amount = abs(tx.amount_cents)
        text = " ".join(x for x in (tx.purpose, tx.reference, tx.counterparty_name) if x)
        squashed = normalize_reference(text)
        evidence: dict[int, SupplierEvidence] = {}

        def ev(supplier_id: int) -> SupplierEvidence:
            return evidence.setdefault(supplier_id, SupplierEvidence(supplier_id))

        # IBAN
        if iban:
            for p in ctx.parties:
                if iban in p.ibans and (sid := ctx.supplier_of(p.id or 0)) is not None:  # type: ignore[arg-type]
                    ev(sid).add(0.95, f"IBAN {iban} gehört zum Lieferanten")
            if iban in ctx.payment_ibans:
                ev(ctx.payment_ibans[iban]).add(0.85, "frühere Zahlung an diese IBAN")
        # name
        name = tx.counterparty_name
        if name.strip():
            for sid, p, best in ctx.name_scores(name):
                ev(sid).add(0.55 + 0.35 * (best - NAME_FLOOR) / (1 - NAME_FLOOR),
                            f"Name „{name.strip()}“ ähnlich zu „{p.name}“ ({int(best * 100)} %)")
        elif tx.purpose.strip():
            for p in ctx.parties:
                sid = ctx.supplier_of(p.id or 0)  # type: ignore[arg-type]
                if sid is not None and any(contains_name(tx.purpose, n) for n in [p.name, *p.aliases]):
                    ev(sid).add(0.5, f"Name „{p.name}“ im Verwendungszweck")
        # invoice numbers of open invoices
        mentioned: dict[int, list[Invoice]] = {}
        for sid, items in ctx.open.items():
            for inv, _bal in items:
                norm = normalize_reference(inv.invoice_number)
                if len(norm) >= 4 and norm in squashed:
                    weak = norm.isdigit() and len(norm) < 6
                    ev(sid).add(0.45 if weak else 0.85, f"Rechnungsnummer {inv.invoice_number} im Verwendungszweck")
                    mentioned.setdefault(sid, []).append(inv)
        # references (customer number, file number ...)
        for ref in ctx.refs.extract(tx.purpose or ""):
            norm = normalize_reference(ref.value.value)
            for stored in self.repos.references.find(norm):
                sid = self._owner_supplier(stored.owner_kind, stored.owner_id, ctx)
                if sid is not None:
                    ev(sid).add(0.7, f"Referenz {ref.value.value} ist bekannt")
        # amounts
        for sid, items in ctx.open.items():
            equal = [inv for inv, bal in items if bal == amount]
            if len(equal) == 1:
                ev(sid).add(0.3, f"Betrag {format_cents(amount)} entspricht der offenen Rechnung {equal[0].invoice_number}")
        for rec in ctx.recurring:
            if (when := getattr(tx, "booking_date", None)) is not None:
                due = next((a.gross_cents for a in sorted(rec.amounts, key=lambda a: a.valid_from) if a.valid_from <= when), None)
                if due == amount and rec.supplier_id in ctx.suppliers:
                    ev(rec.supplier_id).add(0.4, f"wiederkehrende Zahlung „{rec.title}“")

        ranked = sorted(evidence.values(), key=lambda e: -e.score)
        result.candidates = ranked
        if not ranked:
            return result
        best = ranked[0]
        confidence = best.score
        if len(ranked) > 1 and ranked[1].score >= 0.8 * best.score:
            confidence *= 0.8  # two suppliers fit almost equally well
            best.add(0.0, "mehrdeutig")
        result.supplier_id = best.supplier_id
        result.reasons = best.texts
        result.proposal = self.propose_invoices(best.supplier_id, amount, text, ctx, mentioned.get(best.supplier_id))
        factor = 1.0 if result.proposal.exact else 0.8 if result.proposal.invoice_ids else 0.6
        result.confidence = round(confidence * factor, 3)
        return result

    def _owner_supplier(self, kind: str, owner_id: int, ctx: MatchContext) -> int | None:
        if kind == "invoice":
            inv = self.repos.invoices.get(owner_id)
            return inv.supplier_id if inv else None
        if kind == "document":
            doc = self.repos.documents.get(owner_id)
            return ctx.supplier_of(doc.supplier_id) if doc and doc.supplier_id else None
        if kind == "case":
            case = self.repos.cases.get(owner_id)
            return case.supplier_id if case else None
        return None

    # -- invoices -------------------------------------------------------------------------------------------
    def propose_invoices(self, supplier_id: int, amount_cents: int, text: str, ctx: MatchContext,
                         mentioned: list[Invoice] | None = None) -> InvoiceProposal:
        """The open invoices of ``supplier_id`` that a payment of this amount most likely settles."""
        items = ctx.open.get(supplier_id, [])
        if not items:
            return InvoiceProposal()
        balance = {inv.id: bal for inv, bal in items}
        if mentioned is None:
            squashed = normalize_reference(text)
            mentioned = [inv for inv, _b in items if len(n := normalize_reference(inv.invoice_number)) >= 4 and n in squashed]
        if mentioned:
            ids = [i.id for i in mentioned if i.id is not None]
            total = sum(balance[i] for i in ids)
            numbers = ", ".join(i.invoice_number for i in mentioned)
            if total == amount_cents:
                return InvoiceProposal(ids, True, [f"Rechnung {numbers} im Verwendungszweck, Betrag stimmt"])
            return InvoiceProposal(ids, False, [f"Rechnung {numbers} im Verwendungszweck, Betrag weicht ab "
                                                f"({format_cents(amount_cents)} statt {format_cents(total)})"])
        equal = [inv for inv, bal in items if bal == amount_cents]
        if equal:
            inv = equal[0]
            return InvoiceProposal([inv.id], True, [f"Betrag entspricht der offenen Rechnung {inv.invoice_number}"])  # type: ignore[list-item]
        subset = self._subset(items, amount_cents)
        if subset:
            return InvoiceProposal([i.id for i in subset], True, [f"Summe von {len(subset)} offenen Rechnungen"])  # type: ignore[misc]
        return InvoiceProposal()

    @staticmethod
    def _subset(items: list[tuple[Invoice, int]], amount: int) -> list[Invoice] | None:
        pool = [(inv, bal) for inv, bal in items if bal <= amount][:MAX_SUBSET_INVOICES]
        for size in range(2, min(MAX_SUBSET_SIZE, len(pool)) + 1):
            for combo in combinations(pool, size):
                if sum(b for _i, b in combo) == amount:
                    return [i for i, _b in combo]
        return None

    # -- duplicates -----------------------------------------------------------------------------------------
    def existing_payment(self, supplier_id: int, booking_date: date, amount_cents: int):
        """A payment with the same supplier and amount around that date (maybe booked by hand already)."""
        for pay in self.repos.payments.list(supplier_id=supplier_id):
            if pay.amount_cents == amount_cents and abs((pay.payment_date - booking_date).days) <= 5 \
                    and self.repos.bank.by_payment(pay.id or 0) is None:
                entries = self.repos.ledger.list(payment_id=pay.id)
                reversed_ids = {e.reverses_entry_id for e in entries if e.reverses_entry_id}
                if any(e.id not in reversed_ids and e.reverses_entry_id is None for e in entries):
                    return pay
        return None


