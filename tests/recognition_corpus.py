"""Generator of realistic German business documents with known answers (supplier, sender, references).

The documents imitate what PDF text layers and OCR deliver: letterheads in different places, the recipient block of the
user's own hotel, small "Absenderzeile", footers with legal line / bank data, reference numbers inline, on the next line,
in header/value tables and stacked. Everything is generated from a seed, so tests are deterministic.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from datetime import date, timedelta

# -- master data -------------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class SupplierSpec:
    key: str
    name: str  # name in the master data
    street: str
    city: str
    zip: str
    iban: str
    vat: str
    tax: str
    email: str
    domain: str
    known_iban: bool = True  # is the IBAN already in the master data?
    known_vat: bool = False
    legal_variants: tuple[str, ...] = ()  # how the name may be printed (besides the master name)
    kind: str = "supplier"
    represents: str = ""  # agency: key of the supplier it collects for


SUPPLIERS: list[SupplierSpec] = [
    SupplierSpec("mueller", "Müller Bürobedarf GmbH", "Hauptstraße 12", "Berlin", "10115", "DE89370400440532013000", "DE123456789",
                 "27/123/45678", "info@mueller-buero.de", "mueller-buero.de", True, True,
                 ("MÜLLER BÜROBEDARF GMBH", "Müller Bürobedarf", "Mueller Buerobedarf GmbH", "Müller Bürobedarf GmbH - Ihr Partner für Büro")),
    SupplierSpec("gruenwald", "Grünwald Maschinenbau GmbH & Co. KG", "Industrieweg 4", "Stuttgart", "70173", "DE02120300000000202051",
                 "DE234567890", "93/456/12345", "rechnung@gruenwald-maschinen.de", "gruenwald-maschinen.de", True, False,
                 ("Grünwald Maschinenbau GmbH & Co. KG", "GRÜNWALD MASCHINENBAU GmbH & Co.KG", "Grünwald Maschinenbau", "Gruenwald Maschinenbau GmbH & Co. KG")),
    SupplierSpec("stadtwerke", "Stadtwerke Neustadt AG", "Energieallee 1", "Neustadt", "67433", "DE75512108001245126199", "DE345678901",
                 "44/222/33333", "service@stadtwerke-neustadt.de", "stadtwerke-neustadt.de", False, False,
                 ("Stadtwerke Neustadt AG", "STADTWERKE NEUSTADT AG", "Stadtwerke Neustadt")),
    SupplierSpec("schneider", "Immobilien Schneider e.K.", "Marktplatz 3", "Freiburg", "79098", "DE91100000000123456789", "DE456789012",
                 "12/345/67890", "vermietung@immobilien-schneider.de", "immobilien-schneider.de", True, False,
                 ("Immobilien Schneider e.K.", "Immobilien Schneider", "IMMOBILIEN SCHNEIDER E.K.", "Immobilienverwaltung Schneider e.K.")),
    SupplierSpec("hoffmann", "Bäckerei Hoffmann e.K.", "Brotgasse 7", "Hamburg", "20095", "DE12500105170648489890", "DE567890123",
                 "55/111/22222", "bestellung@baeckerei-hoffmann.de", "baeckerei-hoffmann.de", False, True,
                 ("Bäckerei Hoffmann e.K.", "Baeckerei Hoffmann e.K.", "BÄCKEREI HOFFMANN", "Bäckerei Hoffmann")),
    SupplierSpec("nordwind", "Nordwind Logistik AG", "Hafenstraße 99", "Bremen", "28195", "DE44500105175407324931", "DE678901234",
                 "60/333/44444", "buchhaltung@nordwind-logistik.de", "nordwind-logistik.de", True, True,
                 ("Nordwind Logistik AG", "NORDWIND LOGISTIK AG", "Nordwind Logistik")),
    SupplierSpec("alpha", "Alpha Werbetechnik UG (haftungsbeschränkt)", "Gewerbepark 5", "Köln", "50667", "DE27100777770209299700",
                 "DE789012345", "21/555/66666", "hallo@alpha-werbetechnik.de", "alpha-werbetechnik.de", False, False,
                 ("Alpha Werbetechnik UG (haftungsbeschränkt)", "Alpha Werbetechnik UG", "ALPHA WERBETECHNIK UG")),
    SupplierSpec("telekom", "TeleKom Business Services GmbH", "Netzstraße 20", "Frankfurt am Main", "60311", "DE60760300800123456789",
                 "DE890123456", "45/678/90123", "kundenservice@telekom-business.de", "telekom-business.de", False, False,
                 ("TeleKom Business Services GmbH", "TELEKOM BUSINESS SERVICES GMBH", "TeleKom Business Services")),
    SupplierSpec("weber", "Dr. Weber Steuerberatungsgesellschaft mbH", "Kanzleiplatz 2", "München", "80331", "DE33300209000012345678",
                 "DE901234567", "143/234/56789", "kanzlei@weber-steuer.de", "weber-steuer.de", True, False,
                 ("Dr. Weber Steuerberatungsgesellschaft mbH", "Dr. Weber Steuerberatung mbH", "DR. WEBER STEUERBERATUNGSGESELLSCHAFT MBH")),
    SupplierSpec("meier", "Meier & Söhne Getränkehandel OHG", "Brauereiweg 8", "Regensburg", "93047", "DE15701500001234567890", "DE012345678",
                 "244/111/55555", "bestellung@meier-getraenke.de", "meier-getraenke.de", True, False,
                 ("Meier & Söhne Getränkehandel OHG", "Meier und Söhne Getränkehandel OHG", "MEIER & SÖHNE GETRÄNKEHANDEL")),
    SupplierSpec("acme", "Acme Supplies Ltd", "12 Harbour Road", "Dublin", "D02 X285", "IE29AIBK93115212345678", "IE6388047V",
                 "", "billing@acme-supplies.ie", "acme-supplies.ie", False, False, ("Acme Supplies Ltd", "ACME SUPPLIES LTD", "Acme Supplies Limited")),
    SupplierSpec("gartenbau", "Gartenbau Lindner GmbH", "Parkallee 31", "Dresden", "01067", "DE98370400440532013001", "DE112233445",
                 "202/321/65432", "info@gartenbau-lindner.de", "gartenbau-lindner.de", False, False,
                 ("Gartenbau Lindner GmbH", "GARTENBAU LINDNER GMBH", "Gartenbau Lindner")),
]
AGENCIES: list[SupplierSpec] = [
    SupplierSpec("creditreform", "Creditreform Inkasso Südwest GmbH", "Inkassoplatz 1", "Karlsruhe", "76133", "DE55660501010012345678",
                 "DE555000111", "", "akte@inkasso-suedwest.de", "inkasso-suedwest.de", True, False,
                 ("Creditreform Inkasso Südwest GmbH", "CREDITREFORM INKASSO SÜDWEST GMBH", "Inkasso Südwest GmbH"), "collection_agency", "gruenwald"),
    SupplierSpec("brandt", "Rechtsanwälte Brandt & Partner mbB", "Kaiserstraße 40", "Mannheim", "68161", "DE66670500000011223344",
                 "DE555000222", "", "kanzlei@brandt-partner.de", "brandt-partner.de", True, False,
                 ("Rechtsanwälte Brandt & Partner mbB", "RECHTSANWÄLTE BRANDT & PARTNER MBB", "Brandt & Partner Rechtsanwälte mbB"),
                 "collection_agency", "nordwind"),
    SupplierSpec("euroforderung", "Euro-Forderungsmanagement AG", "Schuldnerweg 9", "Düsseldorf", "40213", "DE77300500000001234567",
                 "DE555000333", "", "service@euro-fm.de", "euro-fm.de", False, False,
                 ("Euro-Forderungsmanagement AG", "EURO-FORDERUNGSMANAGEMENT AG", "Euro Forderungsmanagement AG"), "collection_agency", "mueller"),
]
UNKNOWN_SUPPLIERS: list[SupplierSpec] = [
    SupplierSpec("u1", "Werner Elektrotechnik GmbH", "Stromweg 3", "Leipzig", "04109", "DE10100100100123456789", "DE221100334", "21/111/22222",
                 "mail@werner-elektro.de", "werner-elektro.de", legal_variants=("Werner Elektrotechnik GmbH", "WERNER ELEKTROTECHNIK GMBH")),
    SupplierSpec("u2", "Fischhandel Nordsee GmbH & Co. KG", "Kaikante 2", "Cuxhaven", "27472", "DE20200400600123456789", "DE445566778", "35/222/33333",
                 "info@fischhandel-nordsee.de", "fischhandel-nordsee.de", legal_variants=("Fischhandel Nordsee GmbH & Co. KG", "Fischhandel Nordsee GmbH & Co.KG")),
    SupplierSpec("u3", "Haustechnik Becker", "Wasserstraße 14", "Kassel", "34117", "DE30520503530123456789", "DE998877665", "26/333/44444",
                 "service@haustechnik-becker.de", "haustechnik-becker.de", legal_variants=("Haustechnik Becker",)),
    SupplierSpec("u4", "Wäscherei Klarweiß GmbH", "Sauberweg 6", "Hannover", "30159", "DE40250501800123456789", "DE334455667", "25/444/55555",
                 "kontakt@klarweiss.de", "klarweiss.de", legal_variants=("Wäscherei Klarweiß GmbH", "WÄSCHEREI KLARWEISS GMBH", "Waescherei Klarweiss GmbH")),
    SupplierSpec("u5", "Sonnenschein Versicherungsmakler AG", "Policenring 11", "Nürnberg", "90402", "DE50760100850123456789", "DE776655443", "241/555/66666",
                 "makler@sonnenschein-vm.de", "sonnenschein-vm.de", legal_variants=("Sonnenschein Versicherungsmakler AG",)),
]

OWN = {
    "company": "Seeblick Hotels GmbH",
    "hotels": ["Hotel Seeblick", "Hotel Bergfried", "Strandhotel Möwe"],
    "address": ("Seestraße 1", "23570", "Lübeck-Travemünde"),
}

def valid_iban_from(raw: str) -> str:
    """Replace the check digits of ``raw`` so that the IBAN is valid (the sample IBANs are invented)."""
    country, bban = raw[:2], raw[4:]
    digits = "".join(str(int(ch, 36)) for ch in bban + country + "00")
    check = 98 - int(digits) % 97
    return f"{country}{check:02d}{bban}"


def _with_valid_ibans(specs: list[SupplierSpec]) -> list[SupplierSpec]:
    from dataclasses import replace

    return [replace(s, iban=valid_iban_from(s.iban)) for s in specs]


SUPPLIERS = _with_valid_ibans(SUPPLIERS)
AGENCIES = _with_valid_ibans(AGENCIES)
UNKNOWN_SUPPLIERS = _with_valid_ibans(UNKNOWN_SUPPLIERS)

# -- document model -----------------------------------------------------------------------------------------------------


@dataclass
class Case:
    name: str
    text: str
    kind: str  # 'invoice' | 'reminder' | 'dunning' | 'collection'
    supplier_key: str  # whose ledger the document belongs to (expected supplier)
    author_key: str  # who wrote it (agency for collection letters, else = supplier_key)
    known: bool  # is the author in the master data?
    author_name: str  # printed name of the author (for new suppliers: the expected new name)
    refs: dict[str, str] = field(default_factory=dict)  # ref_type -> expected raw value (compared normalised)


def master_names(specs: list[SupplierSpec]) -> dict[str, SupplierSpec]:
    return {s.key: s for s in specs}


# -- building blocks --------------------------------------------------------------------------------------------------


def _phone(rng: random.Random) -> str:
    return f"0{rng.randint(30, 899)} {rng.randint(100000, 999999)}"


def _recipient(rng: random.Random) -> list[str]:
    hotel = rng.choice(OWN["hotels"])
    street, zip_, city = OWN["address"]
    first = rng.choice([[OWN["company"], hotel], [hotel], [OWN["company"]], [OWN["company"], "Buchhaltung"]])
    return [*first, street, f"{zip_} {city}"]


def _letterhead(rng: random.Random, s: SupplierSpec, printed: str, style: int, recipient: list[str]) -> list[str]:
    addr = f"{s.street}, {s.zip} {s.city}"
    contact = f"Tel. {_phone(rng)} · {s.email}"
    if style == 0:
        return [printed, addr, contact, "", *recipient, ""]
    if style == 1:  # no logo text: only the small "Absenderzeile" above the recipient
        return [f"Internet: www.{s.domain}   E-Mail: {s.email}", f"Telefon: {_phone(rng)}", "",
                f"{printed} · {s.street} · {s.zip} {s.city}", *recipient, ""]
    if style == 2:  # recipient first (text order of the PDF), letterhead afterwards
        return [*recipient, "", printed, s.street, f"{s.zip} {s.city}", contact, ""]
    if style == 3:  # name only in the footer: header has only the recipient
        return [*recipient, ""]
    if style == 4:  # slogan under a capitalised name
        return [printed.upper() if rng.random() < 0.5 else printed, "Ihr zuverlässiger Partner seit 1985", addr, "", *recipient, ""]
    return [f"{printed}                         Seite 1 von 2", f"{s.street}  ·  {s.zip} {s.city}", "", *recipient, ""]


def _footer(rng: random.Random, s: SupplierSpec, printed: str, style: int) -> list[str]:
    bank = rng.choice(["Sparkasse", "Volksbank", "Commerzbank", "Deutsche Bank"])
    iban = " ".join(s.iban[i:i + 4] for i in range(0, len(s.iban), 4))
    if style == 0:
        lines = [f"{printed} | Geschäftsführer: Max Muster | Amtsgericht {s.city} HRB {rng.randint(1000, 99999)}",
                 f"USt-IdNr.: {s.vat} | Steuernummer: {s.tax}" if s.tax else f"VAT No.: {s.vat}",
                 f"Bankverbindung: {bank} {s.city} · IBAN {iban} · BIC TESTDEFFXXX"]
        return ["", *lines]
    if style == 1:
        return ["", f"Bankverbindung: {bank}", f"IBAN: {iban}", "BIC: TESTDEFFXXX", f"USt-IdNr. {s.vat}"]
    if style == 2:
        return ["", f"{printed}  www.{s.domain}", f"IBAN {iban}"]
    return []


def _fmt(cents: int) -> str:
    euros, rest = divmod(cents, 100)
    return f"{euros:,}".replace(",", ".") + f",{rest:02d}"


def _ref_block(rng: random.Random, refs: list[tuple[str, str, str]], layout: int) -> list[str]:
    """refs: (type, label, value); layout 0 inline, 1 value on the next line, 2 header row over value row, 3 two per line."""
    if layout == 0:
        return [f"{label}: {value}" for _t, label, value in refs]
    if layout == 1:
        out: list[str] = []
        for _t, label, value in refs:
            out += [f"{label}:", value]
        return out
    if layout == 2:
        out = []
        for i in range(0, len(refs), 3):
            chunk = refs[i:i + 3]
            out.append("   ".join(label for _t, label, _v in chunk))
            out.append("   ".join(value for _t, _l, value in chunk))
        return out
    out = []
    for i in range(0, len(refs), 2):
        chunk = refs[i:i + 2]
        out.append("      ".join(f"{label}: {value}" for _t, label, value in chunk))
    return out


# -- documents ---------------------------------------------------------------------------------------------------------

_CUSTOMER_LABELS = ["Kundennummer", "Kunden-Nr.", "Ihre Kundennummer", "Kd.-Nr.", "Kundennr."]
_CONTRACT_LABELS = ["Vertragsnummer", "Vertrags-Nr.", "Vertragskonto", "Mietvertrag Nr."]
_LETTER_LABELS = ["Schreibennummer", "Schreiben-Nr.", "Unser Zeichen"]


def make_invoice(rng: random.Random, supplier: SupplierSpec, known: bool, idx: int) -> Case:
    printed = rng.choice(supplier.legal_variants or (supplier.name,))
    if known and rng.random() < 0.5:
        printed = supplier.name
    style = rng.choice([0, 0, 1, 1, 2, 3, 4, 5])
    number = rng.choice([f"RE-{rng.randint(2023, 2025)}-{rng.randint(100, 9999)}", f"{rng.randint(100000, 999999)}",
                         f"R{rng.randint(10, 99)}/{rng.randint(1000, 9999)}", f"{rng.randint(2023, 2025)}{rng.randint(1000, 99999)}"])
    cust = f"{rng.randint(10000, 99999)}" if rng.random() < 0.5 else f"KD-{rng.randint(1000, 99999)}"
    refs: list[tuple[str, str, str]] = [("customer_number", rng.choice(_CUSTOMER_LABELS), cust)]
    expected = {"customer_number": cust}
    if supplier.key in ("stadtwerke", "telekom", "schneider", "alpha") or rng.random() < 0.25:
        contract = rng.choice([f"V-{rng.randint(100000, 999999)}", f"{rng.randint(1000000, 9999999)}", f"VT/{rng.randint(10, 99)}/{rng.randint(100, 999)}"])
        refs.append(("contract_number", rng.choice(_CONTRACT_LABELS), contract))
        expected["contract_number"] = contract
    if rng.random() < 0.3:
        order = f"B-{rng.randint(10000, 99999)}"
        refs.append(("order_number", rng.choice(["Bestellnummer", "Ihre Bestellung Nr.", "Auftragsnummer"]), order))
        expected["order_number"] = order
    layout = rng.choice([0, 0, 1, 2, 3])
    d = date(2025, 1, 1) + timedelta(days=rng.randint(0, 400))
    net = rng.randint(5000, 500000)
    vat = round(net * 0.19)
    recipient = _recipient(rng)
    lines = _letterhead(rng, supplier, printed, style, recipient)
    lines += ["Rechnung", ""]
    lines += [f"Rechnungsnummer: {number}", f"Rechnungsdatum: {d.strftime('%d.%m.%Y')}"] if rng.random() < 0.7 else \
        ["Rechnungsnummer   Rechnungsdatum", f"{number}   {d.strftime('%d.%m.%Y')}"]
    lines += _ref_block(rng, refs, layout)
    lines += ["", "Pos.  Beschreibung            Menge   Preis", f"1     Leistung nach Vereinbarung  1   {_fmt(net)} €", "",
              f"Nettobetrag:   {_fmt(net)} €", f"zzgl. 19 % MwSt:   {_fmt(vat)} €", f"Gesamtbetrag:   {_fmt(net + vat)} €",
              "", "Zahlbar innerhalb von 14 Tagen ohne Abzug."]
    lines += _footer(rng, supplier, printed, rng.choice([0, 0, 1, 2]) if style != 3 else rng.choice([0, 2]))
    return Case(f"invoice-{supplier.key}-{idx}", "\n".join(lines), "invoice", supplier.key, supplier.key, known, printed,
                {**expected, "invoice_number": number})


def make_dunning(rng: random.Random, supplier: SupplierSpec, known: bool, idx: int) -> Case:
    printed = rng.choice(supplier.legal_variants or (supplier.name,))
    style = rng.choice([0, 1, 2, 4, 5])
    title = rng.choice(["Zahlungserinnerung", "1. Mahnung", "2. Mahnung", "Letzte Mahnung"])
    number = f"RE-{rng.randint(2023, 2025)}-{rng.randint(100, 9999)}"
    cust = f"{rng.randint(10000, 99999)}"
    letter = f"M-{rng.randint(10000, 99999)}"
    refs = [("customer_number", rng.choice(_CUSTOMER_LABELS), cust), ("letter_number", rng.choice(_LETTER_LABELS), letter)]
    expected = {"customer_number": cust, "letter_number": letter}
    d = date(2025, 3, 1) + timedelta(days=rng.randint(0, 300))
    recipient = _recipient(rng)
    lines = _letterhead(rng, supplier, printed, style, recipient)
    lines += [title, f"Datum: {d.strftime('%d.%m.%Y')}", ""]
    lines += _ref_block(rng, refs, rng.choice([0, 0, 1, 3]))
    lines += ["", f"zu unserer Rechnung {number} vom {(d - timedelta(days=45)).strftime('%d.%m.%Y')}",
              f"Hauptforderung: {_fmt(rng.randint(10000, 900000))} €", "Mahngebühr: 5,00 €", "",
              f"Bitte zahlen Sie bis zum {(d + timedelta(days=10)).strftime('%d.%m.%Y')}."]
    lines += _footer(rng, supplier, printed, rng.choice([0, 1, 2]))
    kind = "reminder" if title == "Zahlungserinnerung" else "dunning"
    return Case(f"dunning-{supplier.key}-{idx}", "\n".join(lines), kind, supplier.key, supplier.key, known, printed,
                {**expected, "invoice_number": number})


def make_collection(rng: random.Random, agency: SupplierSpec, creditor: SupplierSpec, known: bool, creditor_known: bool,
                    idx: int) -> Case:
    printed = rng.choice(agency.legal_variants or (agency.name,))
    style = rng.choice([0, 1, 2, 4])
    number = f"RE-{rng.randint(2023, 2025)}-{rng.randint(100, 9999)}"
    file_no = rng.choice([f"INK-{rng.randint(2023, 2025)}-{rng.randint(10000, 99999)}", f"{rng.randint(100, 999)}/{rng.randint(23, 25)}",
                          f"AZ {rng.randint(10, 99)}-{rng.randint(1000, 9999)}"])
    claim = f"F{rng.randint(100000, 999999)}"
    cust = f"{rng.randint(10000, 99999)}"
    mandate_label = rng.choice(["Mandant", "Gläubiger", "im Auftrag von", "Auftraggeber"])
    creditor_printed = creditor.name
    d = date(2025, 5, 1) + timedelta(days=rng.randint(0, 300))
    recipient = _recipient(rng)
    lines = _letterhead(rng, agency, printed, style, recipient)
    lines += ["Inkassoschreiben", f"Datum: {d.strftime('%d.%m.%Y')}", "",
              f"Aktenzeichen: {file_no}", f"Forderungsnummer: {claim}", f"{mandate_label}: {creditor_printed}",
              f"Kundennummer beim Gläubiger: {cust}", "",
              f"wir vertreten die Interessen von {creditor_printed}. Offen ist die Rechnung {number}.",
              f"Hauptforderung: {_fmt(rng.randint(50000, 900000))} €", "Inkassokosten: 49,00 €", "",
              f"Zahlen Sie bis zum {(d + timedelta(days=7)).strftime('%d.%m.%Y')}."]
    lines += _footer(rng, agency, printed, rng.choice([0, 1, 2]))
    return Case(f"collection-{agency.key}-{creditor.key}-{idx}", "\n".join(lines), "collection", creditor.key, agency.key, known,
                printed, {"file_number": file_no, "claim_number": claim, "customer_number": cust, "invoice_number": number})


def build_corpus(seed: int = 7, per_supplier: int = 3, noise: float = 0.0) -> list[Case]:
    """Known suppliers (several layouts each), unknown suppliers, reminders and collection letters.

    ``noise`` > 0 damages the printed names like bad OCR does (with ``populate_master(hard=True)`` the master names also
    differ from the printed ones and no IBAN/VAT is known: only the names can identify the supplier)."""
    rng = random.Random(seed)
    cases = _build(rng, per_supplier)
    if noise:
        noisy_rng = random.Random(seed + 1)
        for c in cases:
            c.text = ocr_noise(noisy_rng, c.text, c.author_name, noise)
    return cases


def _build(rng: random.Random, per_supplier: int) -> list[Case]:
    cases: list[Case] = []
    for s in SUPPLIERS:
        for i in range(per_supplier):
            cases.append(make_invoice(rng, s, True, i))
        cases.append(make_dunning(rng, s, True, 0))
    for s in UNKNOWN_SUPPLIERS:
        for i in range(2):
            cases.append(make_invoice(rng, s, False, i))
        cases.append(make_dunning(rng, s, False, 0))
    for agency in AGENCIES:
        creditor = master_names(SUPPLIERS)[agency.represents]
        for i in range(3):
            cases.append(make_collection(rng, agency, creditor, True, True, i))
    return cases


# -- evaluation ----------------------------------------------------------------------------------------------------------


def populate_own(svc) -> None:
    """The user's own company with its hotels (they are the recipients of all documents)."""
    company = svc.organization.create_company(OWN["company"])
    for hotel in OWN["hotels"]:
        svc.organization.create_hotel(company.id, hotel)


#: how a user may have typed the supplier into the master data (shorter / different word order than the legal name)
HARD_MASTER_NAMES = {
    "mueller": "Müller Büro", "gruenwald": "Grünwald Maschinenbau", "stadtwerke": "Stadtwerke Neustadt",
    "schneider": "Schneider Immobilien", "hoffmann": "Hoffmann Bäckerei", "nordwind": "Nordwind", "alpha": "Alpha Werbetechnik",
    "telekom": "TeleKom Business", "weber": "Weber Steuerberatung", "meier": "Meier Getränke", "acme": "Acme Supplies",
    "gartenbau": "Lindner Gartenbau",
}
_OCR_SWAPS = {"ü": "u", "ö": "o", "ä": "a", "l": "1", "o": "0", "m": "rn", "ß": "B", "e": "c", "i": "l", "n": "r"}


def ocr_noise(rng: random.Random, text: str, name: str, rate: float = 0.06) -> str:
    """Typical OCR damage in the lines that contain the printed name (the numbers stay readable)."""
    out = []
    for line in text.split("\n"):
        if name.lower()[:8] in line.lower():
            chars = []
            for ch in line:
                if ch.lower() in _OCR_SWAPS and rng.random() < rate:
                    sub = _OCR_SWAPS[ch.lower()]
                    chars.append(sub.upper() if ch.isupper() else sub)
                else:
                    chars.append(ch)
            line = "".join(chars)
        out.append(line)
    return "\n".join(out)


def populate_master(svc, hard: bool = False) -> dict[str, int]:
    """Create the master data (suppliers with or without IBAN/VAT, agencies) and return key -> party id."""
    from supplier_app.models.entities import Party
    from supplier_app.models.enums import PartyRole

    ids: dict[str, int] = {}
    for s in SUPPLIERS:
        name = HARD_MASTER_NAMES[s.key] if hard else s.name
        p = svc.suppliers.create(Party(name=name, role=PartyRole.SUPPLIER, ibans=[s.iban] if s.known_iban and not hard else [],
                                       vat_id=s.vat if s.known_vat and not hard else ""))
        ids[s.key] = p.id
    for a in AGENCIES:
        p = svc.suppliers.create(Party(name=a.name, role=PartyRole.COLLECTION_AGENCY, ibans=[a.iban] if a.known_iban else [],
                                       represents_supplier_id=ids[a.represents]))
        ids[a.key] = p.id
    return ids


@dataclass
class Evaluation:
    supplier_hits: int = 0
    supplier_total: int = 0
    supplier_top3_hits: int = 0
    wrong_supplier: list[str] = field(default_factory=list)
    new_name_hits: int = 0
    new_name_total: int = 0
    wrong_names: list[str] = field(default_factory=list)
    sender_hits: int = 0
    sender_total: int = 0
    ref_hits: dict[str, int] = field(default_factory=dict)
    ref_total: dict[str, int] = field(default_factory=dict)
    ref_misses: list[str] = field(default_factory=list)
    ref_wrong: int = 0  # extracted reference values that are not expected at all
    ref_extracted: int = 0

    def summary(self) -> str:
        pct = lambda a, b: f"{100 * a / b:5.1f} % ({a}/{b})" if b else "n/a"  # noqa: E731
        lines = [f"known supplier correct : {pct(self.supplier_hits, self.supplier_total)}",
                 f"known supplier in top 3: {pct(self.supplier_top3_hits, self.supplier_total)}",
                 f"author (sender) correct: {pct(self.sender_hits, self.sender_total)}",
                 f"new supplier name      : {pct(self.new_name_hits, self.new_name_total)}"]
        for t in sorted(self.ref_total):
            lines.append(f"reference {t:16s}: {pct(self.ref_hits.get(t, 0), self.ref_total[t])}")
        lines.append(f"reference precision    : {pct(self.ref_extracted - self.ref_wrong, self.ref_extracted)}")
        return "\n".join(lines)


def evaluate(svc, cases: list[Case], ids: dict[str, int], analyze=None) -> Evaluation:
    from supplier_app.ai.names import similarity
    from supplier_app.util.normalize import normalize_name, normalize_reference

    analyze = analyze or svc.ingest.pipeline().analyze
    ev = Evaluation()
    for case in cases:
        a = analyze(case.text)
        sender = a.sender
        if case.known:
            ev.sender_total += 1
            if sender is not None and sender.party_id == ids[case.author_key]:
                ev.sender_hits += 1
            ev.supplier_total += 1
            if sender is not None and sender.supplier_id == ids[case.supplier_key]:
                ev.supplier_hits += 1
            else:
                ev.wrong_supplier.append(f"{case.name}: got {sender.supplier_id if sender else None} / {sender.name if sender else '-'} "
                                         f"(want {case.supplier_key}) reason {sender.reason if sender else ''}")
            top = [c.party_id for c in getattr(a, "supplier_candidates", [])[:3]] if hasattr(a, "supplier_candidates") else []
            if (sender is not None and sender.supplier_id == ids[case.supplier_key]) or ids[case.supplier_key] in top:
                ev.supplier_top3_hits += 1
        else:
            ev.new_name_total += 1
            name = sender.name if sender and sender.party_id is None else ""
            if name and (normalize_name(name) == normalize_name(case.author_name) or similarity(name, case.author_name) >= 0.8):
                ev.new_name_hits += 1
            else:
                ev.wrong_names.append(f"{case.name}: got {name!r} (want {case.author_name!r}) / sender {sender}")
        extracted: list[tuple[str, str]] = [(r.ref_type.value, normalize_reference(r.raw)) for r in a.fields.references]
        extracted += [("invoice_number", normalize_reference(str(v.value))) for v in a.fields.invoice_numbers]
        ev.ref_extracted += len({v for _t, v in extracted})
        expected_values = {normalize_reference(v) for v in case.refs.values()}
        ev.ref_wrong += len({v for _t, v in extracted if v not in expected_values})
        for rtype, value in case.refs.items():
            ev.ref_total[rtype] = ev.ref_total.get(rtype, 0) + 1
            if (rtype, normalize_reference(value)) in extracted:
                ev.ref_hits[rtype] = ev.ref_hits.get(rtype, 0) + 1
            else:
                got = [x for x in extracted if x[0] == rtype]
                ev.ref_misses.append(f"{case.name}: {rtype} want {value!r} got {got}")
    return ev
