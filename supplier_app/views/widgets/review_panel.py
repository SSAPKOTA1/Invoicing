"""Review workflow for one document: proposal form, validation messages, highlighted source text."""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QScrollArea,
    QStackedWidget,
    QTableWidget,
    QVBoxLayout,
    QWidget,
)

from supplier_app.controllers.app_controller import AppController
from supplier_app.errors import SupplierAppError
from supplier_app.i18n import tr
from supplier_app.models.enums import ReferenceType, ReviewStatus
from supplier_app.services.review_models import (
    KIND_CREDIT,
    KIND_INVOICE,
    KIND_NONE,
    KIND_NOTICE,
    KIND_PAYMENT,
    ReviewData,
)
from supplier_app.views.errors import show_error
from supplier_app.views.widgets.common import button
from supplier_app.views.widgets.review_forms import (
    CreditForm,
    InvoiceForm,
    NoneForm,
    NoticeForm,
    PaymentForm,
)

KINDS = [KIND_INVOICE, KIND_CREDIT, KIND_NOTICE, KIND_PAYMENT, KIND_NONE]


class ReviewPanel(QWidget):
    """Accept / correct / reject. ``span_requested`` asks the text pane to highlight a source span."""

    finished = Signal(int, str)  # document id, 'confirmed' | 'rejected'
    span_requested = Signal(object)

    def __init__(self, ctrl: AppController) -> None:
        super().__init__()
        self.ctrl = ctrl
        self.review: ReviewData | None = None
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self.title = QLabel(tr("review.title"))
        self.title.setObjectName("SectionTitle")
        outer.addWidget(self.title)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        inner = QWidget()
        self.inner = QVBoxLayout(inner)
        self.inner.setContentsMargins(0, 0, 6, 0)
        scroll.setWidget(inner)
        outer.addWidget(scroll, 1)
        self.messages = QVBoxLayout()
        self.inner.addLayout(self.messages)
        top = QHBoxLayout()
        top.addWidget(QLabel(tr("review.kind")))
        self.kind = QComboBox()
        for k in KINDS:
            self.kind.addItem(tr(f"review.kind.{k}"), k)
        self.kind.currentIndexChanged.connect(self._kind_changed)
        top.addWidget(self.kind, 1)
        self.confidence = QLabel()
        self.confidence.setObjectName("Muted")
        top.addWidget(self.confidence)
        self.inner.addLayout(top)
        thr = ctrl.ctx.services.settings.low_confidence
        self.forms: dict[str, QWidget] = {}
        self.stack = QStackedWidget()
        for k, cls in ((KIND_INVOICE, InvoiceForm), (KIND_CREDIT, CreditForm), (KIND_NOTICE, NoticeForm),
                       (KIND_PAYMENT, PaymentForm)):
            form = cls(ctrl.ctx.services, thr, self._focus_field)
            self.forms[k] = form
            self.stack.addWidget(form)
        self.forms[KIND_NONE] = NoneForm()
        self.stack.addWidget(self.forms[KIND_NONE])
        self.inner.addWidget(self.stack)
        self.inner.addWidget(QLabel(tr("review.references")))
        self.refs = QTableWidget(0, 2)
        self.refs.setHorizontalHeaderLabels([tr("review.ref_type"), tr("review.ref_value")])
        self.refs.verticalHeader().setVisible(False)
        self.refs.horizontalHeader().setStretchLastSection(True)
        self.refs.setColumnWidth(0, 190)
        self.refs.setMinimumHeight(110)
        self.refs.setMaximumHeight(150)
        self.inner.addWidget(self.refs)
        rb = QHBoxLayout()
        rb.addWidget(button(tr("review.add_ref"), "flat", lambda: self._add_ref(ReferenceType.OTHER, "")))
        rb.addWidget(button(tr("review.remove_ref"), "flat", self._remove_ref))
        rb.addStretch(1)
        self.inner.addLayout(rb)
        self.inner.addStretch(1)
        self.error = QLabel()
        self.error.setObjectName("Danger")
        self.error.setWordWrap(True)
        self.error.setVisible(False)
        outer.addWidget(self.error)
        bar = QHBoxLayout()
        self.btn_ok = button(tr("review.accept"), "primary", self.accept)
        self.btn_reject = button(tr("review.reject"), "danger", self.reject)
        self.btn_again = button(tr("review.reanalyze"), "", self.reanalyze)
        for b in (self.btn_ok, self.btn_reject, self.btn_again):
            bar.addWidget(b)
        bar.addStretch(1)
        outer.addLayout(bar)
        self.set_enabled(False)

    def set_enabled(self, on: bool) -> None:
        for b in (self.btn_ok, self.btn_reject, self.btn_again, self.kind):
            b.setEnabled(on)

    # -- loading ----------------------------------------------------------------------------------------
    def load(self, doc_id: int | None) -> None:
        self.error.setVisible(False)
        for i in reversed(range(self.messages.count())):
            w = self.messages.takeAt(i).widget()
            if w:
                w.deleteLater()
        if doc_id is None:
            self.review = None
            self.title.setText(tr("review.title"))
            self.set_enabled(False)
            self.stack.setEnabled(False)
            return
        svc = self.ctrl.ctx.services
        doc = svc.documents.get(doc_id)
        decided = doc.review_status in (ReviewStatus.ACCEPTED, ReviewStatus.REJECTED)
        self.review = svc.ingest.build_review(doc_id)
        r = self.review
        self.kind.blockSignals(True)
        self.kind.setCurrentIndex(max(0, self.kind.findData(r.kind)))
        self.kind.blockSignals(False)
        self.stack.setCurrentWidget(self.forms[r.kind])
        self.forms[r.kind].load(r)  # type: ignore[attr-defined]
        self.refs.setRowCount(0)
        for t, v in r.references:
            self._add_ref(t, v)
        self.confidence.setText(tr("review.confidence", n=int(doc.confidence * 100)))
        self.title.setText(f"{tr('review.title')}: {doc.original_name}")
        for msg in r.messages:
            lab = QLabel("⚠ " + msg)
            lab.setObjectName("Warning")
            lab.setWordWrap(True)
            self.messages.addWidget(lab)
        if decided:
            note = QLabel(tr(f"review.decided.{doc.review_status.value}"))
            note.setObjectName("Muted")
            self.messages.addWidget(note)
        self.set_enabled(not decided)
        self.stack.setEnabled(not decided)
        self.btn_again.setEnabled(not decided)

    def _kind_changed(self) -> None:
        if self.review is None:
            return
        kind = self.kind.currentData()
        self._collect()
        self.review.kind = kind
        self.stack.setCurrentWidget(self.forms[kind])
        self.forms[kind].load(self.review)  # type: ignore[attr-defined]

    def _focus_field(self, field: str) -> None:
        if self.review and field in self.review.spans:
            self.span_requested.emit(self.review.spans[field])

    # -- references ---------------------------------------------------------------------------------------
    def _add_ref(self, ref_type: ReferenceType, value: str) -> None:
        r = self.refs.rowCount()
        self.refs.insertRow(r)
        combo = QComboBox()
        for t in ReferenceType:
            combo.addItem(tr(f"ref.{t.value}"), t)
        combo.setCurrentIndex(combo.findData(ref_type))
        self.refs.setCellWidget(r, 0, combo)
        self.refs.setCellWidget(r, 1, QLineEdit(value))

    def _remove_ref(self) -> None:
        r = self.refs.currentRow()
        if r >= 0:
            self.refs.removeRow(r)

    def _refs(self) -> list[tuple[ReferenceType, str]]:
        out: list[tuple[ReferenceType, str]] = []
        for r in range(self.refs.rowCount()):
            value = self.refs.cellWidget(r, 1).text().strip()
            if value:
                out.append((ReferenceType(self.refs.cellWidget(r, 0).currentData()), value))
        return out

    # -- actions -------------------------------------------------------------------------------------------
    def _collect(self) -> ReviewData | None:
        if self.review is None:
            return None
        r = self.review
        r.kind = self.kind.currentData()
        self.forms[r.kind].apply(r)  # type: ignore[attr-defined]
        r.references = self._refs()
        return r

    def accept(self) -> None:
        r = self._collect()
        if r is None:
            return
        self.error.setVisible(False)
        try:
            result = self.ctrl.ctx.services.ingest.confirm(r)
        except SupplierAppError as exc:
            self.error.setText(exc.message)
            self.error.setVisible(True)
            return
        except Exception as exc:  # noqa: BLE001
            show_error(self, exc)
            return
        self.ctrl.notify_changed()
        self.ctrl.status.emit(tr("review.booked"))
        msgs = result.discrepancies + result.warnings
        if msgs:
            from supplier_app.views.errors import info
            info(self, tr("notice.discrepancy"), "\n\n".join(msgs))
        self.finished.emit(r.document_id, "confirmed")

    def reject(self) -> None:
        if self.review:
            self.ctrl.run(self.ctrl.ctx.services.ingest.reject, self.review.document_id, parent=self)
            self.finished.emit(self.review.document_id, "rejected")

    def reanalyze(self) -> None:
        if self.review:
            self.load(self.review.document_id)
