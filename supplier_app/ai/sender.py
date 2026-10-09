"""Sender / supplier recognition against the Party master data (names, aliases, IBAN, VAT id, fuzzy)."""

from __future__ import annotations

import re
from difflib import SequenceMatcher

from supplier_app.models.enums import DocumentType as D
from supplier_app.models.enums import PartyRole
from supplier_app.repositories.interfaces import PartyRepository
from supplier_app.util.normalize import normalize_name

from .interfaces import SenderMatcher
from .result_types import Classification, ExtractedFields, SenderMatch
from .rules import MANDATE_LABELS

_MANDATE_RE = re.compile(
    r"(?<![a-zäöüß])(?:" + "|".join(MANDATE_LABELS) + r")(?![a-zäöüß])[ \t]*:?[ \t]*(?P<rest>[^\n]*)", re.I)
_CUT = re.compile(r"\s[·|•]\s|\s{3,}|,")
FUZZY_MIN = 0.86


class RuleSenderMatcher(SenderMatcher):
    """Finds the letter author and the supplier whose ledger the document belongs to."""

    def __init__(self, parties: PartyRepository) -> None:
        self.parties = parties

    def _mandate_names(self, text: str) -> list[str]:
        names: list[str] = []
        for m in _MANDATE_RE.finditer(text):
            rest = _CUT.split(m.group("rest").strip())[0].strip()
            if len(rest) >= 3:
                names.append(rest)
        return names

    def _best_by_name(self, candidates: list[str], variants: list[tuple[int, str, str]]) -> tuple[int, float] | None:
        best: tuple[int, float] | None = None
        for cand in candidates:
            cn = normalize_name(cand)
            if len(cn) < 3:
                continue
            for pid, vnorm, _orig in variants:
                if len(vnorm) < 3:
                    continue
                score = 0.0
                if vnorm == cn:
                    score = 1.0
                elif vnorm in cn or cn in vnorm:
                    score = 0.88
                else:
                    ratio = SequenceMatcher(None, vnorm, cn).ratio()
                    score = ratio if ratio >= FUZZY_MIN else 0.0
                if score and (best is None or score > best[1]):
                    best = (pid, score)
        return best

    def match(self, text: str, fields: ExtractedFields, classification: Classification) -> SenderMatch | None:
        variants = self.parties.name_variants()
        dtype = classification.doc_type
        lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
        mandate_names = self._mandate_names(text)
        mandate_match = self._best_by_name(mandate_names, variants)

        author: tuple[int, float, str] | None = None
        if dtype != D.BANK_STATEMENT:
            head = [re.split(r"\s[·|•]\s", ln)[0] for ln in lines[:8]]
            head_hit = self._best_by_name(head, variants)
            if head_hit:
                author = (head_hit[0], 0.9 * head_hit[1], "Briefkopf")
            for iban in fields.ibans:
                if iban.confidence < 0.9:
                    continue
                for p in self.parties.find_by_iban(str(iban.value)):
                    if p.id is not None and (author is None or author[1] < 0.95):
                        author = (p.id, 0.95, "IBAN")
            for vat in fields.vat_ids:
                for p in self.parties.find_by_vat_id(str(vat.value)):
                    if p.id is not None and (author is None or author[1] < 0.95):
                        author = (p.id, 0.95, "USt-IdNr.")
            if author is None:
                stripped = "\n".join(ln for ln in text.splitlines() if not _MANDATE_RE.search(ln))
                body_hit = self._best_by_name([stripped[i : i + 120] for i in range(0, min(len(stripped), 2400), 60)], variants)
                if body_hit and body_hit[1] >= 0.88:
                    author = (body_hit[0], 0.55, "Name im Text")

        supplier_id: int | None = None
        reason_supplier = ""
        if mandate_match and mandate_match[1] >= FUZZY_MIN:
            party = self.parties.get(mandate_match[0])
            if party is not None:
                supplier_id = party.id if party.role != PartyRole.COLLECTION_AGENCY else party.represents_supplier_id
                reason_supplier = "Auftraggeber/Empfänger"
        if supplier_id is None and dtype == D.BANK_STATEMENT:
            for iban in fields.ibans:
                for p in self.parties.find_by_iban(str(iban.value)):
                    if p.role == PartyRole.SUPPLIER:
                        supplier_id, reason_supplier = p.id, "IBAN"
                        break
                if supplier_id:
                    break

        if author is not None:
            party = self.parties.get(author[0])
            assert party is not None
            if supplier_id is None:
                supplier_id = party.id if party.role != PartyRole.COLLECTION_AGENCY else party.represents_supplier_id
            return SenderMatch(party.id, party.name, round(author[1], 3), author[2], supplier_id)
        name = fields.sender_name.value if fields.sender_name and dtype != D.BANK_STATEMENT else ""
        if supplier_id is None and not name:
            return None
        reason = f"Neuer Absender; Lieferant über {reason_supplier}" if supplier_id else "Neuer Absender (nicht in den Stammdaten)"
        return SenderMatch(None, str(name), 0.3 if name else 0.0, reason, supplier_id)
