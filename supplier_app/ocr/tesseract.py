"""Locating and calling Tesseract (bundled first, then Settings path, then PATH)."""

from __future__ import annotations

import logging
import os
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path

from PIL import Image

from supplier_app.errors import OcrError, TesseractMissingError

log = logging.getLogger(__name__)

EXE_NAME = "tesseract.exe" if sys.platform.startswith("win") else "tesseract"
INSTALL_HINT = (
    "Tesseract wurde nicht gefunden. In der ausgelieferten Windows-Version ist Tesseract enthalten "
    "(Ordner 'tesseract' neben SupplierApp.exe). Bei einer Entwicklungsinstallation installieren Sie "
    "Tesseract (z. B. von https://github.com/UB-Mannheim/tesseract/wiki) inklusive der Sprachdaten "
    "'deu' und 'eng' oder tragen den Pfad unter Einstellungen > Tesseract ein."
)


def bundled_dirs() -> list[Path]:
    """Folders where a bundled Tesseract may live (PyInstaller one-folder layout or source tree)."""
    dirs: list[Path] = []
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        dirs.append(Path(meipass) / "tesseract")
    dirs.append(Path(sys.executable).parent / "tesseract")
    dirs.append(Path(__file__).resolve().parents[2] / "tesseract")
    return dirs


def locate_tesseract(configured: str = "") -> Path | None:
    """Bundled Tesseract first, then the configured path, then ``PATH``."""
    for d in bundled_dirs():
        candidate = d / EXE_NAME
        if candidate.is_file():
            return candidate
    if configured:
        p = Path(configured)
        if p.is_dir():
            p = p / EXE_NAME
        if p.is_file():
            return p
    found = shutil.which("tesseract")
    return Path(found) if found else None


@dataclass(frozen=True)
class TesseractInfo:
    path: Path | None
    languages: tuple[str, ...]
    version: str
    bundled: bool

    @property
    def available(self) -> bool:
        return self.path is not None

    @property
    def has_german(self) -> bool:
        return "deu" in self.languages

    def describe(self) -> str:
        if not self.available:
            return INSTALL_HINT
        langs = ", ".join(self.languages) or "?"
        origin = "mitgeliefert" if self.bundled else "System"
        return f"Tesseract {self.version} ({origin}): {self.path} · Sprachen: {langs}"


class TesseractRunner:
    """Thin wrapper around pytesseract with graceful errors."""

    def __init__(self, configured_path: str = "") -> None:
        self.configured_path = configured_path
        self._info: TesseractInfo | None = None

    def info(self, refresh: bool = False) -> TesseractInfo:
        if self._info is not None and not refresh:
            return self._info
        import pytesseract

        path = locate_tesseract(self.configured_path)
        if path is None:
            self._info = TesseractInfo(None, (), "", False)
            return self._info
        pytesseract.pytesseract.tesseract_cmd = str(path)
        tessdata = path.parent / "tessdata"
        if tessdata.is_dir():
            os.environ["TESSDATA_PREFIX"] = str(tessdata)
        try:
            version = str(pytesseract.get_tesseract_version())
            langs = tuple(sorted(x for x in pytesseract.get_languages(config="") if x != "osd"))
        except Exception as exc:  # noqa: BLE001 - broken installs raise various errors
            log.warning("Tesseract found at %s but unusable: %s", path, exc)
            self._info = TesseractInfo(None, (), "", False)
            return self._info
        bundled = any(path.parent == d for d in bundled_dirs())
        self._info = TesseractInfo(path, langs, version, bundled)
        return self._info

    def language_arg(self) -> str:
        langs = self.info().languages
        wanted = [x for x in ("deu", "eng") if x in langs]
        return "+".join(wanted) if wanted else (langs[0] if langs else "eng")

    def require(self) -> TesseractInfo:
        info = self.info()
        if not info.available:
            raise TesseractMissingError(INSTALL_HINT)
        return info

    def image_to_text(self, image: Image.Image) -> tuple[str, float]:
        """OCR one PIL image; returns ``(text, mean word confidence 0..1)``."""
        import pytesseract

        self.require()
        lang = self.language_arg()
        try:
            data = pytesseract.image_to_data(
                image, lang=lang, config="--psm 6" if image.height < 400 else "--psm 3",
                output_type=pytesseract.Output.DICT, timeout=180)
        except RuntimeError as exc:
            raise OcrError("Die Texterkennung hat zu lange gedauert und wurde abgebrochen.") from exc
        except pytesseract.TesseractError as exc:
            raise OcrError(f"Die Texterkennung ist fehlgeschlagen: {exc}") from exc
        lines: dict[tuple[int, int, int], list[str]] = {}
        confs: list[float] = []
        for i, word in enumerate(data["text"]):
            word = word.strip()
            if not word:
                continue
            key = (data["block_num"][i], data["par_num"][i], data["line_num"][i])
            lines.setdefault(key, []).append(word)
            try:
                c = float(data["conf"][i])
            except (TypeError, ValueError):
                continue
            if c >= 0:
                confs.append(c)
        text = "\n".join(" ".join(ws) for _k, ws in sorted(lines.items()))
        return text, (sum(confs) / len(confs) / 100.0 if confs else 0.0)
