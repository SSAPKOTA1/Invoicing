"""Measured quality of the recognition on a generated corpus of realistic letters (see recognition_corpus.py)."""

from __future__ import annotations

import pytest

from supplier_app.ai.references import LabelledReferenceExtractor
from tests.recognition_corpus import build_corpus, evaluate, populate_master, populate_own


def _evaluation(svc, *, hard: bool):
    ids = populate_master(svc, hard=hard)
    populate_own(svc)
    cases = build_corpus(noise=0.07 if hard else 0.0)
    return evaluate(svc, cases, ids)


def _rate(hit: int, total: int) -> float:
    return hit / total if total else 1.0


def test_clean_letters_are_recognised_almost_perfectly(svc) -> None:
    ev = _evaluation(svc, hard=False)
    assert _rate(ev.supplier_hits, ev.supplier_total) >= 0.98, ev.wrong_supplier
    assert _rate(ev.sender_hits, ev.sender_total) >= 0.98
    assert _rate(ev.new_name_hits, ev.new_name_total) >= 0.95, ev.wrong_names
    for rtype, total in ev.ref_total.items():
        assert _rate(ev.ref_hits.get(rtype, 0), total) >= 0.95, (rtype, ev.ref_misses)
    assert _rate(ev.ref_extracted - ev.ref_wrong, ev.ref_extracted) >= 0.97


def test_noisy_ocr_and_look_alike_master_data_stay_reliable(svc) -> None:
    ev = _evaluation(svc, hard=True)
    assert _rate(ev.supplier_hits, ev.supplier_total) >= 0.90, ev.wrong_supplier
    assert _rate(ev.supplier_top3_hits, ev.supplier_total) >= 0.95
    assert _rate(ev.new_name_hits, ev.new_name_total) >= 0.85, ev.wrong_names


@pytest.mark.parametrize("text, ref_type, value", [
    ("Kundennummer: 12345      Vertragsnummer: V-77", "customer_number", "12345"),
    ("Kundennummer: 12345      Vertragsnummer: V-77", "contract_number", "V-77"),
    ("Kundennummer 12345 Rechnungsnummer R-1", "customer_number", "12345"),
    ("Kundennummer:\n12345", "customer_number", "12345"),
    ("Kundennummer   Vertragsnummer\n12345   V-77", "contract_number", "V-77"),
    ("Ihre Kundennummer\n4711", "customer_number", "4711"),
    ("Aktenzeichen: AZ 61-1090", "file_number", "AZ 61-1090"),
    ("Aktenzeichen: INK-NEW-9", "file_number", "INK-NEW-9"),
    ("Aktenzeichen: 12 C 345/24", "file_number", "12 C 345/24"),
    ("Unser Zeichen: VT/40/192 vom 12.03.2024", "letter_number", "VT/40/192"),
])
def test_reference_layouts(text, ref_type, value) -> None:
    found = {(r.ref_type.value, r.value.value) for r in LabelledReferenceExtractor().extract(text)}
    assert (ref_type, value) in found, found


@pytest.mark.parametrize("text", [
    "Kundennummer: 31.12.2024",  # a date is no reference
    "Kundennummer: 1.234,56",  # nor an amount
    "Kundennummer:",  # nothing
    "Kundennummer: Musterstraße",  # no digit
])
def test_things_that_are_no_reference_are_not_extracted(text) -> None:
    assert LabelledReferenceExtractor().extract(text) == []
