"""Threaded document import: hashing + OCR in worker threads, database work on the GUI thread."""

from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal

from supplier_app.main import AppContext
from supplier_app.services.ingest_service import ImportOutcome, PreparedFile

log = logging.getLogger(__name__)


class _Signals(QObject):
    prepared = Signal(object)  # PreparedFile


class _PrepareJob(QRunnable):
    def __init__(self, ctx: AppContext, path: Path, signals: _Signals) -> None:
        super().__init__()
        self.ctx, self.path, self.signals = ctx, path, signals

    def run(self) -> None:
        prepared = self.ctx.services.ingest.prepare(self.path)
        self.signals.prepared.emit(prepared)


class ImportController(QObject):
    """Imports several files; emits progress and one outcome per file."""

    progress = Signal(int, int, str)  # done, total, current file name
    file_done = Signal(object)  # ImportOutcome
    finished = Signal(list)  # list[ImportOutcome]

    def __init__(self, ctx: AppContext) -> None:
        super().__init__()
        self.ctx = ctx
        self._pool = QThreadPool(self)
        self._pool.setMaxThreadCount(2)
        self._signals = _Signals()
        self._signals.prepared.connect(self._on_prepared)
        self._total = 0
        self._outcomes: list[ImportOutcome] = []

    @property
    def busy(self) -> bool:
        return len(self._outcomes) < self._total

    def import_files(self, paths: list[Path]) -> None:
        if self.busy or not paths:
            return
        self.ctx.services.ingest.extractor.runner.info()  # resolve Tesseract once on the GUI thread
        self._total, self._outcomes = len(paths), []
        self.progress.emit(0, self._total, paths[0].name)
        for p in paths:
            self._pool.start(_PrepareJob(self.ctx, Path(p), self._signals))

    def _on_prepared(self, prepared: PreparedFile) -> None:
        try:
            outcome = self.ctx.services.ingest.register(prepared)
        except Exception as exc:  # noqa: BLE001 - one broken file must not stop the batch
            log.exception("register failed")
            outcome = ImportOutcome(None, False, error=str(getattr(exc, "message", exc)))
        if outcome.document is None and not outcome.error:
            outcome.error = "Import fehlgeschlagen."
        self._outcomes.append(outcome)
        self.file_done.emit(outcome)
        self.progress.emit(len(self._outcomes), self._total, prepared.source.name)
        if len(self._outcomes) == self._total:
            done, self._total = self._outcomes, 0
            self._outcomes = []
            self.finished.emit(done)
