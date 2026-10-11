"""Invoice recognition across layouts and languages (Beleg, Facture, Fattura, Netto/Brutto, Summe/Total ...)."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from supplier_app.ai.classifier import KeywordClassifier
from supplier_app.ai.fields import AMOUNT_RE, RegexFieldExtractor
from supplier_app.ai.invoice_amounts import extract_invoice_amounts, plausible_rate
from supplier_app.ai.layout import header_value_pairs
from supplier_app.ai.validation import validate_fields
from supplier_app.ai.vocab import classify_amount_label
from supplier_app.models.enums import DocumentType as D
from supplier_app.util.dates import parse_any_date

FIX = Path(__file__).parent / "fixtures"
CLS, FX = KeywordClassifier(), RegexFieldExtractor()


def _cases() -> list[tuple[str, dict]]:
    out = []
    for name in ("cases", "cases2"):
        data = json.loads((FIX / "invoices" / f"{name}.json").read_text(encoding="utf-8"))
        out.extend((k, v) for k, v in data.items())
    return out


def _recognise(text: str) -> dict:
    cl = CLS.classify(text)
    f = FX.extract(text, cl)
    return {
        "doc_type": cl.doc_type.value, "number": str(f.invoice_numbers[0].value) if f.invoice_numbers else None,
        "date": f.document_date.value.isoformat() if f.document_date else None,
        "due": f.due_date.value.isoformat() if f.due_date else None,
        "net": f.amount("net"), "vat": f.amount("vat"), "gross": f.amount("gross"),
    }


@pytest.mark.parametrize(("name", "case"), _cases(), ids=[n for n, _ in _cases()])
def test_invoice_corpus(name: str, case: dict) -> None:
    got = _recognise(case["text"])
    wrong = {k: (want, got[k]) for k, want in case["expected"].items() if got[k] != want}
    assert not wrong, f"{name}: (expected, got) {wrong}"


def test_pdf_text_layers_with_table_layouts() -> None:
    import pymupdf

    expected = json.loads((FIX / "invoices_pdf" / "expected.json").read_text())
    for name, want in expected.items():
        with pymupdf.open(FIX / "invoices_pdf" / f"{name}.pdf") as doc:
            text = doc[0].get_text("text")  # exactly what the import reads
        got = _recognise(text)
        assert {k: got[k] for k in want} == want, name


def test_every_number_has_a_source_span_in_the_text() -> None:
    text = (FIX / "invoices" / "cases.json").read_text(encoding="utf-8")
    case = json.loads(text)["de_endsumme_zu_zahlen"]["text"]
    f = FX.extract(case, CLS.classify(case))
    for key, raw in (("net", "1.500,00"), ("vat", "285,00"), ("gross", "1.785,00")):
        start, end = f.amounts[key].span
        assert case[start:end] == raw
    start, end = f.invoice_numbers[0].span
    assert case[start:end] == "B/2024/310"


@pytest.mark.parametrize(("label", "kind"), [
    ("Netto", "net"), ("Nettobetrag", "net"), ("Summe netto", "net"), ("Zwischensumme (netto)", "net"), ("Warenwert netto", "net"),
    ("Montant HT", "net"), ("Imponibile", "net"), ("Base imponible", "net"), ("Total excl. VAT", "net"), ("Subtotal", "net"),
    ("MwSt 19 %", "vat"), ("zzgl. 19 % USt", "vat"), ("Umsatzsteuer", "vat"), ("TVA 20 %", "vat"), ("IVA 22%", "vat"),
    ("BTW 21%", "vat"), ("darin enthalten 19 % MwSt", "vat"), ("VAT", "vat"),
    ("Brutto", "gross"), ("Bruttobetrag", "gross"), ("Rechnungsbetrag", "gross"), ("Gesamtbetrag", "gross"), ("Endsumme", "gross"),
    ("Summe", "gross"), ("Total", "gross"), ("Gesamt", "gross"), ("Zu zahlen", "gross"), ("Total TTC", "gross"),
    ("Net à payer", "gross"), ("Totale documento", "gross"), ("Total factura", "gross"), ("Amount payable", "gross"),
    ("Gesamtbetrag inkl. 19 % MwSt.", "gross"), ("Total incl. VAT", "gross"), ("Rechnungs betrag", "gross"),
    ("Honorar gesamt", "gross"), ("Gutschriftsbetrag", "gross"),
])
def test_amount_label_vocabulary(label: str, kind: str) -> None:
    result = classify_amount_label(label)
    assert result is not None and result[0] == kind


@pytest.mark.parametrize("label", [
    "Toner schwarz 2", "Skonto 2 %", "Rabatt 10 %", "Einzelpreis", "Zahlbar innerhalb von 14 Tagen netto", "Anzahlung", "19%", "",
])
def test_non_total_labels_are_ignored(label: str) -> None:
    assert classify_amount_label(label) is None


def test_label_rates_are_returned() -> None:
    assert classify_amount_label("MwSt 7,5 %")[2] == "7.5"  # type: ignore[index]
    assert classify_amount_label("Netto")[2] is None  # type: ignore[index]


@pytest.mark.parametrize(("raw", "expected"), [
    ("15.03.2024", date(2024, 3, 15)), ("15.3.24", date(2024, 3, 15)), ("15/03/2024", date(2024, 3, 15)),
    ("03/15/2024", date(2024, 3, 15)), ("15-03-2024", date(2024, 3, 15)), ("2024-03-15", date(2024, 3, 15)),
    ("15 March 2024", date(2024, 3, 15)), ("March 15, 2024", date(2024, 3, 15)), ("15th March 2024", date(2024, 3, 15)),
    ("15 mars 2024", date(2024, 3, 15)), ("15 marzo 2024", date(2024, 3, 15)), ("5. Mär 2024", date(2024, 3, 5)),
    ("1 Dez. 2024", date(2024, 12, 1)), ("15.03 .2024", date(2024, 3, 15)), ("31 de marzo de 2024", date(2024, 3, 31)),
    ("30.02.2024", None), ("Montag", None), ("13/13/2024", None),
])
def test_date_notations(raw: str, expected: date | None) -> None:
    assert parse_any_date(raw) == expected


@pytest.mark.parametrize(("text", "values"), [
    ("1.234,56", ["1.234,56"]), ("1 234,56 EUR", ["1 234,56"]), ("1'234.56", ["1'234.56"]), ("1,234.56", ["1,234.56"]),
    ("12 500,00 und 19,00", ["12 500,00", "19,00"]), ("Menge 8 80,00", ["80,00"]), ("am 15.03.2024", []),
    ("RE-2024/001", []), ("19 %", []),
])
def test_amount_formats(text: str, values: list[str]) -> None:
    assert [m.group(1) for m in AMOUNT_RE.finditer(text)] == values


def test_net_vat_gross_are_cross_checked_and_derived() -> None:
    # only the gross amount and the rate are printed: net and VAT are calculated and flagged
    t = "Rechnung\nRechnungsnummer: R-1\nRechnungsdatum: 01.02.2024\nGesamtbetrag inkl. 19 % MwSt.: 119,00 EUR"
    cl = CLS.classify(t)
    f = FX.extract(t, cl)
    assert (f.amount("net"), f.amount("vat"), f.amount("gross")) == (10000, 1900, 11900)
    assert f.derived == {"net", "vat"} and f.amounts["net"].confidence < 0.75
    assert [i.code for i in validate_fields(f, cl, today=date(2024, 6, 1)) if i.code == "AMOUNT_DERIVED"]
    # net + vat -> gross
    r = extract_invoice_amounts("Netto 100,00\nMwSt 19 % 19,00")
    assert r.gross is not None and r.gross.value == 11900 and r.derived == {"gross"}
    # printed amounts that do not add up stay visible and are reported
    t2 = "Rechnung Nr. 7\nDatum 01.02.2024\nNetto 100,00\nMwSt 19 % 19,00\nBrutto 120,00"
    cl2 = CLS.classify(t2)
    f2 = FX.extract(t2, cl2)
    assert f2.amount("gross") == 12000
    assert "NET_VAT_GROSS" in {i.code for i in validate_fields(f2, cl2, today=date(2024, 6, 1))}


def test_triple_without_labels_is_found() -> None:
    t = "Rechnung Nr. 301\nDatum 14.03.2024\nTischlerarbeiten\n420,17   79,83   500,00\n"
    f = FX.extract(t, CLS.classify(t))
    assert (f.amount("net"), f.amount("vat"), f.amount("gross")) == (42017, 7983, 50000)


def test_plausible_vat_rates() -> None:
    assert plausible_rate(10000, 1900) == 19.0 and plausible_rate(10000, 700) == 7.0 and plausible_rate(10000, 1234) is None
    assert plausible_rate(0, 0) is None


def test_due_date_terms_and_skonto() -> None:
    base = "Rechnung Nr. 5\nRechnungsdatum: 10.01.2024\n"
    cases = {
        "Zahlungsziel: 30 Tage netto": date(2024, 2, 9), "Payment terms: Net 14": date(2024, 1, 24),
        "Zahlbar innerhalb von 10 Tagen": date(2024, 1, 20), "Paiement à 30 jours": date(2024, 2, 9),
        "Sofort fällig": date(2024, 1, 10), "Due on receipt": date(2024, 1, 10),
        "Bei Zahlung bis 20.01.2024 2 % Skonto.\nNetto bis 10.02.2024": date(2024, 2, 10),
        "Zahlbar bis 15.02.2024": date(2024, 2, 15), "Fälligkeit: 01.03.2024": date(2024, 3, 1),
        "Scadenza: 10/03/2024": date(2024, 3, 10), "Vencimiento 10/03/2024": date(2024, 3, 10),
        "Vervaldatum: 10-03-2024": date(2024, 3, 10),
    }
    for line, due in cases.items():
        t = base + "Netto 100,00\nMwSt 19 % 19,00\nBrutto 119,00\n" + line
        f = FX.extract(t, CLS.classify(t))
        assert f.due_date is not None and f.due_date.value == due, line
    only_skonto = base + "Brutto 119,00\nBei Zahlung bis 20.01.2024 gewähren wir 2 % Skonto."
    assert FX.extract(only_skonto, CLS.classify(only_skonto)).due_date is None


def test_service_period_is_not_the_invoice_date() -> None:
    t = "Rechnung Nr. 8\nLeistungsdatum: 15.01.2024\nRechnungsdatum: 20.01.2024\nBrutto 119,00"
    assert FX.extract(t, CLS.classify(t)).document_date.value == date(2024, 1, 20)
    t2 = "Rechnung Nr. 8\nLeistungszeitraum: 01.01.2024 - 31.01.2024\nBetrag brutto 119,00\nBerlin, 05.02.2024"
    assert FX.extract(t2, CLS.classify(t2)).document_date.value == date(2024, 2, 5)


def test_invoice_number_vocabulary_and_priority() -> None:
    for text, want in (
        ("Beleg-Nr. 2024-0815", "2024-0815"), ("Belegnummer: 99887", "99887"), ("Facture n° FA-0042", "FA-0042"),
        ("Fattura n. 2024/118", "2024/118"), ("Factura nº F-310", "F-310"), ("Factuurnummer: 24-1181", "24-1181"),
        ("Rg.-Nr.: 24-117", "24-117"), ("Invoice # 10045", "10045"), ("Document No. D-77", "D-77"),
        ("Dokumentnummer HN-09", "HN-09"), ("Rechnung Nr. 7", "7"), ("Rechnung 2024-0042", "2024-0042"),
    ):
        t = f"Rechnung\n{text}\nDatum: 01.02.2024\nBrutto 119,00"
        f = FX.extract(t, CLS.classify(t))
        assert f.invoice_numbers and f.invoice_numbers[0].value == want, text
    # the number of the credit note itself wins over the invoice it refers to
    t = "Gutschrift\nGutschrift-Nr. GS-10\nzu Rechnung RE-2024-881\nDatum 05.12.2024\nGutschriftsbetrag -119,00 €"
    f = FX.extract(t, CLS.classify(t))
    assert f.invoice_numbers[0].value == "GS-10" and {v.value for v in f.invoice_numbers} >= {"GS-10", "RE-2024-881"}
    assert f.amount("gross") == 11900  # credit amounts are positive


@pytest.mark.parametrize(("text", "expected"), [
    ("Beleg\nBeleg-Nr. 1\nNetto 10,00\nMwSt 19 % 1,90\nBrutto 11,90", D.INVOICE),
    ("Facture\nFacture n° 1\nTotal HT 10,00\nTVA 20 % 2,00\nTotal TTC 12,00", D.INVOICE),
    ("Fattura\nFattura n. 1\nImponibile 10,00\nIVA 22% 2,20\nTotale documento 12,20", D.INVOICE),
    ("Factuur\nFactuurnummer 1\nSubtotaal 10,00\nBTW 21% 2,10\nTotaal 12,10", D.INVOICE),
    ("Tax invoice\nInvoice number 1\nSubtotal 10.00\nVAT 20% 2.00\nTotal 12.00", D.INVOICE),
    ("Handwerkerrechnung\nBetrag netto 10,00\nMwSt 19 % 1,90\nBetrag brutto 11,90", D.INVOICE),
    ("Honorarnote\nHonorar netto 10,00\nUSt 19 % 1,90\nGesamt 11,90", D.INVOICE),
    ("Rechnung Nr. 55-1021\nDatum 01.02.2024", D.INVOICE),
    # not invoices
    ("Angebot\nAngebotsnummer 1\nNetto 10,00\nMwSt 19 % 1,90\nBrutto 11,90", D.OTHER),
    ("Lieferschein\nBeleg-Nr. 1\nWare wurde geliefert", D.DELIVERY_NOTE),
    ("Zahlungsbeleg\nÜberweisungsbetrag 10,00\nVerwendungszweck RE-1", D.BANK_STATEMENT),
    ("1. Mahnung\nRechnung Nr. 55 vom 10.01.2024\nOffene Hauptforderung 100,00\nNetto 84,03\nBrutto 100,00", D.FIRST_DUNNING),
    ("Gutschrift\nGutschrift-Nr. 1\nNetto 10,00\nMwSt 19 % 1,90\nBrutto 11,90", D.CREDIT_NOTE),
])
def test_invoice_document_type_vocabulary(text: str, expected: D) -> None:
    assert CLS.classify(text).doc_type == expected


def test_layout_pairs_header_rows_stacked_and_alternating() -> None:
    header = "Rechnungsnummer   Rechnungsdatum\nR-77              12.03.2024\n"
    assert [(p.label, p.value) for p in header_value_pairs(header)] == [("Rechnungsnummer", "R-77"), ("Rechnungsdatum", "12.03.2024")]
    stacked = "Rechnung\nRechnungsnummer\nRechnungsdatum\nR-77\n12.03.2024\n"
    pairs = {p.label: p.value for p in header_value_pairs(stacked)}
    assert pairs["Rechnungsnummer"] == "R-77" and pairs["Rechnungsdatum"] == "12.03.2024"
    alternating = "Rechnungsnummer\nR-77\nRechnungsdatum\n12.03.2024\n"
    assert {p.label: p.value for p in header_value_pairs(alternating)} == {"Rechnungsnummer": "R-77", "Rechnungsdatum": "12.03.2024"}
    t = header_value_pairs(alternating)[0]
    assert alternating[t.start : t.end] == "R-77"


def test_non_breaking_spaces_and_unicode_minus_do_not_break_amounts() -> None:
    t = "Rechnung Nr. 9\nDatum 01.02.2024\nNetto 1 250,00 €\nMwSt 19 % 237,50 €\nBrutto 1 487,50 €"
    f = FX.extract(t, CLS.classify(t))
    assert (f.amount("net"), f.amount("vat"), f.amount("gross")) == (125000, 23750, 148750)


def test_extraction_never_crashes_and_stays_fast_on_noisy_text() -> None:
    import random
    import time

    rng = random.Random(7)
    words = ["Rechnung", "Netto", "Brutto", "MwSt", "19 %", "Summe", "Total", "Beleg-Nr.", "Datum:", "Fällig", "1.234,56", "12,00",
             "15.03.2024", "EUR", "€", "Gesamt", "Skonto", "30 Tage", "Net 30", "IBAN DE89 3704 0044 0532 0130 00", "x", "-", "\t",
             "  ", "0,00", "99999999,99", "01.13.2024", "Zwischensumme", "Facture", "TTC", "HT", " "]
    start = time.time()
    for _ in range(60):
        lines = [" ".join(rng.choice(words) for _ in range(rng.randint(0, 8))) for _ in range(rng.randint(1, 40))]
        text = "\n".join(lines)
        cl = CLS.classify(text)
        f = FX.extract(text, cl)
        validate_fields(f, cl, today=date(2024, 6, 1))
        for key in ("net", "vat", "gross"):
            assert f.amount(key) is None or isinstance(f.amount(key), int)
    big = "Rechnung Nr. 1\nDatum 01.02.2024\n" + "Position 12 10,00 120,00\n" * 4000 + "Netto 100,00\nMwSt 19 % 19,00\nBrutto 119,00\n"
    FX.extract(big, CLS.classify(big))
    assert time.time() - start < 20


def test_user_vocabulary_extends_the_builtin_words(svc) -> None:
    from supplier_app.ai.pipeline import build_default_pipeline

    text = ("Lieferantenabrechnung\nVorgang-Nr. LA-4711\nAusgabedatum 01.03.2024\nWarenwert ohne Steuer 100,00\n"
            "Steueranteil 19,00\nZahlungsbetrag 119,00\nZahlung erbeten bis 15.03.2024")
    plain = build_default_pipeline(svc.repos, svc.ledger, svc.settings).analyze(text)
    assert plain.classification.doc_type != D.INVOICE or plain.fields.invoice_numbers == []
    svc.settings.set_custom_vocab({"invoice_title": ["Lieferantenabrechnung"], "invoice_number": ["Vorgang-Nr."],
                                   "net": ["Warenwert ohne Steuer"], "vat": ["Steueranteil"], "gross": ["Zahlungsbetrag"],
                                   "document_date": ["Ausgabedatum"], "due_date": ["Zahlung erbeten bis"]})
    assert svc.settings.custom_vocab()["net"] == ["Warenwert ohne Steuer"]
    f = build_default_pipeline(svc.repos, svc.ledger, svc.settings).analyze(text)
    assert f.classification.doc_type == D.INVOICE
    flds = f.fields
    assert flds.invoice_numbers[0].value == "LA-4711" and flds.document_date.value == date(2024, 3, 1)
    assert (flds.amount("net"), flds.amount("vat"), flds.amount("gross")) == (10000, 1900, 11900)
    assert flds.due_date.value == date(2024, 3, 15)
    svc.settings.set("custom_vocab", "{broken")
    assert svc.settings.custom_vocab() == {}
