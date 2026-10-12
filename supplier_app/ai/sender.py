"""Sender / supplier recognition against the master data: ranked candidates with the evidence for each.

Evidence (each counts with its own strength, combined like independent witnesses):
IBAN, USt-IdNr., Steuernummer, e-mail / web domain, and the printed name compared with name, aliases of every party. The
name is looked for where a sender prints it (letterhead, "Absenderzeile", footer), not in the recipient block, and the
user's own companies and hotels are never taken for the sender. Collection letters name the creditor ("Mandant", "Gläubiger",
"im Auftrag von"); the ledger of a collection agency's letter is the one of the creditor.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Sequence

from supplier_app.models.entities import Party
from supplier_app.models.enums import DocumentType as D
from supplier_app.models.enums import PartyRole
from supplier_app.repositories.interfaces import PartyRepository
from supplier_app.util.normalize import normalize_iban, normalize_name

from .identity import NameCandidate, OwnNames, extract_identity, registrable
from .interfaces import SenderMatcher
from .names import NameWeights, contains_name, similarity
from .result_types import Classification, ExtractedFields, NewPartyInfo, PartyCandidate, SenderMatch
from .rules import MANDATE_LABELS

_MANDATE_RE = re.compile(
    r"(?<![a-zäöüß])(?:" + "|".join(MANDATE_LABELS) + r"|forderungsinhaber(?:in)?|ursprüngliche[rn]?\s+gläubiger(?:in)?|"
    r"leistungserbringer(?:in)?|rechnungssteller(?:in)?|vertragspartner(?:in)?|"
    r"wir\s+vertreten(?:\s+(?:die\s+interessen\s+(?:von|der|des)|den|die|herrn|frau|firma))?|"
    r"wir\s+sind\s+beauftragt\s+(?:von|durch)|namens\s+und\s+im\s+auftrag\s+(?:von|der|des))"
    r"(?![a-zäöüß])[ \t]*:?[ \t]*(?P<rest>[^\n]*)", re.I)
_CUT = re.compile(r"\s[·|•]\s|\s{3,}|,|\.(?:\s|$)|\s(?:zur|zu|wegen|aus|bezüglich|betreffend|für|und\s+fordern|fordert)\s")
_DUNNING = (D.PAYMENT_REMINDER, D.FIRST_DUNNING, D.SECOND_DUNNING, D.FINAL_DUNNING, D.COLLECTION_LETTER, D.COURT_ORDER)

SUGGEST_MIN = 0.4  # below: no suggestion, the form offers "new supplier"
CONFIDENT_MIN = 0.75


def _noisy_or(strengths: Sequence[float]) -> float:
    rest = 1.0
    for s in strengths:
        rest *= 1.0 - min(0.99, max(0.0, s))
    return round(1.0 - rest, 3)


class RuleSenderMatcher(SenderMatcher):
    """Finds the letter author and the supplier whose ledger the document belongs to."""

    def __init__(self, parties: PartyRepository, own_names: Callable[[], list[str]] | list[str] | None = None) -> None:
        self.parties = parties
        self._own = own_names or []

    def own(self) -> OwnNames:
        names = self._own() if callable(self._own) else self._own
        return OwnNames(list(names))

    # -- helpers --------------------------------------------------------------------------------------------
    @staticmethod
    def _mandate_names(text: str) -> list[str]:
        names: list[str] = []
        for m in _MANDATE_RE.finditer(text):
            rest = _CUT.split(m.group("rest").strip())[0].strip(" :;-")
            if len(rest) >= 3 and sum(c.isalpha() for c in rest) >= 3 and rest not in names:
                names.append(rest)
        return names

    def _evidence(self, party: Party, ident, text: str, weights: NameWeights, own: OwnNames) -> tuple[float, list[str]]:
        strengths: list[float] = []
        reasons: list[str] = []
        if set(map(normalize_iban, party.ibans)) & set(ident.ibans):
            strengths.append(0.97)
            reasons.append("IBAN")
        if party.vat_id and re.sub(r"\s+", "", party.vat_id).upper() in ident.vat_ids:
            strengths.append(0.97)
            reasons.append("USt-IdNr.")
        if party.tax_number and re.sub(r"\s+", "", party.tax_number) in ident.tax_numbers:
            strengths.append(0.93)
            reasons.append("Steuernummer")
        if party.email:
            mail = party.email.strip().lower()
            dom = registrable(mail.rsplit("@", 1)[-1]) if "@" in mail else ""
            if mail in ident.emails:
                strengths.append(0.9)
                reasons.append("E-Mail-Adresse")
            elif dom and dom in ident.domains:
                strengths.append(0.8)
                reasons.append("E-Mail-/Web-Domain")
        best_sim, best_cand = 0.0, None
        variants = [party.name, *party.aliases]
        for cand in ident.names:
            for variant in variants:
                sim = similarity(variant, cand.text, weights)
                if sim > best_sim:
                    best_sim, best_cand = sim, cand
        if best_cand is not None and best_sim >= 0.72:
            strengths.append(best_sim * (0.55 + 0.45 * best_cand.score))
            where = next((r for r in ("Absenderzeile", "Briefkopf", "Fußzeile") if r in best_cand.reasons), "Text")
            reasons.append(f"Name ({where}, {int(best_sim * 100)} %)")
        elif any(contains_name(text, v) and not own.matches(v) for v in variants if len(normalize_name(v)) >= 6):
            top = ident.names[0] if ident.names else None
            elsewhere = top is not None and top.score >= 0.55 and all(similarity(v, top.text, weights) < 0.6 for v in variants)
            strengths.append(0.2 if elsewhere else 0.5)  # a mention does not beat a clearly different letterhead
            reasons.append("Name im Text")
        return (_noisy_or(strengths) if strengths else 0.0), reasons

    def _rank(self, parties: list[Party], ident, text: str, weights: NameWeights, own: OwnNames,
              roles: tuple[PartyRole, ...] | None = None, minimum: float = 0.3) -> list[PartyCandidate]:
        out: list[PartyCandidate] = []
        for p in parties:
            if p.id is None or (roles is not None and p.role not in roles):
                continue
            score, reasons = self._evidence(p, ident, text, weights, own)
            if score >= minimum:
                out.append(PartyCandidate(p.id, p.name, score, reasons, p.role.value))
        out.sort(key=lambda c: (-c.score, c.name.lower()))
        if len(out) >= 2 and out[0].score < 0.9 and out[0].score - out[1].score < 0.08:
            out[0].reasons.append("mehrdeutig")
            out[0].score = round(out[0].score - 0.08, 3)
        out.sort(key=lambda c: (-c.score, c.name.lower()))
        return out[:6]

    def _new_party(self, ident, own: OwnNames, exclude: str = "") -> NewPartyInfo | None:
        best = next((n for n in ident.names if not exclude or normalize_name(n.text) != normalize_name(exclude)), None)
        if best is None:
            return None
        return NewPartyInfo(
            name=best.text, address=ident.address, vat_id=ident.vat_ids[0] if ident.vat_ids else "",
            tax_number=ident.tax_numbers[0] if ident.tax_numbers else "", email=ident.emails[0] if ident.emails else "",
            phone=ident.phones[0] if ident.phones else "", ibans=list(ident.ibans[:2]),
            alternatives=[n.text for n in ident.names if n is not best][:3])

    # -- main -------------------------------------------------------------------------------------------------
    def match(self, text: str, fields: ExtractedFields, classification: Classification) -> SenderMatch | None:
        dtype = classification.doc_type
        parties = self.parties.list()
        weights = NameWeights([n for p in parties for n in (p.name, *p.aliases)])
        own = self.own()
        ident = extract_identity(text, own)
        if dtype == D.BANK_STATEMENT:
            return self._payee(text, ident, parties, weights, own)

        body = "\n".join(ln for ln in text.splitlines() if not _MANDATE_RE.search(ln))  # a named creditor is not the author
        author_candidates = self._rank(parties, ident, body, weights, own)
        top = author_candidates[0] if author_candidates else None
        party = next((p for p in parties if top and p.id == top.party_id), None) if top and top.score >= SUGGEST_MIN else None

        supplier_candidates: list[PartyCandidate] = []
        creditor_name = ""
        supplier_id: int | None = None
        if dtype in _DUNNING:
            exclude = party.name if party else (ident.best_name().text if ident.best_name() else "")
            mand = [n for n in self._mandate_names(text) if normalize_name(n) != normalize_name(exclude) and not own.matches(n)]
            mand_ident = type(ident)()  # names only: the mandate names compared with the suppliers
            mand_ident.names = [NameCandidate(n, normalize_name(n), 0.9, ["Mandant/Gläubiger"], 0, False, True) for n in mand]
            suppliers = [p for p in parties if p.role != PartyRole.COLLECTION_AGENCY and (party is None or p.id != party.id)]
            supplier_candidates = self._rank(suppliers, mand_ident, "", weights, own, roles=None, minimum=0.45)
            if supplier_candidates and supplier_candidates[0].score >= 0.55:
                supplier_id = supplier_candidates[0].party_id
            elif party is not None and party.role == PartyRole.COLLECTION_AGENCY and party.represents_supplier_id:
                supplier_id = party.represents_supplier_id
                rep = next((p for p in parties if p.id == supplier_id), None)
                if rep is not None:
                    supplier_candidates.insert(0, PartyCandidate(rep.id or 0, rep.name, 0.7, ["vom Inkassobüro vertretener Lieferant"], rep.role.value))
            elif party is not None and party.role == PartyRole.SUPPLIER:
                supplier_id = party.id
            if supplier_id is None and mand:
                creditor_name = mand[0]
        else:
            suppliers_only = [c for c in author_candidates if c.role != PartyRole.COLLECTION_AGENCY.value]
            supplier_candidates = suppliers_only
            if party is not None:
                supplier_id = party.id if party.role != PartyRole.COLLECTION_AGENCY else party.represents_supplier_id

        new = self._new_party(ident, own)
        if party is not None:
            reason = ", ".join(top.reasons) if top else ""
            return SenderMatch(party.id, party.name, top.score if top else 0.0, reason, supplier_id,
                               author_candidates, supplier_candidates, new, creditor_name)
        if new is None and supplier_id is None and not creditor_name:
            return None
        name = new.name if new else ""
        reason = "Neuer Absender (nicht in den Stammdaten)"
        best = ident.best_name()
        score = round(0.2 + 0.4 * best.score, 3) if best else 0.0
        return SenderMatch(None, name, min(score, SUGGEST_MIN - 0.01) if author_candidates else score, reason, supplier_id,
                           author_candidates, supplier_candidates, new, creditor_name)

    def _payee(self, text: str, ident, parties: list[Party], weights: NameWeights, own: OwnNames) -> SenderMatch | None:
        """Payment documents: the supplier is the payee (by IBAN, else by the name after "Empfänger" ...)."""
        mand = [n for n in self._mandate_names(text) if not own.matches(n)]
        mand_ident = type(ident)()
        mand_ident.ibans = list(ident.ibans)
        mand_ident.names = [NameCandidate(n, normalize_name(n), 0.9, ["Empfänger"], 0, False, True) for n in mand]
        ranked = self._rank([p for p in parties if p.role == PartyRole.SUPPLIER], mand_ident, "", weights, own, minimum=0.45)
        if not ranked:
            return None
        top = ranked[0]
        return SenderMatch(None, "", 0.0, "Zahlungsempfänger: " + ", ".join(top.reasons), top.party_id, [], ranked, None, "")
