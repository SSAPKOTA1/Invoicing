"""Documents: drag & drop import, preview, OCR text with highlighted source spans, review workflow."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QTextCharFormat, QTextCursor
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QProgressBar,
    QSplitter,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from supplier_app.controllers.app_controller import AppController
from supplier_app.controllers.import_controller import ImportController
from supplier_app.i18n import tr
from supplier_app.models.enums import ReviewStatus
from supplier_app.services.ingest_service import ImportOutcome
from supplier_app.views.errors import info
from supplier_app.views.pages.base import Page
from supplier_app.views.theme import tokens
from supplier_app.views.widgets.common import button, page_title
from supplier_app.views.widgets.data_table import Cell, DataTable, Row
from supplier_app.views.widgets.document_preview import DocumentPreview
from supplier_app.views.widgets.drop_zone import DropZone
from supplier_app.views.widgets.review_panel import ReviewPanel

FILTERS = ["all", "review", "accepted", "rejected"]
FILE_FILTER = "Dokumente (*.pdf *.png *.jpg *.jpeg *.tif *.tiff *.bmp *.txt);;Alle Dateien (*)"


class DocumentsPage(Page):
    key = "documents"
    title = "nav.documents"

    def __init__(self, ctrl: AppController) -> None:
        super().__init__(ctrl)
        self.importer = ImportController(ctrl.ctx)
        self.importer.progress.connect(self._progress)
        self.importer.file_done.connect(self._file_done)
        self.importer.finished.connect(self._finished)
        self.doc_id: int | None = None
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 20)
        head = QHBoxLayout()
        head.addWidget(page_title(tr("nav.documents")))
        head.addStretch(1)
        head.addWidget(button(tr("action.import"), "primary", self.choose_files))
        root.addLayout(head)
        split = QSplitter(Qt.Orientation.Horizontal)

        left = QWidget()
        l_lay = QVBoxLayout(left)
        l_lay.setContentsMargins(0, 0, 0, 0)
        self.drop = DropZone()
        self.drop.files_dropped.connect(lambda files: self.start_import(files))
        l_lay.addWidget(self.drop)
        self.progress = QProgressBar()
        self.progress.setVisible(False)
        l_lay.addWidget(self.progress)
        self.import_msgs = QLabel()
        self.import_msgs.setWordWrap(True)
        self.import_msgs.setObjectName("Warning")
        self.import_msgs.setVisible(False)
        l_lay.addWidget(self.import_msgs)
        bar = QHBoxLayout()
        self.status = QComboBox()
        for f in FILTERS:
            self.status.addItem(tr(f"docs.filter.{f}"), f)
        self.status.currentIndexChanged.connect(lambda _i: self.refresh())
        self.filter = QLineEdit()
        self.filter.setPlaceholderText(tr("common.filter"))
        self.filter.textChanged.connect(lambda t: self.table.set_filter_text(t))
        bar.addWidget(self.status)
        bar.addWidget(self.filter, 1)
        l_lay.addLayout(bar)
        self.table = DataTable()
        self.table.row_selected.connect(self._selected)
        l_lay.addWidget(self.table, 1)
        split.addWidget(left)

        self.tabs = QTabWidget()
        self.preview = DocumentPreview()
        self.tabs.addTab(self.preview, tr("docs.tab.preview"))
        self.text = QPlainTextEdit()
        self.text.setReadOnly(True)
        self.tabs.addTab(self.text, tr("docs.tab.text"))
        self.review = ReviewPanel(ctrl)
        self.review.finished.connect(self._review_finished)
        self.review.span_requested.connect(self._highlight)
        split.addWidget(self.review)
        split.addWidget(self.tabs)
        split.setChildrenCollapsible(False)
        split.setSizes([330, 560, 440])
        root.addWidget(split, 1)

    # -- list -----------------------------------------------------------------------------------------------
    def refresh(self) -> None:
        mode = self.status.currentData()
        docs = self.svc.repos.documents.list()
        if mode == "review":
            docs = [d for d in docs if d.review_status in (ReviewStatus.PENDING, ReviewStatus.NEEDS_REVIEW)]
        elif mode == "accepted":
            docs = [d for d in docs if d.review_status == ReviewStatus.ACCEPTED]
        elif mode == "rejected":
            docs = [d for d in docs if d.review_status == ReviewStatus.REJECTED]
        threshold = self.svc.settings.low_confidence
        rows = []
        for d in docs:
            tone = "warn" if d.review_status == ReviewStatus.NEEDS_REVIEW else (
                "ok" if d.review_status == ReviewStatus.ACCEPTED else "muted" if d.review_status == ReviewStatus.REJECTED else "")
            rows.append(Row([d.original_name, tr(f"doctype.{d.doc_type.value}"),
                             Cell(f"{int(d.confidence * 100)} %", d.confidence, "right", "bad" if d.confidence < threshold else ""),
                             Cell(tr(f"review.{d.review_status.value}"), tone=tone)], d.id))
        keep = self.doc_id
        self.table.set_data([tr("doc.name"), tr("doc.type"), tr("doc.confidence"), tr("doc.status")], rows, [150, 110, 80, 90])
        if keep is not None and not self.table.select_payload(keep):
            self.doc_id = None
            self.review.load(None)
        elif keep is not None:
            self._load_document(keep, reload_review=False)

    def select_document(self, doc_id: int) -> None:
        self.status.setCurrentIndex(0)
        self.refresh()
        self.table.select_payload(doc_id)

    def _selected(self, doc_id) -> None:
        self.doc_id = doc_id
        self._load_document(doc_id)

    def _load_document(self, doc_id: int | None, reload_review: bool = True) -> None:
        if doc_id is None:
            self.preview.clear()
            self.text.setPlainText("")
            self.review.load(None)
            return
        doc = self.svc.documents.get(doc_id)
        self.preview.show_file(self.svc.documents.file_path(doc))
        self.text.setPlainText(doc.ocr_text or tr("docs.no_text"))
        if reload_review:
            self.review.load(doc_id)
            self._mark_low_confidence()

    # -- highlighting ---------------------------------------------------------------------------------------------
    def _selections(self, spans: list[tuple[int, int]], color: str) -> list[QTextEdit.ExtraSelection]:
        out = []
        for start, end in spans:
            sel = QTextEdit.ExtraSelection()
            cur = QTextCursor(self.text.document())
            cur.setPosition(max(0, start))
            cur.setPosition(min(end, self.text.document().characterCount() - 1), QTextCursor.MoveMode.KeepAnchor)
            sel.cursor = cur
            fmt = QTextCharFormat()
            fmt.setBackground(QColor(color))
            fmt.setForeground(QColor("#10141c"))
            sel.format = fmt
            out.append(sel)
        return out

    def _mark_low_confidence(self) -> None:
        r = self.review.review
        if r is None:
            self.text.setExtraSelections([])
            return
        thr = self.svc.settings.low_confidence
        low = [span for f, span in r.spans.items() if r.confidence.get(f, 1.0) < thr]
        self._low_spans = low
        self.text.setExtraSelections(self._selections(low, tokens(self.ctrl.theme)["warn"]))

    _low_spans: list[tuple[int, int]] = []

    def _highlight(self, span) -> None:
        start, end = span
        sel = self._selections([(start, end)], tokens(self.ctrl.theme)["accent"]) + \
            self._selections(self._low_spans, tokens(self.ctrl.theme)["warn"])
        self.text.setExtraSelections(sel)
        cur = QTextCursor(self.text.document())
        cur.setPosition(max(0, start))
        self.text.setTextCursor(cur)
        self.text.centerCursor()
        self.tabs.setCurrentIndex(1)

    # -- import ----------------------------------------------------------------------------------------------------------
    def choose_files(self) -> None:
        files, _ = QFileDialog.getOpenFileNames(self, tr("action.import"), "", FILE_FILTER)
        if files:
            self.start_import([Path(f) for f in files])

    def start_import(self, files: list[Path]) -> None:
        if self.importer.busy:
            info(self, tr("docs.busy"))
            return
        self.import_msgs.setVisible(False)
        self.progress.setVisible(True)
        self.progress.setRange(0, len(files))
        self.progress.setValue(0)
        self.importer.import_files(files)

    def _progress(self, done: int, total: int, name: str) -> None:
        self.progress.setRange(0, total)
        self.progress.setValue(done)
        self.progress.setFormat(f"{done}/{total}  {name}")

    def _file_done(self, outcome: ImportOutcome) -> None:
        self.ctrl.status.emit(outcome.document.original_name if outcome.document else outcome.error)

    def _finished(self, outcomes: list[ImportOutcome]) -> None:
        self.progress.setVisible(False)
        lines = []
        for o in outcomes:
            if o.error:
                lines.append("✗ " + o.error)
            lines.extend("• " + w for w in o.warnings)
        self.import_msgs.setText("\n".join(lines))
        self.import_msgs.setVisible(bool(lines))
        created = [o.document for o in outcomes if o.document and o.created]
        self.ctrl.notify_changed()
        self.ctrl.status.emit(tr("docs.imported", n=len(created), total=len(outcomes)))
        if created and created[0].id:
            self.select_document(created[0].id)

    def _review_finished(self, doc_id: int, result: str) -> None:
        self.refresh()
        self.review.load(doc_id)
