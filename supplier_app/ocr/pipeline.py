"""Text extraction: PDF text layer first, OCR as fallback; plain text files; images."""

from __future__ import annotations

import logging
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from PIL import Image

from supplier_app.errors import DocumentError, OcrError, TesseractMissingError

from .preprocess import preprocess
from .tesseract import TesseractRunner

log = logging.getLogger(__name__)

MIN_TEXT_CHARS = 25  # a PDF page with less text than this is treated as scanned
MAX_OCR_PAGES = 30
MAX_TEXT_PAGES = 300
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp"}
Image.MAX_IMAGE_PIXELS = 200_000_000

Progress = Callable[[int, int], None]


@dataclass
class ExtractedText:
    text: str
    page_count: int
    source: str  # 'text_layer' | 'ocr' | 'plain' | 'mixed' | ''
    confidence: float  # 1.0 for text layers
    warnings: list[str] = field(default_factory=list)

    @property
    def empty(self) -> bool:
        return not self.text.strip()


def read_plain_text(path: Path) -> str:
    raw = path.read_bytes()
    for enc in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


class TextExtractor:
    """Extract text from PDF / image / text files. Never raises raw library errors."""

    def __init__(self, runner: TesseractRunner) -> None:
        self.runner = runner

    def extract(self, path: Path, progress: Progress | None = None) -> ExtractedText:
        path = Path(path)
        suffix = path.suffix.lower()
        try:
            if suffix == ".txt":
                text = read_plain_text(path)
                return self._finish(ExtractedText(text, 1, "plain", 1.0))
            if suffix == ".pdf":
                return self._finish(self._from_pdf(path, progress))
            if suffix in IMAGE_SUFFIXES:
                return self._finish(self._from_image(path, progress))
        except (DocumentError, OcrError):
            raise
        except Exception as exc:  # noqa: BLE001 - corrupt files raise assorted library errors
            log.exception("extraction failed for %s", path)
            raise DocumentError(f"Die Datei '{path.name}' ist beschädigt oder nicht lesbar.") from exc
        raise DocumentError(f"Dateityp '{suffix}' wird nicht unterstützt.")

    @staticmethod
    def _finish(result: ExtractedText) -> ExtractedText:
        result.text = unicodedata.normalize("NFC", result.text)
        if result.empty:
            result.warnings.append("Es wurde kein Text erkannt. Bitte Dokument manuell erfassen.")
        return result

    def _from_pdf(self, path: Path, progress: Progress | None) -> ExtractedText:
        import pymupdf

        try:
            doc = pymupdf.open(path)
        except Exception as exc:  # noqa: BLE001
            raise DocumentError(f"Die PDF-Datei '{path.name}' ist beschädigt und kann nicht geöffnet werden.") from exc
        with doc:
            if doc.needs_pass:
                raise DocumentError(f"Die PDF-Datei '{path.name}' ist passwortgeschützt.")
            pages = doc.page_count
            warnings: list[str] = []
            texts: list[str] = []
            used_ocr = used_layer = False
            confs: list[float] = []
            ocr_pages = 0
            for i in range(min(pages, MAX_TEXT_PAGES)):
                if progress:
                    progress(i, pages)
                layer = doc[i].get_text("text").strip()
                if len(layer) >= MIN_TEXT_CHARS:
                    texts.append(layer)
                    used_layer = True
                    confs.append(1.0)
                    continue
                if ocr_pages >= MAX_OCR_PAGES:
                    warnings.append(f"Nur die ersten {MAX_OCR_PAGES} gescannten Seiten wurden per OCR gelesen.")
                    break
                try:
                    pix = doc[i].get_pixmap(dpi=300)
                    image = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
                    text, conf = self._ocr(image)
                except TesseractMissingError:
                    warnings.append("Gescannte Seite(n) ohne Text: Tesseract fehlt, keine OCR möglich.")
                    texts.append(layer)
                    break
                ocr_pages += 1
                used_ocr = True
                texts.append(text or layer)
                confs.append(conf)
            if pages > MAX_TEXT_PAGES:
                warnings.append(f"Das Dokument hat {pages} Seiten; nur {MAX_TEXT_PAGES} wurden gelesen.")
        source = "mixed" if used_layer and used_ocr else "text_layer" if used_layer else "ocr" if used_ocr else ""
        return ExtractedText("\n\n".join(t for t in texts if t), pages, source,
                             sum(confs) / len(confs) if confs else 0.0, warnings)

    def _ocr(self, image: Image.Image) -> tuple[str, float]:
        return self.runner.image_to_text(preprocess(image))

    def _from_image(self, path: Path, progress: Progress | None) -> ExtractedText:
        try:
            img = Image.open(path)
            img.load()
        except Image.DecompressionBombError as exc:
            raise DocumentError(f"Das Bild '{path.name}' ist zu groß.") from exc
        except Exception as exc:  # noqa: BLE001
            raise DocumentError(f"Das Bild '{path.name}' ist beschädigt und kann nicht geöffnet werden.") from exc
        frames = getattr(img, "n_frames", 1)
        texts: list[str] = []
        confs: list[float] = []
        warnings: list[str] = []
        for i in range(min(frames, MAX_OCR_PAGES)):
            if progress:
                progress(i, frames)
            img.seek(i)
            text, conf = self._ocr(img.convert("RGB"))
            texts.append(text)
            confs.append(conf)
        if frames > MAX_OCR_PAGES:
            warnings.append(f"Nur die ersten {MAX_OCR_PAGES} Seiten wurden gelesen.")
        return ExtractedText("\n\n".join(t for t in texts if t), frames, "ocr",
                             sum(confs) / len(confs) if confs else 0.0, warnings)
