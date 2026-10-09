from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from supplier_app.ai.classifier import KeywordClassifier
from supplier_app.ai.fields import AMOUNT_RE, RegexFieldExtractor
from supplier_app.ai.references import LabelledReferenceExtractor
from supplier_app.ai.result_types import Classification, ExtractedFields, FieldValue
from supplier_app.ai.validation import validate_fields
from supplier_app.models.enums import DocumentType as D
from supplier_app.models.enums import ReferenceType as R
from tests.helpers import make_scenario

TEXTS = Path(__file__).parent / "fixtures" / "texts"
CLS = KeywordClassifier()
FX = RegexFieldExtractor()


def text(name: str) -> str:
    return (TEXTS / f"{name}.txt").read_text(encoding="utf-8")


@pytest.mark.parametrize(("name", "expected"), [
    ("invoice_RE-2024-001", D.INVOICE), ("invoice_en", D.INVOICE), ("dunning1_mueller", D.FIRST_DUNNING),
    ("dunning2_inkasso", D.SECOND_DUNNING), ("collection_letter", D.COLLECTION_LETTER), ("court_order", D.COURT_ORDER),
    ("credit_note", D.CREDIT_NOTE), ("delivery_note", D.DELIVERY_NOTE), ("payment_confirmation", D.BANK_STATEMENT),
    ("reminder_en", D.PAYMENT_REMINDER), ("empty", D.OTHER),
])
def test_classification_of_fixtures(name: str, expected: D) -> None:
    result = CLS.classify(text(name))
    assert result.doc_type == expected
    if expected != D.OTHER:
        assert result.confidence >= 0.7 and result.reasons


@pytest.mark.parametrize(("snippet", "expected"), [
    ("Zahlungserinnerung\nSehr geehrte Damen und Herren, möglicherweise übersehen", D.PAYMENT_REMINDER),
    ("3. Mahnung\nLetzte Frist", D.FINAL_DUNNING), ("Letzte Mahnung vor Inkasso", D.FINAL_DUNNING),
    ("Final notice\nfinal demand for payment", D.FINAL_DUNNING), ("Second reminder\nsecond dunning", D.SECOND_DUNNING),
    ("Mahnung\nMahngebühr 5,00", D.FIRST_DUNNING), ("Kontoauszug\nBuchungsdatum 01.01.2024", D.BANK_STATEMENT),
    ("Bank statement\nPayment confirmation", D.BANK_STATEMENT), ("Credit note CN-1", D.CREDIT_NOTE),
    ("Hallo Welt, kein Schlüsselwort", D.OTHER), ("Vollstreckungsbescheid", D.COURT_ORDER),
])
def test_classification_snippets(snippet: str, expected: D) -> None:
    assert CLS.classify(snippet).doc_type == expected


def test_numbered_dunning_with_fee_line_of_other_level_is_not_confused() -> None:
    t = "Inkasso Partner GmbH\n2. Mahnung\nMahngebühr 1. Mahnung: 5,00 €\nMahngebühr 2. Mahnung: 10,00 €"
    assert CLS.classify(t).doc_type == D.SECOND_DUNNING


def test_amount_regex_handles_german_and_english_and_ignores_dates() -> None:
    assert [m.group(1) for m in AMOUNT_RE.finditer("1.234,56 und 12,00 und 1,190.00 und 7.50")] == [
        "1.234,56", "12,00", "1,190.00", "7.50"]
    assert AMOUNT_RE.search("am 20.03.2024 und 10.01.2024") is None
    assert AMOUNT_RE.search("Rechnung 2024") is None


def test_invoice_fields() -> None:
    t = text("invoice_RE-2024-001")
    f = FX.extract(t, CLS.classify(t))
    assert f.sender_name.value == "Müller Bürobedarf GmbH"
    assert f.document_date.value == date(2024, 1, 10) and f.due_date.value == date(2024, 2, 9)
    assert (f.amount("net"), f.amount("vat"), f.amount("gross")) == (84034, 15966, 100000)
    assert f.invoice_numbers[0].value == "RE-2024/001" and f.invoice_numbers[0].confidence > 0.9
    assert [i.value for i in f.ibans] == ["DE89370400440532013000"] and f.ibans[0].confidence > 0.9
    assert f.vat_ids[0].value == "DE123456789" and str(f.vat_rate.value) == "19" and f.currency.value == "EUR"
    refs = {(r.ref_type, r.raw) for r in f.references}
    assert (R.CUSTOMER_NUMBER, "K-4711") in refs and (R.ORDER_NUMBER, "B-2023-889") in refs
    # source spans point to the printed text
    start, end = f.amounts["gross"].span
    assert t[start:end] == "1.000,00"
    start, end = f.invoice_numbers[0].span
    assert t[start:end] == "RE-2024/001"
    assert not validate_fields(f, CLS.classify(t), today=date(2024, 6, 1))


def test_english_invoice_fields() -> None:
    t = text("invoice_en")
    f = FX.extract(t, CLS.classify(t))
    assert f.invoice_numbers[0].value == "INV-2024-17" and f.amount("gross") == 119000 and f.amount("net") == 100000
    assert f.document_date.value == date(2024, 3, 12) and f.due_date.value == date(2024, 4, 11)


def test_dunning_fields_sum_fee_lines() -> None:
    t = text("dunning2_inkasso")
    f = FX.extract(t, CLS.classify(t))
    assert f.amount("principal") == 100000 and f.amount("fees") == 1500 and f.amount("total_claimed") == 101500
    assert len(f.fee_items) == 2 and f.deadline.value == date(2024, 4, 3) and f.due_date is None
    refs = {(r.ref_type, r.raw) for r in f.references}
    assert (R.FILE_NUMBER, "INK-2024-77881") in refs and (R.CLAIM_NUMBER, "F-99120") in refs
    assert f.referenced_invoice_dates[0].value == date(2024, 1, 10)


def test_collection_letter_fields_and_validation() -> None:
    t = text("collection_letter")
    cls = CLS.classify(t)
    f = FX.extract(t, cls)
    assert {k: v.value for k, v in f.amounts.items()} == {
        "principal": 100000, "fees": 1500, "interest": 2740, "flat_fee": 4000, "collection_costs": 12050,
        "total_claimed": 120290, "already_paid": 40000, "remaining": 80290}
    assert (R.MANDATE_NUMBER, "M-5521") in {(r.ref_type, r.raw) for r in f.references}
    assert not [i for i in validate_fields(f, cls, today=date(2024, 6, 1))]


def test_ocr_style_split_words_are_tolerated() -> None:
    t = ("2. Mahnung\nDatum: 20.03.2024\nHaupt forderung: 1.000,00 €\nMahn gebühr: 10,00 €\n"
         "Gesamt forderung: 1.010,00 €\nZahibar bis 03.04.2024")
    f = FX.extract(t, CLS.classify(t))
    assert f.amount("principal") == 100000 and f.amount("fees") == 1000 and f.amount("total_claimed") == 101000


def test_amount_on_next_line_and_relative_due_date() -> None:
    t = "Rechnung\nRechnungsdatum: 01.02.2024\nRechnungsbetrag:\n119,00 €\nZahlbar innerhalb von 14 Tagen netto"
    f = FX.extract(t, CLS.classify(t))
    assert f.amount("gross") == 11900 and f.due_date.value == date(2024, 2, 15)


def test_long_date_format_and_date_fallback() -> None:
    t = "Mahnung\nBerlin, den 5. März 2024\nOffene Hauptforderung 100,00 €"
    f = FX.extract(t, CLS.classify(t))
    assert f.document_date.value == date(2024, 3, 5) and f.document_date.confidence < 0.9


def test_reference_extractor_labels_and_user_keywords() -> None:
    ex = LabelledReferenceExtractor({"file_number": ["Unser Zeichen Inkasso"], "bogus": ["x"]})
    t = ("Bearbeitungsnummer: 4711/A\nAktenzeichen INK-1/24 vom 01.02.2024\nAz. 55/24\nVorgangsnummer: V-88\n"
         "Debitorennummer 7788\nMandatsnummer: M 5\nBitte geben Sie das Aktenzeichen an.\nKundennummer: 12,50\n"
         "Unser Zeichen Inkasso: IK-77\nZahlungsreferenz: ZR 2024 1")
    got = {(r.ref_type, r.raw) for r in ex.extract(t)}
    assert (R.PROCESSING_NUMBER, "4711/A") in got and (R.FILE_NUMBER, "INK-1/24") in got
    assert (R.FILE_NUMBER, "Az 55/24".replace("Az ", "")) in got or (R.FILE_NUMBER, "55/24") in got
    assert (R.CASE_NUMBER, "V-88") in got and (R.DEBTOR_NUMBER, "7788") in got
    assert (R.FILE_NUMBER, "IK-77") in got
    assert not any(r[0] == R.CUSTOMER_NUMBER for r in got)  # '12,50' is an amount
    assert not any("an" == r[1] for r in got)


def test_validation_issues() -> None:
    cls = Classification(D.INVOICE, 1.0)
    f = ExtractedFields()
    f.amounts = {"net": FieldValue(10000, 1), "vat": FieldValue(1900, 1), "gross": FieldValue(12000, 1)}
    f.vat_rate = FieldValue("19", 1)
    f.document_date = FieldValue(date(2100, 1, 1), 1)
    f.due_date = FieldValue(date(2099, 1, 1), 1)
    f.ibans = [FieldValue("DE00123456789012345678", 0.3, None, "DE00 1234")]
    f.vat_ids = [FieldValue("DE12", 0.3, None, "DE12")]
    codes = {i.code for i in validate_fields(f, cls, today=date(2024, 1, 1))}
    assert {"NET_VAT_GROSS", "MISSING_NUMBER", "DATE_FUTURE", "DUE_BEFORE_DATE", "IBAN", "VAT_ID"} <= codes
    f2 = ExtractedFields()
    f2.amounts = {"net": FieldValue(10000, 1), "vat": FieldValue(500, 1), "gross": FieldValue(10500, 1)}
    f2.vat_rate = FieldValue("19", 1)
    assert "VAT_RATE" in {i.code for i in validate_fields(f2, cls)}
    dun = Classification(D.FIRST_DUNNING, 1.0)
    f3 = ExtractedFields()
    f3.amounts = {"principal": FieldValue(100000, 1), "fees": FieldValue(500, 1), "total_claimed": FieldValue(101500, 1),
                  "already_paid": FieldValue(100, 1), "remaining": FieldValue(5, 1)}
    f3.document_date = FieldValue(date(2024, 3, 1), 1)
    f3.deadline = FieldValue(date(2024, 2, 1), 1)
    codes = {i.code for i in validate_fields(f3, dun)}
    assert {"CLAIM_SUM", "REMAINING_SUM", "DEADLINE_BEFORE_DATE"} <= codes
    assert "MISSING_AMOUNT" in {i.code for i in validate_fields(ExtractedFields(), dun)}
    assert "MISSING_DATE" in {i.code for i in validate_fields(ExtractedFields(), dun)}
    assert "MISSING_AMOUNT" in {i.code for i in validate_fields(ExtractedFields(), Classification(D.BANK_STATEMENT, 1))}
    old = ExtractedFields()
    old.document_date = FieldValue(date(1980, 1, 1), 1)
    assert "DATE_OLD" in {i.code for i in validate_fields(old, Classification(D.OTHER, 1))}


def test_analysis_json_roundtrip_is_serialisable(svc) -> None:
    import json
    sc = make_scenario(svc)
    analysis = svc.ingest.pipeline().analyze(text("dunning2_inkasso"))
    data = json.loads(analysis.to_json())
    assert data["classification"]["doc_type"] == "second_dunning"
    assert data["candidates"][0]["invoice_id"] == sc.invoice.id
    assert data["fields"]["amounts"]["fees"]["value"] == 1500
    assert data["fields"]["deadline"]["span"]


def test_sender_matching_variants(svc) -> None:
    sc = make_scenario(svc)
    pl = svc.ingest.pipeline()
    # exact via letterhead/IBAN
    a = pl.analyze(text("invoice_RE-2024-001"))
    assert a.sender.party_id == sc.supplier.id and a.sender.supplier_id == sc.supplier.id
    # agency known: letter resolves to represented supplier
    a = pl.analyze(text("dunning2_inkasso"))
    assert a.sender.party_id == sc.agency.id and a.sender.supplier_id == sc.supplier.id
    # alias + fuzzy (OCR damaged letterhead)
    damaged = text("invoice_RE-2024-001").replace("Müller Bürobedarf GmbH", "Miller Burobedarf GmbH").replace(
        "DE89 3704 0044 0532 0130 00", "").replace("DE123456789", "")
    a = pl.analyze(damaged)
    assert a.sender.party_id == sc.supplier.id and a.sender.reason in ("Briefkopf", "Name im Text")
    # unknown sender is proposed as new
    a = pl.analyze(text("invoice_en"))
    assert a.sender.party_id is None and a.sender.name.startswith("Acme") and a.sender.supplier_id is None
    assert pl.analyze("").sender is None


def test_linker_by_reference_amount_and_supplier_conflict(svc) -> None:
    from supplier_app.services.dunning_service import NoticeDraft
    from supplier_app.services.ledger import NoticeClaim
    sc = make_scenario(svc)
    svc.dunning.book_notice(NoticeDraft(
        sc.agency.id, date(2024, 3, 1), D_LEVEL, [NoticeClaim(sc.invoice.id, 100000, fees_cents=500)],
        references=[(R.FILE_NUMBER, "INK-NEW-9")]))
    pl = svc.ingest.pipeline()
    # letter without invoice number, only the remembered new agency reference
    t = "Inkasso Schmidt & Partner GmbH\n2. Mahnung\nDatum: 10.04.2024\nAktenzeichen: INK-NEW-9\nGesamtforderung: 1.005,00 €"
    a = pl.analyze(t)
    assert a.candidates and a.candidates[0].invoice_id == sc.invoice.id
    assert any("Referenz" in r for r in a.candidates[0].reasons)
    # no hint at all -> no candidate, flagged
    a = pl.analyze("2. Mahnung\nDatum: 10.04.2024\nGesamtforderung: 5,00 €")
    assert a.candidates == [] and "NO_LINK" in {i.code for i in a.issues}
    # bank statement matched by amount equal to open balance + invoice number
    pay = "Zahlungsbestätigung\nAusführungsdatum: 01.04.2024\nBetrag: 1.005,00 EUR\nVerwendungszweck: RE 2024/001"
    a = pl.analyze(pay)
    assert a.candidates and a.candidates[0].invoice_id == sc.invoice.id


D_LEVEL = __import__("supplier_app.models.enums", fromlist=["DunningLevel"]).DunningLevel.SECOND
