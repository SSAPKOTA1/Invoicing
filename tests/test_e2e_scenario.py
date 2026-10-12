"""End to end: scan invoice -> 1st Mahnung -> 2nd Mahnung from a collection agency -> partial payment."""

from __future__ import annotations

import shutil
from datetime import date
from pathlib import Path

import pytest

from supplier_app.models.enums import (
    AllocationComponent,
    DunningLevel,
    InvoiceStatus,
    PartyRole,
    ReviewStatus,
)
from supplier_app.ocr.tesseract import TesseractRunner
from supplier_app.services.review_models import KIND_NOTICE

FIX = Path(__file__).parent / "fixtures"
HAVE_TESSERACT = TesseractRunner().info().available
needs_ocr = pytest.mark.skipif(not HAVE_TESSERACT, reason="Tesseract nicht installiert - OCR not verified")


def run_scenario(svc, files: dict[str, Path]) -> dict:
    ing = svc.ingest
    # 1. invoice (new supplier is proposed from the letterhead)
    out = ing.import_file(files["invoice"])
    assert out.document and out.created and out.error == ""
    rev = ing.build_review(out.document.id)
    assert rev.kind == "invoice" and rev.invoice_number == "RE-2024/001" and rev.gross_cents == 100000
    assert rev.new_supplier_name.startswith("M") and rev.document_date == date(2024, 1, 10)
    assert rev.due_date == date(2024, 2, 9)
    inv_id = ing.confirm(rev).invoice_id
    supplier = svc.suppliers.suppliers()[0]
    assert supplier.ibans == ["DE89370400440532013000"]

    # 2. first Mahnung from the supplier itself
    out = ing.import_file(files["dunning1"])
    rev = ing.build_review(out.document.id)
    assert rev.kind == KIND_NOTICE and rev.level == DunningLevel.FIRST and rev.supplier_id == supplier.id
    assert rev.claims[0].invoice_id == inv_id and rev.claims[0].fees_cents == 500 and rev.total_claimed_cents == 100500
    assert rev.due_date == date(2024, 3, 15)
    res1 = ing.confirm(rev)
    assert res1.discrepancies == []

    # 3. second Mahnung from a collection agency with a new reference (agency unknown -> proposed)
    out = ing.import_file(files["dunning2"])
    rev = ing.build_review(out.document.id)
    assert rev.level == DunningLevel.SECOND and rev.supplier_id == supplier.id
    assert rev.sender_party_id is None and "Inkasso" in rev.new_sender_name
    assert rev.new_sender_role == PartyRole.COLLECTION_AGENCY
    assert rev.claims[0].invoice_id == inv_id and rev.claims[0].fees_cents == 1500
    assert rev.total_claimed_cents == 101500
    assert any(v.replace(" ", "").upper() == "INK-2024-77881" for _t, v in rev.references)
    res2 = ing.confirm(rev)
    assert res2.discrepancies == []
    assert svc.ledger.invoice_balance(inv_id).balance_cents == 101500  # fee restated, not doubled
    agency = next(p for p in svc.suppliers.list() if p.role == PartyRole.COLLECTION_AGENCY)
    assert agency.represents_supplier_id == supplier.id

    # 4. partial payment confirmation
    out = ing.import_file(files["payment"])
    rev = ing.build_review(out.document.id)
    assert rev.kind == "payment" and rev.payment_amount_cents == 40000 and rev.payment_invoice_ids == [inv_id]
    assert rev.document_date == date(2024, 4, 1)
    res3 = ing.confirm(rev)
    return {"invoice_id": inv_id, "supplier": supplier, "agency": agency, "payment_id": res3.payment_id}


def assert_final_state(svc, ctx) -> None:
    inv_id = ctx["invoice_id"]
    bal = svc.ledger.invoice_balance(inv_id)
    assert bal.balance_cents == 61500 and bal.status == InvoiceStatus.PARTIALLY_PAID
    allocs = {a.component: a.amount_cents for a in svc.repos.payments.allocations(payment_id=ctx["payment_id"])}
    assert allocs == {AllocationComponent.COSTS: 1500, AllocationComponent.PRINCIPAL: 38500}
    hist = svc.history.invoice_history(inv_id)
    kinds = [i.kind for i in hist.items]
    assert kinds.count("notice") == 2 and len(svc.cases.list()) == 1
    assert {n for n, _v in hist.references} >= {"Bearbeitungsnummer", "Aktenzeichen", "Rechnungsnummer"}
    for query in ("Müller", "RE-2024/001", "4711/A", "ink 2024 77881", "F99120"):
        assert inv_id in svc.search.search(query).invoice_ids(), query
    docs = svc.repos.documents.list()
    assert len(docs) == 4 and all(d.review_status == ReviewStatus.ACCEPTED for d in docs)
    assert all(n.document_id for n in svc.repos.notices.list())


def test_scenario_with_pdf_text_layers(file_svc) -> None:
    files = {"invoice": FIX / "pdf/invoice_RE-2024-001.pdf", "dunning1": FIX / "pdf/dunning1_mueller.pdf",
             "dunning2": FIX / "pdf/dunning2_inkasso.pdf", "payment": FIX / "pdf/payment_confirmation.pdf"}
    ctx = run_scenario(file_svc, files)
    assert_final_state(file_svc, ctx)
    # importing a file twice does not create a second document
    again = file_svc.ingest.import_file(files["invoice"])
    assert not again.created and again.warnings


@needs_ocr
def test_scenario_with_scanned_images(file_svc) -> None:
    files = {"invoice": FIX / "scans/invoice_RE-2024-001_scan.png", "dunning1": FIX / "pdf/dunning1_mueller.pdf",
             "dunning2": FIX / "scans/dunning2_inkasso_scan.png", "payment": FIX / "scans/payment_confirmation_scan.jpg"}
    ctx = run_scenario(file_svc, files)
    assert_final_state(file_svc, ctx)
    assert file_svc.repos.documents.get(1).text_source == "ocr"


def test_court_order_after_payment_flags_discrepancy(file_svc) -> None:
    files = {"invoice": FIX / "pdf/invoice_RE-2024-001.pdf", "dunning1": FIX / "pdf/dunning1_mueller.pdf",
             "dunning2": FIX / "pdf/dunning2_inkasso.pdf", "payment": FIX / "pdf/payment_confirmation.pdf"}
    ctx = run_scenario(file_svc, files)
    out = file_svc.ingest.import_file(FIX / "pdf/court_order.pdf")
    rev = file_svc.ingest.build_review(out.document.id)
    assert rev.level == DunningLevel.COURT_ORDER and rev.supplier_id == ctx["supplier"].id
    assert rev.new_sender_role == PartyRole.OTHER
    res = file_svc.ingest.confirm(rev)
    assert any("Differenz" in d for d in res.discrepancies)
    assert any("Zahlung" in d for d in res.discrepancies)
    hist = file_svc.history.invoice_history(ctx["invoice_id"])
    assert hist.warnings and file_svc.dunning.escalated_invoice_ids() == {ctx["invoice_id"]}


def test_collection_letter_with_deduction_reconciles(file_svc) -> None:
    files = {"invoice": FIX / "pdf/invoice_RE-2024-001.pdf", "dunning1": FIX / "pdf/dunning1_mueller.pdf",
             "dunning2": FIX / "pdf/dunning2_inkasso.pdf", "payment": FIX / "pdf/payment_confirmation.pdf"}
    ctx = run_scenario(file_svc, files)
    out = file_svc.ingest.import_file(FIX / "pdf/collection_letter.pdf")
    rev = file_svc.ingest.build_review(out.document.id)
    assert rev.level == DunningLevel.COLLECTION and rev.sender_party_id == ctx["agency"].id
    claim = rev.claims[0]
    assert (claim.principal_cents, claim.total_cents, rev.credited_cents) == (60000, 80290, 40000)
    res = file_svc.ingest.confirm(rev)
    assert res.discrepancies == []  # 600,00 principal + charges == ledger expectation
    assert file_svc.ledger.invoice_balance(ctx["invoice_id"]).balance_cents == 80290
    rows = file_svc.dunning.compare_with_calculation(res.notice_id)
    assert {r.label for r in rows} == {"Verzugszinsen", "Verzugspauschale"}


def test_credit_note_and_english_documents(file_svc) -> None:
    svc = file_svc
    inv = svc.ingest.import_file(FIX / "pdf/invoice_RE-2024-001.pdf")
    inv_id = svc.ingest.confirm(svc.ingest.build_review(inv.document.id)).invoice_id
    cn = svc.ingest.import_file(FIX / "pdf/credit_note.pdf")
    rev = svc.ingest.build_review(cn.document.id)
    assert rev.kind == "credit_note" and rev.invoice_id == inv_id and rev.gross_cents == 10000
    svc.ingest.confirm(rev)
    assert svc.ledger.invoice_balance(inv_id).balance_cents == 90000
    en = svc.ingest.import_file(FIX / "texts/invoice_en.txt")
    rev = svc.ingest.build_review(en.document.id)
    assert rev.kind == "invoice" and rev.invoice_number == "INV-2024-17" and rev.gross_cents == 119000
    assert rev.document_date == date(2024, 3, 12) and rev.due_date == date(2024, 4, 11)
    svc.ingest.reject(en.document.id)
    assert svc.repos.documents.get(en.document.id).review_status == ReviewStatus.REJECTED


def test_unreadable_inputs_do_not_crash(file_svc, tmp_path) -> None:
    corrupt = tmp_path / "kaputt.pdf"
    corrupt.write_bytes(b"%PDF-1.4 this is not really a pdf")
    out = file_svc.ingest.import_file(corrupt)
    assert out.document is None and "beschädigt" in out.error
    bad_img = tmp_path / "bad.png"
    bad_img.write_bytes(b"\x89PNG garbage")
    assert "beschädigt" in file_svc.ingest.import_file(bad_img).error
    empty_txt = tmp_path / "leer.txt"
    empty_txt.write_text("  \n", encoding="utf-8")
    out = file_svc.ingest.import_file(empty_txt)
    assert out.document and out.document.review_status == ReviewStatus.NEEDS_REVIEW
    assert any("kein text" in w.lower() for w in out.warnings)
    missing = file_svc.ingest.import_file(tmp_path / "gibt-es-nicht.pdf")
    assert missing.error
    exe = tmp_path / "x.exe"
    exe.write_bytes(b"MZ")
    assert file_svc.ingest.import_file(exe).error
    shutil.rmtree(tmp_path, ignore_errors=True)


def test_scanned_pdf_falls_back_to_ocr_or_warns(file_svc, tmp_path) -> None:
    """A PDF that contains only an image has no text layer."""
    import pymupdf
    img_pdf = tmp_path / "scan.pdf"
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_image(page.rect, filename=str(FIX / "scans/invoice_RE-2024-001_scan.png"))
    doc.save(img_pdf)
    doc.close()
    out = file_svc.ingest.import_file(img_pdf)
    assert out.document is not None
    if HAVE_TESSERACT:
        assert out.document.text_source == "ocr" and "RE-2024/001" in out.document.ocr_text
    else:
        assert any("Tesseract" in w for w in out.warnings)
