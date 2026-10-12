"""Who wrote the document? Name candidates from letterhead, "Absenderzeile" and footer, plus contact and tax data.

A German business letter names its author in several places: the letterhead, the small sender line above the address
window ("Müller GmbH · Hauptstr. 1 · 10115 Berlin"), and the footer with legal line and bank data. The recipient - the
user's own company or hotel - is printed as well and must never be taken for the sender. Each name candidate gets a
plausibility score from the evidence (legal form, position, repeated in header and footer, name contained in the e-mail
or web domain, next to IBAN / tax data).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from supplier_app.util.normalize import normalize_iban, normalize_name, valid_iban

from .names import GENERIC_WORDS, tokens_of

GENERIC_MAIL_DOMAINS = frozenset("""
gmail.com googlemail.com web.de gmx.de gmx.net gmx.at gmx.ch t-online.de outlook.com outlook.de hotmail.com hotmail.de live.de
yahoo.com yahoo.de icloud.com me.com freenet.de aol.com online.de arcor.de 1und1.de protonmail.com mail.de posteo.de
""".split())
_SECOND_LEVEL = {"co", "com", "org", "net", "ac", "gov", "or", "ne"}

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@([A-Za-z0-9\-]+(?:\.[A-Za-z0-9\-]+)*\.[A-Za-z]{2,})")
URL_RE = re.compile(r"(?:https?://)?(?:www\.)([A-Za-z0-9\-]+(?:\.[A-Za-z0-9\-]+)*\.[A-Za-z]{2,})", re.I)
TAX_NUMBER_RE = re.compile(
    r"(?:steuer\s?-?\s?(?:nummer|nr\.?)|st\.?\s?-?\s?nr\.?|tax\s+(?:no\.?|number|id))\s*:?\s*(\d{2,3}\s?/\s?\d{3}\s?/\s?\d{4,5}|\d{10,11})",
    re.I)
PHONE_RE = re.compile(r"(?:tel(?:efon)?\.?|phone|fon)\s*:?\s*([+\d][\d /()\-]{6,})", re.I)

LEGAL_FORMS = (
    r"gmbh(?:\s*&\s*co\.?\s*(?:kg|ohg))?|ag|kg|ohg|gbr|ug(?:\s*\(haftungsbeschränkt\))?|mbh|e\.?\s?k\.?|e\.?\s?v\.?|"
    r"ltd\.?|limited|inc\.?|llc|plc|se|kgaa|partg(?:\s?mbb)?|mbb|s\.?a\.?r\.?l\.?|sas|srl|s\.?p\.?a\.?|b\.?v\.?|n\.?v\.?|pty|"
    r"gesellschaft(?:\s+mit\s+beschränkter\s+haftung)?|eg|stiftung|gmbh\s*&\s*co\.?\s*kg"
)
LEGAL_FORM_END = re.compile(rf"(?:^|[\s,])(?:{LEGAL_FORMS})\.?\s*(?:\([^)]*\))?\s*$", re.I)
LEGAL_FORM_ANY = re.compile(rf"(?<![A-Za-zÄÖÜäöüß])(?:{LEGAL_FORMS})(?![A-Za-zÄÖÜäöüß])", re.I)
BUSINESS_WORDS = re.compile(
    r"(?:bürobedarf|werbetechnik|maschinenbau|logistik|steuerberat|rechtsanwält|getränke|bäckerei|metzgerei|gärtnerei|gartenbau|"
    r"elektro|sanitär|haustechnik|wäscherei|versicherung|makler|immobilien|hausverwaltung|stadtwerke|energie|telekom|verlag|druckerei|"
    r"spedition|handel|großhandel|service|dienstleistung|bau|reinigung|hotelbedarf|einkauf|inkasso|forderungsmanagement|kanzlei)",
    re.I)

STREET_RE = re.compile(
    r"\b[A-ZÄÖÜ][\wäöüß.\- ]{1,40}?(?:straße|strasse|str\.|weg|allee|platz|gasse|ring|damm|ufer|chaussee|steig|pfad|hof|markt|"
    r"park|promenade|kai|steg|zeile|road|street|lane|avenue|rd\.|st\.)\s*\d+\s*[a-zA-Z]?\b|\b\d+\s+[A-Z][\w ]{2,30}\s(?:road|street|lane|avenue)\b",
    re.I)
ZIPCITY_RE = re.compile(r"\b(?:[A-Z]{1,2}-)?\d{4,5}\s+[A-ZÄÖÜ][\wäöüß\-./ ]{1,40}|\b[A-Z]\d{2}\s?[A-Z0-9]{4}\b")
POSTFACH_RE = re.compile(r"\bpostfach\b", re.I)
CONTACT_RE = re.compile(r"\b(?:tel(?:efon)?\.?|fax|mobil|handy|e-?mail|internet|web|www\.|homepage|phone)\b|@|https?://", re.I)
BANK_RE = re.compile(r"\b(?:iban|bic|swift|kontonummer|konto-?nr|blz|bankleitzahl|bankverbindung|konto)\b", re.I)
LEGAL_INFO_RE = re.compile(
    r"\b(?:amtsgericht|registergericht|handelsregister|hr[ab]\s*\d|geschäftsführ|vorstand|vorsitzende|aufsichtsrat|inhaber|"
    r"ust-?\s?id|umsatzsteuer|steuer\s?-?(?:nummer|nr)|finanzamt|sitz\s+der\s+gesellschaft|sitz:|gerichtsstand|persönlich\s+haftende|"
    r"vat\s+(?:no|id|number)|company\s+(?:no|number|reg)|registered)\b", re.I)
PAGE_RE = re.compile(r"\b(?:seite|page|blatt)\s*\d+(?:\s*(?:von|of|/)\s*\d+)?\b", re.I)
DATE_RE = re.compile(r"\b\d{1,2}\.\s?\d{1,2}\.\s?\d{2,4}\b")
TITLE_RE = re.compile(
    r"^(?:rechnung|mahnung|\d\.\s*mahnung|zahlungserinnerung|gutschrift|inkassoschreiben|mahnbescheid|lieferschein|angebot|kontoauszug|"
    r"letzte\s+mahnung|invoice|reminder|credit\s+note|statement|abrechnung|zahlungsaufforderung|mahnschreiben)\b", re.I)
SALUTATION_RE = re.compile(r"^(?:frau|herr|herrn|firma|sehr\s+geehrte|z\.?\s?hd\.?|zu\s+händen|attn|dear|buchhaltung|an\s*:)\b", re.I)
LABEL_RE = re.compile(
    r"\b(?:nummer|nr\.?|datum|betrag|summe|zeichen|referenz|kunde|kd\.?|vertrag|bearbeiter|ansprechpartner|durchwahl|"
    r"aktenzeichen|forderung|fällig|zahlbar|lieferdatum|leistungsdatum|bestellung|auftrag)\b[^\n]{0,3}:?\s*$", re.I)
SLOGAN_RE = re.compile(r"\b(?:partner|seit\s+\d{4}|ihr[e]?\s|qualität|zuverlässig|kompetent|willkommen|wir\s)\b", re.I)
_SEP = re.compile(r"\s[·|•‧]\s|\s{3,}|\t+|\s[–—]\s|\s/\s")


@dataclass
class NameCandidate:
    text: str  # cleaned, as printed
    norm: str  # comparison form (no legal form, no umlauts)
    score: float
    reasons: list[str] = field(default_factory=list)
    line: int = 0
    sender_line: bool = False  # came from a "name · street · zip city" line
    legal_form: bool = False


@dataclass
class DocumentIdentity:
    names: list[NameCandidate] = field(default_factory=list)
    ibans: list[str] = field(default_factory=list)
    vat_ids: list[str] = field(default_factory=list)
    tax_numbers: list[str] = field(default_factory=list)
    emails: list[str] = field(default_factory=list)
    domains: list[str] = field(default_factory=list)  # registrable domains of e-mails and web sites (no free mail providers)
    phones: list[str] = field(default_factory=list)
    address: str = ""  # "Hauptstraße 12, 10115 Berlin" of the best name candidate

    def best_name(self) -> NameCandidate | None:
        return self.names[0] if self.names else None


def registrable(domain: str) -> str:
    parts = domain.lower().strip(".").split(".")
    if len(parts) >= 3 and parts[-2] in _SECOND_LEVEL:
        return ".".join(parts[-3:])
    return ".".join(parts[-2:])


def _contacts(text: str) -> tuple[list[str], list[str]]:
    emails, domains = [], []
    for m in EMAIL_RE.finditer(text):
        dom = registrable(m.group(1))
        if m.group(0).lower() not in emails:
            emails.append(m.group(0).lower())
        if dom not in GENERIC_MAIL_DOMAINS and dom not in domains:
            domains.append(dom)
    for m in URL_RE.finditer(text):
        dom = registrable(m.group(1))
        if dom not in GENERIC_MAIL_DOMAINS and dom not in domains:
            domains.append(dom)
    return emails, domains


def _clean_segment(seg: str) -> str:
    seg = seg.strip(" \t.,;:-–—|·•")
    seg = re.sub(r"\s+", " ", seg)
    # an address glued to the name: "Müller GmbH Hauptstraße 12 10115 Berlin"
    for rx in (STREET_RE, ZIPCITY_RE, POSTFACH_RE, PAGE_RE, EMAIL_RE, URL_RE, CONTACT_RE, BANK_RE, LEGAL_INFO_RE):
        m = rx.search(seg)
        if m and m.start() >= 4:
            seg = seg[: m.start()].strip(" ,.-–|·•")
    return seg


def _is_name_like(seg: str) -> bool:
    if len(seg) < 3 or len(seg) > 75:
        return False
    if sum(c.isalpha() for c in seg) < 3:
        return False
    words = seg.split()
    if len(words) > 9:
        return False
    for rx in (STREET_RE, ZIPCITY_RE, POSTFACH_RE, CONTACT_RE, BANK_RE, LEGAL_INFO_RE, PAGE_RE, DATE_RE, TITLE_RE, SALUTATION_RE):
        if rx.search(seg):
            return False
    if LABEL_RE.search(seg) or ":" in seg:
        return False
    if re.fullmatch(r"[\d\W]+", seg):
        return False
    if seg.endswith((".", ",")) and len(words) > 4:  # a sentence
        return False
    if not seg[0].isalnum() and seg[0] not in "ÄÖÜ(":
        return False
    return True


class OwnNames:
    """The user's own companies and hotels (they appear as recipient and must not be taken for the sender)."""

    def __init__(self, names: list[str] | None = None) -> None:
        self._sets = [frozenset(t for t in tokens_of(n)) for n in (names or []) if n.strip()]
        self._sets = [s for s in self._sets if s]

    def matches(self, segment: str) -> bool:
        toks = frozenset(tokens_of(segment))
        if not toks:
            return False
        for own in self._sets:
            if toks == own:
                return True
            if len(own) >= 2 and own <= toks and len(toks) <= len(own) + 1:
                return True  # "Hotel Seeblick Lübeck"
            if len(toks) >= 2 and toks <= own:
                return True
            if len(own) == 1 and toks <= own:
                return True
        return False

    @property
    def configured(self) -> bool:
        return bool(self._sets)


def _domain_hit(norm: str, domains: list[str]) -> int:
    """How many distinct name words (or word beginnings) are contained in the e-mail / web domains."""
    if not domains:
        return 0
    compact = [re.sub(r"[^a-z0-9]", "", d.rsplit(".", 1)[0]) for d in domains]
    hits = 0
    for tok in set(norm.split()):
        if len(tok) < 4 or tok in GENERIC_WORDS:
            continue
        if any(tok in c or (len(c) >= 5 and c in tok) or (len(tok) >= 6 and tok[:6] in c) for c in compact):
            hits += 1
    return hits


def extract_identity(text: str, own: OwnNames | None = None) -> DocumentIdentity:
    own = own or OwnNames()
    ident = DocumentIdentity()
    lines = text.splitlines()
    nonempty = [i for i, ln in enumerate(lines) if ln.strip()]
    header_idx = set(nonempty[:25])
    footer_idx = set(nonempty[-24:])
    ident.emails, ident.domains = _contacts(text)
    for m in re.finditer(r"\b[A-Z]{2}\d{2}(?:\s?[A-Z0-9]{4}){3,7}(?:\s?[A-Z0-9]{1,4})?\b", text):
        iban = normalize_iban(m.group(0))
        while len(iban) > 14 and not valid_iban(iban):
            iban = iban[:-1]
        if valid_iban(iban) and iban not in ident.ibans:
            ident.ibans.append(iban)
    for m in re.finditer(r"\b(DE\s?\d{9}|ATU\d{8}|NL\d{9}B\d{2}|FR[A-Z0-9]{2}\s?\d{9}|IT\d{11}|PL\d{10}|BE0?\d{9,10}|IE\d[A-Z0-9]\d{5}[A-Z]{1,2})\b", text):
        vat = re.sub(r"\s+", "", m.group(1))
        if vat not in ident.vat_ids:
            ident.vat_ids.append(vat)
    for m in TAX_NUMBER_RE.finditer(text):
        tax = re.sub(r"\s+", "", m.group(1))
        if tax not in ident.tax_numbers:
            ident.tax_numbers.append(tax)
    for m in PHONE_RE.finditer(text):
        phone = re.sub(r"\s+", " ", m.group(1)).strip(" -/")
        if phone not in ident.phones:
            ident.phones.append(phone)

    found: dict[str, NameCandidate] = {}
    line_norms = [normalize_name(ln) for ln in lines]
    for i in sorted(header_idx | footer_idx):
        line = lines[i].strip()
        if not line:
            continue
        pieces = [p for p in _SEP.split(line) if p.strip()]
        absender = False
        if len(pieces) >= 2 and any(STREET_RE.search(p) or ZIPCITY_RE.search(p) for p in pieces[1:]):
            absender = True  # "Name · Straße 1 · 12345 Ort"
        m = re.match(r"^(?P<n>[^,]{3,60}?),\s*(?P<s>[^,]*\d[^,]*),\s*(?:[A-Z]{1,2}-)?\d{4,5}\s+\S", line)
        if m:
            pieces, absender = [m.group("n")], True
        elif len(pieces) == 1:
            pieces = [line]
        for rank, piece in enumerate(pieces):
            seg = _clean_segment(piece)
            if not _is_name_like(seg) or own.matches(seg):
                continue
            norm = normalize_name(seg)
            if len(norm) < 3:
                continue
            legal = bool(LEGAL_FORM_ANY.search(seg))
            if not legal and not (absender and rank == 0) and not BUSINESS_WORDS.search(seg):
                # without legal form only a few lines qualify: the very first lines of the letterhead
                if not (i in nonempty[:4] and len(seg.split()) <= 5 and not SLOGAN_RE.search(seg)):
                    continue
            score = 0.15
            reasons: list[str] = []
            if legal:
                score += 0.3
                reasons.append("Rechtsform")
            if absender and rank == 0:
                score += 0.3
                reasons.append("Absenderzeile")
            pos = nonempty.index(i) if i in nonempty else 99
            if i in header_idx:
                score += 0.2 if pos < 6 else 0.1
                reasons.append("Briefkopf")
            if i in footer_idx and i not in header_idx:
                score += 0.1
                reasons.append("Fußzeile")
            if SLOGAN_RE.search(seg) and not legal:
                score -= 0.2
            cand = found.get(norm)
            if cand is None:
                cand = found[norm] = NameCandidate(seg, norm, score, reasons, i, absender and rank == 0, legal)
            else:
                cand.score = max(cand.score, score) + 0.05
                cand.reasons = list(dict.fromkeys([*cand.reasons, *reasons]))
                cand.sender_line = cand.sender_line or (absender and rank == 0)
                if legal and not cand.legal_form:
                    cand.legal_form, cand.text = True, seg  # prefer the form with legal form
                elif seg != seg.upper() and cand.text == cand.text.upper():
                    cand.text = seg  # prefer mixed case over CAPITALS
    for cand in found.values():
        occurrences = sum(1 for ln in line_norms if cand.norm and f" {cand.norm} " in f" {ln} ")
        if occurrences >= 2:
            cand.score += min(0.3, 0.15 * (occurrences - 1))
            cand.reasons.append("mehrfach genannt")
        hits = _domain_hit(cand.norm, ident.domains)
        if hits:
            cand.score += 0.25 if hits == 1 else 0.35
            cand.reasons.append("passt zur E-Mail-/Web-Adresse")
        near_bank = any(
            cand.norm in f" {line_norms[j]} " and (BANK_RE.search(lines[j]) or LEGAL_INFO_RE.search(lines[j]))
            for j in footer_idx if j < len(lines))
        if near_bank:
            cand.score += 0.1
        cand.score = max(0.0, min(1.0, cand.score))
    # a name that is only a part of a better candidate ("Müller Bürobedarf" vs "Müller Bürobedarf GmbH") is merged into it
    ordered = sorted(found.values(), key=lambda c: (-c.score, c.line))
    result: list[NameCandidate] = []
    for cand in ordered:
        merged = False
        for kept in result:
            if kept.norm.startswith(cand.norm + " ") or cand.norm.startswith(kept.norm + " ") or kept.norm == cand.norm:
                kept.score = min(1.0, kept.score + 0.05)
                merged = True
                break
        if not merged:
            result.append(cand)
    ident.names = result[:6]
    if ident.names:
        best = ident.names[0]
        line = lines[best.line] if best.line < len(lines) else ""
        street = STREET_RE.search(line)
        zipc = ZIPCITY_RE.search(line)
        if not (street and zipc):  # letterhead: the address is on one of the next lines
            for j in range(best.line + 1, min(len(lines), best.line + 4)):
                street = street or STREET_RE.search(lines[j])
                zipc = zipc or ZIPCITY_RE.search(lines[j])
        if street and zipc:
            ident.address = f"{street.group(0).strip()}, {zipc.group(0).strip()}"
    return ident
