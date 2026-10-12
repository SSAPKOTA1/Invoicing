from __future__ import annotations

import sys
from pathlib import Path

import pytest
from PIL import Image

from supplier_app.errors import DocumentError, TesseractMissingError
from supplier_app.ocr.pipeline import TextExtractor, read_plain_text
from supplier_app.ocr.preprocess import estimate_skew, preprocess, to_gray
from supplier_app.ocr.tesseract import INSTALL_HINT, TesseractRunner, bundled_dirs, locate_tesseract

FIX = Path(__file__).parent / "fixtures"
RUNNER = TesseractRunner()
HAVE = RUNNER.info().available
needs_ocr = pytest.mark.skipif(not HAVE, reason="Tesseract nicht installiert - OCR not verified")


def test_locate_prefers_bundled_then_setting_then_path(tmp_path, monkeypatch) -> None:
    exe = tmp_path / "mytess" / ("tesseract.exe" if sys.platform.startswith("win") else "tesseract")
    exe.parent.mkdir()
    exe.write_text("x")
    assert locate_tesseract(str(exe)) in (exe, locate_tesseract(""))
    assert locate_tesseract(str(exe.parent)) is not None
    monkeypatch.setattr("supplier_app.ocr.tesseract.bundled_dirs", lambda: [exe.parent])
    assert locate_tesseract("/nonexistent") == exe
    monkeypatch.setattr("supplier_app.ocr.tesseract.bundled_dirs", lambda: [])
    monkeypatch.setattr("shutil.which", lambda _n: None)
    assert locate_tesseract("") is None
    assert bundled_dirs()


def test_missing_tesseract_is_reported_friendly(monkeypatch) -> None:
    monkeypatch.setattr("supplier_app.ocr.tesseract.locate_tesseract", lambda _p="": None)
    runner = TesseractRunner()
    info = runner.info()
    assert not info.available and info.describe() == INSTALL_HINT
    with pytest.raises(TesseractMissingError):
        runner.require()
    with pytest.raises(TesseractMissingError):
        runner.image_to_text(Image.new("L", (10, 10)))
    # a scanned PDF without Tesseract yields a warning, not a crash
    import pymupdf
    ext = TextExtractor(runner)
    with pytest.raises(DocumentError):
        ext.extract(Path("x.xyz"))
    img = FIX / "scans/invoice_RE-2024-001_scan.png"
    with pytest.raises(TesseractMissingError):
        ext.extract(img)
    assert pymupdf is not None


@needs_ocr
def test_tesseract_info_and_language() -> None:
    info = RUNNER.info(refresh=True)
    assert info.available and info.has_german and "Tesseract" in info.describe()
    assert RUNNER.language_arg() == "deu+eng"


@needs_ocr
def test_ocr_of_scanned_images() -> None:
    ext = TextExtractor(RUNNER)
    out = ext.extract(FIX / "scans/invoice_RE-2024-001_scan.png")
    assert out.source == "ocr" and out.confidence > 0.7
    for needle in ("RE-2024/001", "1.000,00", "10.01.2024", "Rechnungsdatum"):
        assert needle in out.text
    jpg = ext.extract(FIX / "scans/payment_confirmation_scan.jpg")
    assert "400,00" in jpg.text and "RE-2024/001" in jpg.text


def test_text_layer_pdf_and_plain_text(tmp_path) -> None:
    ext = TextExtractor(RUNNER)
    pdf = ext.extract(FIX / "pdf/invoice_RE-2024-001.pdf")
    assert pdf.source == "text_layer" and pdf.confidence == 1.0 and "Rechnungsnummer: RE-2024/001" in pdf.text
    cp = tmp_path / "alt.txt"
    cp.write_bytes("Müller Rechnung 12,00 €".encode("cp1252"))
    assert "Müller" in read_plain_text(cp) and ext.extract(cp).source == "plain"
    bad = tmp_path / "b.txt"
    bad.write_bytes(b"\xff\xfe\x00\x80")
    assert read_plain_text(bad)


def test_pdf_errors(tmp_path) -> None:
    import pymupdf
    ext = TextExtractor(RUNNER)
    broken = tmp_path / "broken.pdf"
    broken.write_bytes(b"not a pdf at all")
    with pytest.raises(DocumentError):
        ext.extract(broken)
    enc = tmp_path / "enc.pdf"
    d = pymupdf.open()
    d.new_page().insert_text((50, 50), "Geheim " * 10)
    d.save(enc, encryption=pymupdf.PDF_ENCRYPT_AES_256, owner_pw="o", user_pw="u")
    d.close()
    with pytest.raises(DocumentError) as err:
        ext.extract(enc)
    assert "passwortgeschützt" in str(err.value)


def test_multi_page_pdf_progress(tmp_path) -> None:
    import pymupdf
    pdf = tmp_path / "multi.pdf"
    d = pymupdf.open()
    for i in range(3):
        d.new_page().insert_text((50, 50), f"Seite {i + 1} Rechnung mit genug Text für die Erkennung")
    d.save(pdf)
    d.close()
    seen: list[tuple[int, int]] = []
    out = TextExtractor(RUNNER).extract(pdf, lambda i, n: seen.append((i, n)))
    assert out.page_count == 3 and "Seite 3" in out.text and seen == [(0, 3), (1, 3), (2, 3)]


def test_preprocess_deskews_and_binarizes() -> None:
    img = Image.open(FIX / "scans/invoice_RE-2024-001_scan.png")
    assert abs(estimate_skew(to_gray(img))) >= 0.5
    out = preprocess(img)
    assert out.mode == "L" and set(out.getdata()) <= {0, 255}
    small = preprocess(Image.new("RGB", (200, 100), "white"), deskew=False)
    assert max(small.size) >= 1600
    huge = preprocess(Image.new("L", (7000, 300), 255), deskew=False)
    assert max(huge.size) <= 6000


@needs_ocr
def test_empty_image_gives_warning(tmp_path) -> None:
    blank = tmp_path / "blank.png"
    Image.new("RGB", (800, 600), "white").save(blank)
    out = TextExtractor(RUNNER).extract(blank)
    assert out.empty and out.warnings
