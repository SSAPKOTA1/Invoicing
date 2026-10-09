"""Document files: copy into the data folder, hash, de-duplicate."""

from __future__ import annotations

import hashlib
import re
import shutil
from pathlib import Path

from supplier_app.errors import DocumentError
from supplier_app.models.entities import Document
from supplier_app.models.enums import ReviewStatus
from supplier_app.repositories.interfaces import Repositories
from supplier_app.services.base import ServiceBase
from supplier_app.settings.paths import AppPaths

ALLOWED_SUFFIXES = {".pdf", ".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".txt"}
MAX_BYTES = 500 * 1024 * 1024


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def safe_name(name: str) -> str:
    cleaned = re.sub(r"[^\w.\- ()äöüÄÖÜß]", "_", name).strip(" .")
    return cleaned[:120] or "dokument"


class DocumentService(ServiceBase):
    def __init__(self, repos: Repositories, paths: AppPaths) -> None:
        super().__init__(repos)
        self.paths = paths

    def store_file(self, source: Path) -> tuple[Document, bool]:
        """Copy ``source`` into the documents folder. Returns ``(document, created)``.

        An already imported file (same SHA-256) returns the existing document with ``created=False``.
        """
        source = Path(source)
        if not source.is_file():
            raise DocumentError(f"Die Datei '{source.name}' wurde nicht gefunden.")
        if source.suffix.lower() not in ALLOWED_SUFFIXES:
            raise DocumentError(
                f"Dateityp '{source.suffix}' wird nicht unterstützt (PDF, PNG, JPG, TIFF, TXT).")
        size = source.stat().st_size
        if size == 0:
            raise DocumentError(f"Die Datei '{source.name}' ist leer.")
        if size > MAX_BYTES:
            raise DocumentError(f"Die Datei '{source.name}' ist zu groß (maximal 500 MB).")
        try:
            digest = sha256_of(source)
        except OSError as exc:
            raise DocumentError(f"Die Datei '{source.name}' kann nicht gelesen werden: {exc}") from exc
        existing = self.repos.documents.get_by_hash(digest)
        if existing is not None:
            return existing, False
        self.paths.documents.mkdir(parents=True, exist_ok=True)
        target = self.paths.documents / f"{digest[:12]}_{safe_name(source.name)}"
        try:
            shutil.copy2(source, target)
        except OSError as exc:
            raise DocumentError(
                f"Die Datei konnte nicht kopiert werden (Speicherplatz?): {exc}") from exc
        doc = Document(stored_path=target.name, sha256=digest, original_name=source.name)
        try:
            with self.repos.transaction():
                self.repos.documents.add(doc)
                self._audit("import", "document", doc.id, source.name)
        except Exception:
            target.unlink(missing_ok=True)
            raise
        return doc, True

    def file_path(self, doc: Document) -> Path:
        return self.paths.documents / doc.stored_path

    def get(self, doc_id: int) -> Document:
        doc = self.repos.documents.get(doc_id)
        if doc is None:
            raise DocumentError("Dokument nicht gefunden.")
        return doc

    def set_review_status(self, doc_id: int, status: ReviewStatus) -> None:
        doc = self.get(doc_id)
        doc.review_status = status
        self.repos.documents.update(doc)
        self._audit("review", "document", doc_id, status.value)

    def list(self, status: ReviewStatus | None = None) -> list[Document]:
        return self.repos.documents.list(review_status=status)
