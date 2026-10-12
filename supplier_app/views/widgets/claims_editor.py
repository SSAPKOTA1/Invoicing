"""The invoices a letter concerns ("Betroffene Rechnungen"): one clear card per invoice with all amounts readable.

Each card shows the invoice (number, date, gross, open balance according to the account) and the amounts the letter
claims for it, in two columns of labelled fields. Recognition suggestions that are not on a card yet are offered as
buttons. A letter may also have no invoice yet (it can be filed and assigned later).
"""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from supplier_app.ai.result_types import LinkCandidate
from supplier_app.i18n import tr, tx
from supplier_app.models.enums import InvoiceStatus
from supplier_app.services.container import Services
from supplier_app.services.review_models import ClaimInput
from supplier_app.util.dates import format_date
from supplier_app.util.money import format_cents
from supplier_app.views.widgets.common import button, wrapped_label
from supplier_app.views.widgets.inputs import MoneyEdit

FIELDS = (("notice.principal", "principal_cents"), ("notice.fees", "fees_cents"), ("notice.interest", "interest_cents"),
          ("notice.flat", "flat_fee_cents"), ("notice.other", "other_costs_cents"), ("notice.total", "total_cents"))


class ClaimCard(QFrame):
    removed = Signal(object)
    changed = Signal()

    def __init__(self, svc: Services, supplier_id: int | None, claim: ClaimInput | None) -> None:
        super().__init__()
        self.svc = svc
        self.setObjectName("Card")
        self.setFrameShape(QFrame.Shape.StyledPanel)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 10, 12, 10)
        lay.setSpacing(8)
        top = QHBoxLayout()
        title = QLabel(tr("review.claim.invoice"))
        title.setObjectName("SectionTitle")
        top.addWidget(title)
        self.invoice = QComboBox()
        self.invoice.setMinimumWidth(240)
        self.invoice.setMinimumHeight(34)
        self.invoice.currentIndexChanged.connect(self._invoice_changed)
        top.addWidget(self.invoice, 1)
        top.addWidget(button(tr("review.remove_claim"), "flat", lambda: self.removed.emit(self)))
        lay.addLayout(top)
        self.info = wrapped_label("", "Muted", 2)
        lay.addWidget(self.info)
        grid = QGridLayout()
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(6)
        self.edits: dict[str, MoneyEdit] = {}
        for i, (key, attr) in enumerate(FIELDS):
            box = QVBoxLayout()
            box.setSpacing(2)
            label = QLabel(tr(key))
            label.setObjectName("Muted")
            edit = MoneyEdit()
            edit.setMinimumWidth(120)
            edit.textChanged.connect(lambda _t: self.changed.emit())
            box.addWidget(label)
            box.addWidget(edit)
            holder = QWidget()
            holder.setLayout(box)
            box.setContentsMargins(0, 0, 0, 0)
            grid.addWidget(holder, i // 2, i % 2)
            self.edits[attr] = edit
        lay.addLayout(grid)
        self.fill_invoices(supplier_id, claim.invoice_id if claim else None)
        if claim:
            for attr, edit in self.edits.items():
                edit.set_cents(getattr(claim, attr))

    def fill_invoices(self, supplier_id: int | None, select: int | None) -> None:
        self.invoice.blockSignals(True)
        self.invoice.clear()
        self._states = {}
        if supplier_id:
            for s in self.svc.ledger.invoice_states(supplier_id=supplier_id):
                if s.invoice.status == InvoiceStatus.CANCELLED:
                    continue
                self._states[s.invoice.id] = s
        for iid, s in sorted(self._states.items(), key=lambda kv: (kv[1].balance.balance_cents <= 0, kv[1].invoice.invoice_date)):
            self.invoice.addItem(tr("review.claim.item", number=s.invoice.invoice_number, gross=format_cents(s.invoice.gross_cents),
                                    open=format_cents(s.balance.balance_cents)), iid)
        self.invoice.setCurrentIndex(max(0, self.invoice.findData(select)))
        self.invoice.blockSignals(False)
        self._invoice_changed()

    def _invoice_changed(self) -> None:
        s = self._states.get(self.invoice.currentData())
        if s is None:
            self.info.setText(tr("review.claim.none"))
        else:
            self.info.setText(tr("review.claim.info", date=format_date(s.invoice.invoice_date), due=format_date(s.invoice.due_date),
                                 gross=format_cents(s.invoice.gross_cents), open=format_cents(s.balance.balance_cents)))
        self.changed.emit()

    def claim(self) -> ClaimInput | None:
        iid = self.invoice.currentData()
        if iid is None:
            return None
        return ClaimInput(int(iid), **{attr: int(edit.cents() or 0) for attr, edit in self.edits.items()})


class ClaimsEditor(QWidget):
    changed = Signal()

    def __init__(self, svc: Services) -> None:
        super().__init__()
        self.svc = svc
        self.supplier_id: int | None = None
        self.cards: list[ClaimCard] = []
        self.candidates: list[LinkCandidate] = []
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(8)
        self.empty = wrapped_label(tr("review.claims.empty"), "Warning", 3)
        outer.addWidget(self.empty)
        self.holder = QVBoxLayout()
        self.holder.setSpacing(8)
        outer.addLayout(self.holder)
        self.suggest_row = QHBoxLayout()
        self.suggest_label = QLabel(tr("review.claims.suggestions"))
        self.suggest_label.setObjectName("Muted")
        self.suggest_row.addWidget(self.suggest_label)
        self.suggest_box = QHBoxLayout()
        self.suggest_row.addLayout(self.suggest_box)
        self.suggest_row.addStretch(1)
        outer.addLayout(self.suggest_row)
        tools = QHBoxLayout()
        tools.addWidget(button(tr("review.add_claim"), "", lambda: self.add_claim(None)))
        tools.addStretch(1)
        outer.addLayout(tools)
        self._refresh()

    # -- content ---------------------------------------------------------------------------------------------
    def set_supplier(self, supplier_id: int | None) -> None:
        self.supplier_id = supplier_id
        for card in self.cards:
            card.fill_invoices(supplier_id, card.invoice.currentData())
        self._refresh()

    def set_claims(self, claims: list[ClaimInput], candidates: list[LinkCandidate] | None = None) -> None:
        for card in self.cards:
            card.setParent(None)
            card.deleteLater()
        self.cards = []
        self.candidates = list(candidates or [])
        for claim in claims:
            self.add_claim(claim, refresh=False)
        self._refresh()

    def add_claim(self, claim: ClaimInput | None, refresh: bool = True) -> None:
        card = ClaimCard(self.svc, self.supplier_id, claim)
        card.removed.connect(self._remove)
        card.changed.connect(self.changed)
        self.cards.append(card)
        self.holder.addWidget(card)
        if refresh:
            self._refresh()
            self.changed.emit()

    def _remove(self, card: ClaimCard) -> None:
        self.cards.remove(card)
        card.setParent(None)
        card.deleteLater()
        self._refresh()
        self.changed.emit()

    def claims(self) -> list[ClaimInput]:
        return [c for c in (card.claim() for card in self.cards) if c is not None]

    def _refresh(self) -> None:
        self.empty.setVisible(not self.cards)
        used = {card.invoice.currentData() for card in self.cards}
        while self.suggest_box.count():
            item = self.suggest_box.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        shown = 0
        for cand in self.candidates:
            if cand.invoice_id in used or (self.supplier_id and cand.supplier_id != self.supplier_id) or shown >= 3:
                continue
            shown += 1
            btn = button(f"＋ {cand.invoice_number} ({int(cand.score * 100)} %)", "flat",
                         lambda cid=cand.invoice_id: self._add_candidate(cid), ", ".join(tx(r) for r in cand.reasons))
            self.suggest_box.addWidget(btn)
        self.suggest_label.setVisible(shown > 0)

    def _add_candidate(self, invoice_id: int) -> None:
        self.add_claim(ClaimInput(invoice_id))
