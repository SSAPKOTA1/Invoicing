"""Default recognition rules (German + English). Configurable: user keywords extend reference labels."""

from __future__ import annotations

import re

from supplier_app.models.enums import DocumentType as D
from supplier_app.models.enums import ReferenceType as R

# (regex, weight). Patterns matched inside the title zone (first lines) get TITLE_BONUS times the weight.
CLASSIFIER_RULES: dict[D, list[tuple[str, float]]] = {
    D.INVOICE: [
        (r"^\s*rechnung\s*$", 6), (r"^\s*invoice\s*$", 6), (r"\brechnungs(?:nummer|datum|betrag|nr)\b", 3),
        (r"\binvoice\s*(?:no\b|number|date|#)", 3), (r"\binvoice\b", 1.5), (r"\bzahlbar\s+bis\b", 1),
        (r"\b(?:due date|payment due)\b", 1), (r"\b(?:mwst|ust|vat)\b", 0.8), (r"\bnettobetrag\b|\bnet amount\b", 1),
        (r"\bleistungsdatum\b|\blieferdatum\b", 1), (r"\bbankverbindung\b", 0.5),
    ],
    D.CREDIT_NOTE: [
        (r"^\s*gutschrift\b", 7), (r"\bgutschrifts(?:nummer|betrag)\b", 4), (r"\bcredit note\b", 6),
        (r"\bstornorechnung\b", 4), (r"\bgutgeschrieben\b", 1.5),
    ],
    D.PAYMENT_REMINDER: [
        (r"\bzahlungserinnerung\b", 8), (r"\bpayment reminder\b|\bfriendly reminder\b", 8),
        (r"\bfreundliche[nr]?\s+erinnerung\b", 5), (r"\berinnerung\b", 2), (r"\bversehentlich\b|\bübersehen\b", 2),
        (r"\bmahnung\b", 1),
    ],
    D.FIRST_DUNNING: [
        (r"^\s*(?:1\.?|erste)\s*mahnung\b", 10), (r"(?<!gebühr )(?<!gebühren )(?<!kosten )\b(?:1\.?|erste)\s*mahnung\b", 3),
        (r"\bfirst\s+(?:dunning|reminder|notice)\b", 8), (r"\bmahnung\b", 3),
        (r"\bmahngebühr", 1.5),
    ],
    D.SECOND_DUNNING: [
        (r"^\s*(?:2\.?|zweite)\s*mahnung\b", 10),
        (r"(?<!gebühr )(?<!gebühren )(?<!kosten )\b(?:2\.?|zweite)\s*mahnung\b", 3), (r"\bsecond\s+(?:dunning|reminder|notice)\b", 8),
    ],
    D.FINAL_DUNNING: [
        (r"^\s*(?:3\.?|dritte)\s*mahnung\b", 10), (r"^\s*letzte\s+mahnung\b", 10),
        (r"(?<!gebühr )(?<!gebühren )(?<!kosten )\b(?:3\.?|dritte)\s*mahnung\b", 3), (r"\bletzte\s+mahnung\b", 4), (r"\bletzte[rn]?\s+aufforderung\b", 6),
        (r"\bfinal\s+(?:notice|demand|reminder|dunning)\b", 8), (r"\bletztmalig\b|\bletzte\s+frist\b", 3),
    ],
    D.COLLECTION_LETTER: [
        (r"\binkassoschreiben\b", 9), (r"\binkasso\b", 3), (r"\bforderungsaufstellung\b", 5),
        (r"\binkassokosten\b|\binkassogebühr", 5), (r"\bzum\s+einzug\s+übergeben\b|\babgetreten\b|\bforderungsübergang\b", 4),
        (r"\bdebt\s+collection\b|\bcollection\s+agency\b", 7), (r"\brechtsanwaltsvergütung\b|\brvg\b", 3),
        (r"\bmandant", 1.5), (r"\bwir\s+vertreten\b", 4),
    ],
    D.COURT_ORDER: [
        (r"^\s*mahnbescheid\b", 10), (r"\bmahnbescheid\b", 5), (r"\bvollstreckungsbescheid\b", 8),
        (r"\bmahngericht\b|\bamtsgericht\b", 3), (r"\bwiderspruch\s+einlegen\b", 4), (r"\bgerichtskosten\b", 2),
        (r"\bpayment order\b|\bcourt order\b", 6),
    ],
    D.BANK_STATEMENT: [
        (r"\bzahlungsbestätigung\b|\bzahlungsbeleg\b|\büberweisungsbeleg\b|\bbuchungsbestätigung\b", 7),
        (r"\bkontoauszug\b", 7), (r"\bbank statement\b|\bpayment confirmation\b|\bremittance advice\b", 7),
        (r"\büberweisung\s+wurde\s+ausgeführt\b", 4), (r"\bausführungsdatum\b|\bbuchungsdatum\b", 2),
        (r"\bverwendungszweck\b", 2), (r"\bempfänger\b|\bbeneficiary\b", 1),
    ],
    D.DELIVERY_NOTE: [
        (r"^\s*lieferschein\b", 8), (r"\blieferscheinnummer\b", 6), (r"\bdelivery note\b|\bpacking slip\b", 8),
        (r"\bwarenempfang\b|\bware\s+wurde\b", 2),
    ],
}
TITLE_LINES = 16
TITLE_BONUS = 1.5

# Labels (regex alternations, case-insensitive) for references. User keywords from Settings are appended.
REFERENCE_LABELS: dict[R, list[str]] = {
    R.PROCESSING_NUMBER: [r"bearbeitungs\s?-?\s?(?:nummer|nr\.?|zeichen)", r"processing\s+(?:no\.?|number)"],
    R.FILE_NUMBER: [r"aktenzeichen", r"geschäftszeichen", r"\baz\.?(?=\s*[:\s])", r"file\s+(?:no\.?|number|reference)"],
    R.CASE_NUMBER: [r"vorgangs\s?-?\s?(?:nummer|nr\.?)", r"fallnummer", r"ticket\s?(?:nummer|nr\.?)?", r"case\s+(?:no\.?|number|id)"],
    R.CLAIM_NUMBER: [r"forderungs\s?-?\s?(?:nummer|nr\.?|referenz)", r"claim\s+(?:no\.?|number|ref(?:erence)?)"],
    R.CUSTOMER_NUMBER: [r"kunden\s?-?\s?(?:nummer|nr\.?)", r"kd\.?\s?-?\s?nr\.?", r"customer\s+(?:no\.?|number|id)"],
    R.MANDATE_NUMBER: [r"mandats\s?-?\s?(?:nummer|nr\.?|referenz)", r"mandate\s+(?:no\.?|number|reference)"],
    R.DEBTOR_NUMBER: [r"debitoren\s?-?\s?(?:nummer|nr\.?)", r"schuldner\s?-?\s?(?:nummer|nr\.?)", r"debtor\s+(?:no\.?|number)"],
    R.ORDER_NUMBER: [r"bestell\s?-?\s?(?:nummer|nr\.?)", r"auftrags\s?-?\s?(?:nummer|nr\.?)", r"order\s+(?:no\.?|number)", r"purchase\s+order"],
    R.PAYMENT_REFERENCE: [r"zahlungs\s?-?\s?referenz(?:nummer)?", r"payment\s+reference"],
    R.OTHER: [r"ihr\s+zeichen", r"unser\s+zeichen", r"ihre\s+referenz", r"unsere\s+referenz", r"your\s+reference", r"reference"],
}

INVOICE_NUMBER_LABELS = [
    r"rechnungs\s?-?\s?(?:nummer|nr\.?)", r"rechnung\s+(?:nr\.?|nummer|no\.?)", r"re\.?\s?-?\s?nr\.?",
    r"invoice\s+(?:no\.?|number|#)", r"belegnummer", r"(?:ihre|unsere|zur|die|der)\s+rechnung", r"rechnung\s+vom",
    r"zu\s+rechnung", r"invoice", r"rechnung",
]

#: Labels that identify the party an agency/payment/court letter is about (supplier / creditor)
MANDATE_LABELS = [
    r"auftraggeber", r"mandant(?:in)?", r"gläubiger(?:in)?", r"antragsteller(?:in)?", r"im\s+auftrag\s+(?:von|der|des)",
    r"empfänger", r"zahlung\s+an", r"begünstigter", r"creditor", r"beneficiary", r"on\s+behalf\s+of", r"payee",
]

AMOUNT_LABELS: dict[str, dict[str, list[str]]] = {
    "invoice": {
        "gross": [r"rechnungsbetrag", r"gutschriftsbetrag", r"bruttobetrag", r"gesamtbetrag", r"endbetrag", r"zahlbetrag",
                  r"total\s+amount\s+due", r"amount\s+due", r"gesamtsumme", r"summe\s+brutto", r"gesamt", r"total"],
        "net": [r"nettobetrag", r"nettosumme", r"summe\s+netto", r"zwischensumme", r"net\s+amount", r"subtotal"],
        "vat": [r"(?:zzgl\.?|inkl\.?)?\s*\d{1,2}(?:[.,]\d+)?\s*%\s*(?:mwst\.?|ust\.?|mehrwertsteuer|umsatzsteuer|vat)",
                r"mwst\.?", r"mehrwertsteuer", r"umsatzsteuer", r"vat(?:\s*\d{1,2}\s*%)?"],
    },
    "dunning": {
        "principal": [r"offene[rn]?\s+hauptforderung", r"hauptforderung", r"ursprüngliche\s+forderung", r"offene\s+forderung",
                      r"forderungsbetrag", r"offener\s+betrag", r"rechnungsbetrag", r"outstanding\s+amount", r"open\s+amount",
                      r"principal", r"capital"],
        "fees": [r"mahngebühr(?:en)?", r"mahnkosten", r"mahnspesen", r"bearbeitungsgebühr", r"reminder\s+fee", r"dunning\s+fee"],
        "interest": [r"verzugszinsen", r"zinsforderung", r"zinsen", r"interest"],
        "flat_fee": [r"verzugspauschale", r"pauschalbetrag", r"pauschale", r"flat\s+fee"],
        "collection_costs": [r"inkassokosten", r"inkassogebühr(?:en)?", r"rechtsanwaltskosten", r"rechtsanwaltsvergütung",
                             r"anwaltskosten", r"auslagenpauschale", r"collection\s+costs?"],
        "court_costs": [r"gerichtskosten", r"gerichtsgebühr(?:en)?"],
        "remaining": [r"noch\s+zu\s+zahlen", r"restforderung", r"restbetrag", r"offener\s+gesamtbetrag", r"verbleibend(?:er\s+betrag)?",
                      r"zu\s+zahlender\s+betrag", r"remaining\s+balance"],
        "already_paid": [r"abzüglich\s+zahlung(?:en)?(?:\s+vom\s+[\d.]+)?", r"bereits\s+gezahlt", r"bereits\s+geleistete\s+zahlung(?:en)?",
                         r"zahlungseingang", r"bereits\s+beglichen", r"zahlung(?:en)?\s+erhalten", r"payment\s+received",
                         r"already\s+paid"],
        "total_claimed": [r"gesamtforderung", r"forderung\s+gesamt", r"summe\s+der\s+forderung", r"gesamtbetrag", r"gesamtsumme",
                          r"zahlbetrag", r"insgesamt", r"total\s+(?:claim|due|amount)", r"gesamt", r"total"],
    },
    "payment": {
        "payment_amount": [r"überweisungsbetrag", r"zahlungsbetrag", r"betrag", r"amount", r"zahlbetrag"],
    },
}

DATE_LABELS = {
    "document": [r"rechnungsdatum", r"briefdatum", r"ausstellungsdatum", r"belegdatum", r"invoice\s+date", r"mahndatum",
                 r"gutschriftsdatum", r"^[ \t]*date(?=[ \t]*:)", r"^[ \t]*datum(?=[ \t]*:)"],
    "payment": [r"ausführungsdatum", r"buchungsdatum", r"zahlungsdatum", r"wertstellung", r"valuta", r"booking\s+date",
                r"payment\s+date"],
    "due": [r"zahlbar\s+bis", r"fällig(?:keit(?:sdatum)?)?(?:\s+am)?", r"zahlungsziel", r"due\s+date", r"payment\s+due",
            r"pay\s+by", r"zahlen\s+sie\s+(?:bitte\s+)?(?:den\s+betrag\s+)?bis(?:\s+(?:spätestens|zum))?", r"bis\s+spätestens",
            r"zahlungsfrist", r"frist(?:\s+bis)?", r"zahlbar\s+(?:bis\s+)?zum", r"spätestens\s+bis", r"deadline"],
}

LEGAL_FORM_RE = re.compile(
    r"\b(?:gmbh|ag|kg|ug|ohg|gbr|mbh|e\.?\s?k\.?|ltd\.?|inc\.?|llc|se|kgaa|e\.?\s?v\.?|co\.|partner|inkasso|"
    r"amtsgericht|mahngericht|bank|versicherung)\b", re.I)


_SPLIT_PREFIXES = (
    "haupt|gesamt|mahn|verzugs|inkasso|rechnungs|netto|brutto|zahlungs|gerichts|rest|kunden|vorgangs|forderungs|"
    "mandats|debitoren|bestell|auftrags|bearbeitungs|end|zwischen|gutschrifts|ausführungs|buchungs|überweisungs"
)
_SPLIT_RE = re.compile(rf"(?<![a-zäöüß])({_SPLIT_PREFIXES})(?=[a-zäöüß])")


def tolerant(pattern: str) -> str:
    """Allow OCR to insert one space inside compound words (``Haupt forderung``)."""
    return _SPLIT_RE.sub(lambda m: m.group(1) + r"\s?", pattern)

