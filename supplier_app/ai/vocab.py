"""Multilingual vocabulary for invoices (German, English, French, Italian, Spanish, Dutch).

Everything here is plain data/regex so it can be extended without touching the extraction logic:
labels of amounts (Netto/Brutto/MwSt/Summe/Total ...), invoice numbers, dates and payment terms.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from supplier_app.util.dates import MONTH_WORDS

_MONTH_ALT = "|".join(sorted((re.escape(m) for m in MONTH_WORDS), key=len, reverse=True))

#: date notations: 15.03.2024, 15/03/24, 15-03-2024, 2024-03-15, 15 March 2024, March 15, 2024, 15 mars 2024
DATE_PATTERN = (
    r"(?<![\w.,/\-])(?:"
    r"\d{1,2}\s?[./-]\s?\d{1,2}\s?[./-]\s?(?:\d{4}|\d{2})(?![\d/\-])"
    r"|\d{4}\s?[./-]\s?\d{1,2}\s?[./-]\s?\d{1,2}(?![\d/\-])"
    rf"|\d{{1,2}}(?:st|nd|rd|th|\.|er)?\s+(?:de\s+)?(?:{_MONTH_ALT})\.?,?\s+(?:de\s+)?\d{{4}}(?!\d)"
    rf"|(?:{_MONTH_ALT})\.?\s+\d{{1,2}}(?:st|nd|rd|th)?,?\s+\d{{4}}(?!\d)"
    r")"
)

#: money amounts: 1.234,56 | 1 234,56 | 1\'234.56 | 1,234.56 | 1234,56 | 1234.56 (always two decimals, never a date)
AMOUNT_RE = re.compile(
    r"(?<![\w.,'’])(-?(?:\d{1,3}(?:\.\d{3})+,\d{2}|\d{1,3}(?: \d{3})+,\d{2}|\d{1,3}(?:['’]\d{3})+\.\d{2}|"
    r"\d{1,3}(?:,\d{3})+\.\d{2}|\d+,\d{2}|\d+\.\d{2}))(?![\d])(?!\.\d)(?!,\d)"
)

#: user-defined extra words per field (Settings -> Erkennung); keys of :class:`ExtraVocab`
EXTRA_VOCAB_KEYS = ("invoice_title", "invoice_number", "net", "vat", "gross", "document_date", "due_date")


def _word_pattern(word: str) -> str:
    """A user word as a regex: literal, whitespace/hyphen tolerant."""
    parts = [re.escape(p) for p in re.split(r"[\s\-]+", word.strip()) if p]
    return r"[\s\-]?".join(parts)


@dataclass(frozen=True)
class ExtraVocab:
    """Words the user added for suppliers that use unusual wording. They take precedence over the built-in vocabulary."""

    words: dict[str, tuple[str, ...]] = field(default_factory=dict)

    @staticmethod
    def from_settings(data: dict[str, list[str]] | None) -> ExtraVocab:
        cleaned = {k: tuple(w.strip() for w in (data or {}).get(k, []) if len(w.strip()) >= 2) for k in EXTRA_VOCAB_KEYS}
        return ExtraVocab({k: v for k, v in cleaned.items() if v})

    def patterns(self, key: str) -> list[str]:
        return [_word_pattern(w) for w in self.words.get(key, ())]

    def regex(self, key: str) -> re.Pattern[str] | None:
        pats = self.patterns(key)
        return re.compile(r"(?<![a-zäöüß])(?:" + "|".join(pats) + r")(?![a-zäöüß])", re.I) if pats else None

    def __bool__(self) -> bool:
        return bool(self.words)


# --------------------------------------------------------------------------------------------------------
# Amount labels. A label text (the words in front of the amount on its line) is classified into
# net / vat / gross with a strength: 3 = unambiguous, 2 = usually right, 1 = only at the start of the line.
# --------------------------------------------------------------------------------------------------------
_VAT_WORD = re.compile(
    r"\b(?:m\.?\s?w\.?\s?st\.?|ust\.?|u\.st\.?|mehrwert\s?steuer|umsatz\s?steuer|steuer(?:betrag)?|vat|tax|tva|iva|btw|"
    r"igv|mva|gst|sales\s+tax)\b", re.I)
_INCLUDING = re.compile(r"\b(?:inkl\.?|inklusive|incl\.?|including|inclusive|mit|con|avec|met|incl\.?\s*btw)\b", re.I)
_EXCLUDING = re.compile(
    r"\b(?:exkl\.?|exklusive|excl\.?|excluding|exclusive|ohne|without|sin|sans|senza|zonder|excl\.?\s*btw)\b", re.I)
_ADDING = re.compile(r"\b(?:zzgl\.?|zuzüglich|plus|\+|darin\s+enthalten|davon|enthaltene?|enthält|dont|di\s+cui|of\s+which)\b", re.I)

_NET_STRONG = re.compile(
    r"\b(?:netto(?:betrag|summe|wert|preis|entgelt\w*|honorar|rechnungsbetrag)?|betrag\s+netto|summe\s+netto|gesamt\s+netto|"
    r"warenwert|net(?:\s+(?:amount|total|price|value|sum))?|total\s+net|montant\s+h\.?\s?t\.?|total\s+h\.?\s?t\.?|"
    r"h\.?\s?t\.?|hors\s+taxes?|imponibile|totale\s+imponibile|base\s+imponible|base\s+imp\.?|netto\s*total|"
    r"nettobetrag|net\s*amount|excl\.?\s+vat|taxable\s+amount|bedrag\s+excl\w*|totaal\s+excl\w*)\b", re.I)
_NET_WEAK = re.compile(r"\b(?:zwischensumme|zwischensumme\s*\(?netto\)?|subtotal|sub-total|subtotaal|sous-total|"
                       r"subtotale|parcial|teilsumme|summe\s+positionen)\b", re.I)
_GROSS_STRONG = re.compile(
    r"\b(?:rechnungs(?:betrag|summe|endbetrag|total)|gesamt(?:betrag|summe|rechnungsbetrag|brutto|preis)|brutto(?:betrag|summe|"
    r"preis)?|betrag\s+brutto|summe\s+brutto|end(?:betrag|summe)|zahl(?:ungs)?betrag|zu\s+zahlen(?:der\s+betrag)?|"
    r"zu\s+zahlender\s+betrag|fälliger\s+betrag|gutschrifts(?:betrag|summe)|gross(?:\s+(?:amount|total|price))?|"
    r"grand\s+total|invoice\s+total|total\s+invoice|total\s+(?:amount|due|payable|gross|ttc)|amount\s+(?:due|payable)|"
    r"balance\s+due|total\s+due|amount\s+to\s+pay|montant\s+(?:ttc|total|à\s+payer)|total\s+ttc|ttc|net\s+à\s+payer|"
    r"total\s+à\s+payer|à\s+payer|totale\s+(?:documento|fattura|da\s+pagare|iva\s+inclusa|generale)|importo\s+totale|"
    r"da\s+pagare|total\s+factura|importe\s+total|total\s+a\s+pagar|totaal(?:\s+incl\w*)?|te\s+betalen|totaalbedrag|"
    r"factuurbedrag|honorar\s+gesamt|summe\s+gesamt|gesamt\s+inkl\w*)\b", re.I)
_GROSS_WEAK = re.compile(r"^(?:gesamt|total|summe|totale|totaal|betrag|amount|endsumme|sum)\b", re.I)
_IGNORE = re.compile(
    r"\b(?:skonto|rabatt|discount|escompte|sconto|abzgl\.?|abzüglich|anzahlung|vorauszahlung|bereits\s+(?:gezahlt|bezahlt|beglichen)|"
    r"deposit|einzelpreis|stückpreis|unit\s+price|prix\s+unitaire|menge|quantity|pfand|porto|versand|fracht|shipping|"
    r"zahlungseingang|payment\s+received|saldo\s+vortrag|übertrag)\b", re.I)
_RATE_IN_LABEL = re.compile(r"(\d{1,2}(?:[.,]\d+)?)\s*%")


_SPLIT_COMPOUND = re.compile(
    r"\b(rechnungs|gesamt|zwischen|mehrwert|umsatz|end|netto|brutto|zahl|zahlungs|gutschrifts)\s(betrag|summe|steuer|preis)\b", re.I)


def classify_amount_label(label: str, extra: ExtraVocab | None = None) -> tuple[str, float, str | None] | None:
    """Return ``(kind, strength, rate)`` for the words in front of an amount, or ``None`` if it is not a net/vat/gross label.

    ``kind`` is ``'net'``, ``'vat'`` or ``'gross'``; ``rate`` is the percentage printed in the label ("MwSt 19 %")."""
    text = re.sub(r"\s+", " ", label.strip(" \t:.-–_*|·•"))
    text = _SPLIT_COMPOUND.sub(lambda m: m.group(1) + m.group(2), text)  # OCR: "Rechnungs betrag"
    if extra:
        for kind in ("net", "vat", "gross"):
            rx = extra.regex(kind)
            if rx is not None and rx.search(text):
                rate_x = _RATE_IN_LABEL.search(text)
                return kind, 3.0, rate_x.group(1).replace(",", ".") if rate_x else None
    if not text or len(text) > 70 or re.search(r"\b\d{1,3}\s*(?:tage|tagen|days|jours|giorni)\b", text, re.I):
        return None
    rate_m = _RATE_IN_LABEL.search(text)
    rate = rate_m.group(1).replace(",", ".") if rate_m else None
    if _IGNORE.search(text) and not _GROSS_STRONG.search(text) and not _NET_STRONG.search(text):
        return None
    has_vat = bool(_VAT_WORD.search(text))
    net_hit, gross_hit = _NET_STRONG.search(text), _GROSS_STRONG.search(text)
    if has_vat:
        if _ADDING.search(text):
            return "vat", 3.0, rate
        if (gross_hit or _GROSS_WEAK.search(text)) and _INCLUDING.search(text):
            return "gross", 3.0, rate
        if (net_hit or _NET_WEAK.search(text) or _GROSS_WEAK.search(text)) and _EXCLUDING.search(text):
            return "net", 3.0, rate
        if gross_hit and re.search(r"\b(?:gesamt|total|summe|brutto|endbetrag|rechnungs\w+)\b", text, re.I) \
                and not re.search(r"\b(?:steuerbetrag|mwst|ust)\b", text, re.I):
            return "gross", 2.0, rate
        return "vat", 3.0, rate
    if gross_hit and net_hit and gross_hit.start() <= net_hit.start() and gross_hit.end() >= net_hit.end():
        return "gross", 3.0, rate  # "Net à payer": the net word is part of a gross phrase
    if net_hit:
        return "net", 3.0, rate
    if gross_hit:
        return "gross", 3.0, rate
    if _NET_WEAK.search(text):
        return "net", 1.5, rate
    if _GROSS_WEAK.search(text) and len(text) <= 30:
        return "gross", 1.0, rate
    return None


#: words that start/continue a column header of an amount table ("Netto  MwSt  Brutto")
COLUMN_WORDS = (
    ("net", re.compile(r"^(?:netto|net|ht|h\.t\.|imponibile|nettobetrag|subtotal|zwischensumme|base\s+imponible|montant\s+ht)\b", re.I)),
    ("vat", re.compile(r"^(?:mwst\.?|ust\.?|steuer|vat|tax|tva|iva|btw|mehrwertsteuer|umsatzsteuer)\b", re.I)),
    ("gross", re.compile(r"^(?:brutto|gross|ttc|gesamt|total|summe|totale|totaal|gesamtbetrag|endbetrag|rechnungsbetrag|betrag)\b", re.I)),
)

# --------------------------------------------------------------------------------------------------------
# Invoice numbers (value follows the label, on the same line or in the cell below)
# --------------------------------------------------------------------------------------------------------
#: strong labels name the number of an invoice/credit note/receipt explicitly
INVOICE_NUMBER_STRONG = [
    r"rechnungs\s?-?\s?(?:nummer|nr\.?|no\.?)", r"rechnung\s?-?\s?(?:nr\.?|nummer|no\.?|n°)", r"re\.?\s?-?\s?(?:nr\.?|nummer)",
    r"rg\.?\s?-?\s?(?:nr\.?|nummer)", r"r\.?\s?-?\s?nr\.?", r"invoice\s*(?:no\.?|number|nr\.?|num\.?|#|id)",
    r"inv\.?\s?(?:no\.?|nr\.?|#)", r"beleg\s?-?\s?(?:nummer|nr\.?|no\.?)", r"belegnummer", r"belegnr\.?",
    r"faktura\s?-?\s?(?:nummer|nr\.?|no\.?)", r"fakturanummer", r"dokument\s?-?\s?(?:nummer|nr\.?)",
    r"document\s*(?:no\.?|number|nr\.?|id)", r"doc\.?\s?(?:no\.?|nr\.?|number)", r"abrechnungs\s?-?\s?(?:nummer|nr\.?)",
    r"honorar\s?-?\s?(?:nummer|nr\.?)", r"gutschrifts\s?-?\s?(?:nummer|nr\.?)", r"gutschrift\s?-?\s?(?:nr\.?|nummer)",
    r"credit\s+note\s*(?:no\.?|number|nr\.?|#)", r"tax\s+invoice\s*(?:no\.?|number|nr\.?|#)", r"bill\s*(?:no\.?|number|#)",
    r"receipt\s*(?:no\.?|number|#)", r"quittungs\s?-?\s?(?:nummer|nr\.?)", r"kassenbon\s?-?\s?nr\.?",
    r"facture\s*(?:n[°ºo]\.?|no\.?|nr\.?|numéro|number|num\.?)", r"n[°º]\s*(?:de\s+)?facture", r"numéro\s+de\s+facture",
    r"avoir\s*(?:n[°ºo]\.?|no\.?)", r"fattura\s*(?:n[°ºo]?\.?|nr\.?|numero|num\.?)", r"numero\s+(?:della\s+)?fattura",
    r"nota\s+di\s+credito\s*(?:n[°ºo]?\.?)", r"factura\s*(?:n[°ºo]\.?|núm\.?|num\.?|no\.?|nr\.?|número)",
    r"n[úu]mero\s+de\s+factura", r"factuur\s?-?\s?(?:nummer|nr\.?|no\.?)", r"factuurnummer",
]
#: weaker hints: "Rechnung 2024-117", "zu Rechnung RE-1", "Ihre Rechnung"
INVOICE_NUMBER_WEAK = [
    r"(?:ihre|unsere|zur|die|der|zu)\s+rechnung(?:\s+(?:nr\.?|nummer))?", r"rechnung\s+vom", r"invoice", r"rechnung", r"facture",
    r"fattura", r"factura", r"factuur", r"faktura", r"beleg", r"belegnr", r"honorarnote", r"abrechnung",
]
#: bare header cells of a table whose first column is the invoice number ("Nr.   Datum   Kunde")
BARE_DATE_CELL = re.compile(r"^(?:datum|date|data|fecha|belegdatum|rechnungsdatum)$", re.I)
BARE_NUMBER_CELL = re.compile(r"^(?:nr\.?|no\.?|n°|nummer|number|num\.?|rechnung|invoice|facture|fattura|factura|beleg)$", re.I)

# --------------------------------------------------------------------------------------------------------
# Dates
# --------------------------------------------------------------------------------------------------------
DOCUMENT_DATE_LABELS = [
    r"rechnungs\s?-?\s?datum", r"belegdatum", r"beleg\s?-?\s?datum", r"fakturadatum", r"ausstellungsdatum", r"briefdatum",
    r"dokumentdatum", r"abrechnungsdatum", r"gutschriftsdatum", r"datum\s+der\s+rechnung", r"ausgestellt\s+am", r"rechnung\s+vom",
    r"invoice\s+date", r"date\s+of\s+(?:issue|invoice)", r"issue\s+date", r"issued(?:\s+on)?", r"document\s+date", r"tax\s+point",
    r"date\s+(?:de\s+)?(?:la\s+)?facture", r"date\s+d['’]émission", r"facture\s+du", r"data\s+(?:della\s+)?(?:fattura|documento|emissione)",
    r"fattura\s+del", r"fecha\s+(?:de\s+)?(?:factura|emisión|expedición)", r"factuurdatum", r"datum\s+factuur",
    r"mahndatum", r"^[ \t]*(?:rechnung|beleg|faktura|gutschrift|invoice|facture|fattura|factura|credit\s+note)\b[^\n]{0,60}?\b(?:vom|dated|du|del|of|from)",
    r"^[ \t]*(?:datum|date|data|fecha)(?=[ \t]*[:.]?[ \t]*(?:\d|[^\W\d_]+[ \t]+\d))",
]
PAYMENT_DATE_LABELS = [
    r"ausführungsdatum", r"buchungsdatum", r"zahlungsdatum", r"wertstellung", r"valuta", r"booking\s+date", r"payment\s+date",
    r"date\s+de\s+paiement", r"data\s+(?:di\s+)?pagamento", r"fecha\s+de\s+pago", r"betaaldatum",
]
DUE_DATE_LABELS = [
    r"zahlbar\s+(?:netto\s+)?(?:bis|zum)", r"fällig(?:keit(?:sdatum)?)?(?:\s+(?:am|bis|zum))?", r"zahlungsziel", r"zahlungsfrist",
    r"zahlung\s+bis", r"zahlen\s+sie\s+(?:bitte\s+)?(?:den\s+betrag\s+)?bis(?:\s+(?:spätestens|zum))?", r"zu\s+zahlen\s+bis",
    r"bis\s+spätestens", r"spätestens\s+bis", r"netto\s+bis", r"zahlbar\s+bis", r"frist(?:\s+bis)?", r"überweisen\s+sie\s+(?:bitte\s+)?bis",
    r"due\s+(?:date|on|by)", r"payment\s+due(?:\s+(?:date|by|on))?", r"pay\s+(?:by|before)", r"payable\s+(?:by|before|on)", r"deadline",
    r"date\s+d['’]échéance", r"échéance", r"à\s+payer\s+avant\s+le", r"payable\s+(?:avant|le)", r"règlement\s+(?:avant|le)",
    r"data\s+(?:di\s+)?scadenza", r"scadenza", r"pagamento\s+entro", r"da\s+pagare\s+entro",
    r"fecha\s+de\s+vencimiento", r"vencimiento", r"vervaldatum", r"betalen\s+(?:voor|vóór|uiterlijk)", r"uiterlijk",
]
_DAYS = r"(?:tage|tagen|tag|days?|jours?|giorni|d[ií]as|dagen)"
#: "30 Tage netto", "Net 30", "Zahlungsziel: 14 Tage", "Paiement à 30 jours", "payable within 10 days"
RELATIVE_TERMS = [
    re.compile(rf"(?P<d>\d{{1,3}})\s*{_DAYS}\s*(?:netto|net|nett|rein\s+netto|ohne\s+abzug|strictement\s+net)\b", re.I),
    re.compile(rf"\b(?:netto|nett)\s*[:.]?\s*(?:zahlbar\s+)?(?:innerhalb\s+(?:von\s+)?)?(?P<d>\d{{1,3}})\s*{_DAYS}", re.I),
    re.compile(r"\bnet\s*:?\s*(?P<d>\d{1,3})\b(?![.,]\d)", re.I),
    re.compile(rf"(?:zahlungs\w*|zahlbar|zahlung|zahlen|payment|terms?|paiement|pagamento|pago|betaling|innerhalb|within|binnen|entro|"
               rf"à)\b(?:[^\n.;]|\n(?!\n)){{0,45}}?(?P<d>\d{{1,3}})\s*{_DAYS}", re.I),
]
IMMEDIATE_TERMS = re.compile(
    r"\b(?:sofort\s+(?:fällig|zahlbar|zu\s+zahlen)|zahlbar\s+sofort|fällig\s+sofort|ohne\s+abzug\s+sofort|due\s+(?:on|upon)\s+receipt|"
    r"payable\s+(?:on|upon)\s+receipt|immediate(?:ly)?\s+(?:payable|due)|payable\s+immediately|à\s+réception|alla\s+ricezione|"
    r"al\s+contado|bij\s+ontvangst)\b|\bsofort\s+fällig\b", re.I)
SKONTO_LINE = re.compile(r"skonto|discount|escompte|sconto|descuento|korting", re.I)
#: dates that describe the delivery, not the invoice
SERVICE_DATE_CONTEXT = re.compile(
    r"(?:leistungs|liefer|lieferungs|service|delivery|performance|versand|bestell|order|prestation|consegna)\w*\s*(?:datum|date|zeitraum|period)?"
    r"\s*[:.]?\s*$|leistungszeitraum|zeitraum", re.I)

#: plausible VAT rates (percent) of the countries we see
VAT_RATES = (0.0, 2.5, 2.6, 3.8, 4.0, 5.0, 5.5, 6.0, 7.0, 7.7, 8.1, 9.0, 10.0, 12.0, 13.0, 14.0, 15.0, 16.0, 19.0, 20.0, 21.0,
             22.0, 23.0, 24.0, 25.0, 27.0)
