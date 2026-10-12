"""Choose a supplier / sender: the recognition's suggestions first (with the evidence), then "new", then everybody.

The recognition proposes who wrote a document. The user sees *why* (IBAN, name in the letterhead ...), can pick another
entry from the list, search the master data in a dialog, or create a new record from the printed data.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QVBoxLayout,
    QWidget,
)

from supplier_app.ai.result_types import NewPartyInfo, PartyCandidate
from supplier_app.i18n import tr, tx
from supplier_app.models.entities import Party
from supplier_app.models.enums import PartyRole
from supplier_app.util.normalize import normalize_name
from supplier_app.views.dialogs.forms import button_box, dialog_root
from supplier_app.views.theme import repolish
from supplier_app.views.widgets.common import button, wrapped_label

SUGGESTION_MIN = 0.3


class PartyChooserDialog(QDialog):
    """Searchable list of the master data (type a name, a place or an IBAN fragment)."""

    def __init__(self, parties: list[Party], selected: int | None = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("party.chooser.title"))
        self.setModal(True)
        self.resize(520, 460)
        self.parties = parties
        self.chosen_id: int | None = None
        root = dialog_root(self)
        self.filter = QLineEdit()
        self.filter.setPlaceholderText(tr("party.chooser.filter"))
        self.filter.textChanged.connect(self._fill)
        root.addWidget(self.filter)
        self.list = QListWidget()
        self.list.itemDoubleClicked.connect(lambda _i: self.accept())
        root.addWidget(self.list, 1)
        root.addWidget(button_box(self, tr("party.chooser.select")))
        self._selected = selected
        self._fill()
        self.filter.setFocus()

    def _fill(self) -> None:
        needle = normalize_name(self.filter.text())
        raw = self.filter.text().strip().lower()
        self.list.clear()
        for p in self.parties:
            hay = " ".join([normalize_name(p.name), *(normalize_name(a) for a in p.aliases), p.address.lower(),
                            *(i.lower() for i in p.ibans)])
            if needle and needle not in hay and raw not in hay:
                continue
            item = QListWidgetItem(f"{p.name}  ·  {tr('role.' + p.role.value)}" + (f"  ·  {p.address}" if p.address else ""))
            item.setData(Qt.ItemDataRole.UserRole, p.id)
            self.list.addItem(item)
            if p.id == self._selected:
                self.list.setCurrentItem(item)
        if self.list.currentItem() is None and self.list.count():
            self.list.setCurrentRow(0)

    def accept(self) -> None:
        item = self.list.currentItem()
        if item is not None:
            self.chosen_id = item.data(Qt.ItemDataRole.UserRole)
        super().accept()


class PartyPicker(QWidget):
    """Combo with suggestions + search button + name field for a new record + an explanation of the proposal."""

    changed = Signal()

    def __init__(self, parties: list[Party], *, allow_new: bool = True, new_label: str | None = None,
                 with_role: bool = False, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.parties = parties
        self.allow_new = allow_new
        self.new_label = new_label or tr("review.new_supplier")
        self._candidates: dict[int, PartyCandidate] = {}
        self._info: NewPartyInfo | None = None
        self._suggested = False
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(4)
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        self.combo = QComboBox()
        self.combo.setMinimumWidth(260)
        self.combo.setMinimumHeight(34)
        self.combo.currentIndexChanged.connect(self._selection_changed)
        row.addWidget(self.combo, 1)
        self.search = button(tr("party.search"), "", self._open_chooser, tr("party.search.tip"))
        row.addWidget(self.search)
        outer.addLayout(row)
        self.hint = wrapped_label("", "Muted", 2)
        outer.addWidget(self.hint)
        name_row = QHBoxLayout()
        name_row.setContentsMargins(0, 0, 0, 0)
        self.new_name = QLineEdit()
        self.new_name.setPlaceholderText(tr("review.new_supplier_name"))
        self.new_name.setMinimumHeight(34)
        name_row.addWidget(self.new_name, 1)
        self.new_role: QComboBox | None = None
        if with_role:
            self.new_role = QComboBox()
            for role in PartyRole:
                self.new_role.addItem(tr(f"role.{role.value}"), role)
            name_row.addWidget(self.new_role)
        self.new_holder = QWidget()
        self.new_holder.setLayout(name_row)
        outer.addWidget(self.new_holder)
        self.set_candidates([], None)

    # -- content ----------------------------------------------------------------------------------------
    def set_candidates(self, candidates: list[PartyCandidate], selected_id: int | None, new_name: str = "",
                       info: NewPartyInfo | None = None, suggested: bool = False) -> None:
        """Fill the list: suggestions (best first), "new", then all parties; preselect ``selected_id`` (or "new")."""
        self._candidates = {c.party_id: c for c in candidates}
        self._info = info
        self._suggested = suggested
        self.combo.blockSignals(True)
        self.combo.clear()
        shown = [c for c in candidates if c.score >= SUGGESTION_MIN]
        for c in shown:
            self.combo.addItem(f"★ {c.name}   ({int(c.score * 100)} %)", c.party_id)
        if shown:
            self.combo.insertSeparator(self.combo.count())
        if self.allow_new:
            self.combo.addItem(self.new_label, None)
            self.combo.insertSeparator(self.combo.count())
        for p in sorted(self.parties, key=lambda x: x.name.lower()):
            self.combo.addItem(p.name, p.id)
        idx = self.combo.findData(selected_id) if selected_id is not None else (
            self.combo.findData(None) if self.allow_new else 0)
        self.combo.setCurrentIndex(max(0, idx))
        self.combo.blockSignals(False)
        self.new_name.setText(new_name)
        self._selection_changed()

    def _selection_changed(self) -> None:
        is_new = self.allow_new and self.combo.currentData() is None
        self.new_holder.setVisible(is_new)
        self.hint.setText(self._hint_text(is_new))
        self.hint.setObjectName("Warning" if (self._suggested and not is_new and self.party_id() in self._candidates) else "Muted")
        repolish(self.hint)
        repolish(self.combo)
        self.changed.emit()

    def _hint_text(self, is_new: bool) -> str:
        pid = self.party_id()
        if is_new:
            info = self._info
            details = ", ".join(x for x in (info.address, f"{tr('party.vat')} {info.vat_id}" if info and info.vat_id else "",
                                            info.email if info else "", info.ibans[0] if info and info.ibans else "") if x) if info else ""
            if details:
                return tr("party.new_hint", details=details)
            return tr("party.new_hint.none") if not self._candidates else tr("party.none_hint")
        cand = self._candidates.get(pid) if pid is not None else None
        if cand is not None:
            key = "party.suggestion_hint" if self._suggested else "party.sure_hint"
            return tr(key, pct=int(cand.score * 100), reasons=", ".join(tx(r) for r in cand.reasons) or "-")
        return tr("party.manual_hint") if self._candidates else ""

    def _open_chooser(self) -> None:
        dlg = PartyChooserDialog(self.parties, self.party_id(), self)
        if dlg.exec() and dlg.chosen_id is not None:
            self.set_party(dlg.chosen_id)

    # -- value ----------------------------------------------------------------------------------------------
    def party_id(self) -> int | None:
        data = self.combo.currentData()
        return int(data) if data is not None else None

    def set_party(self, party_id: int | None) -> None:
        idx = self.combo.findData(party_id) if party_id is not None else (self.combo.findData(None) if self.allow_new else -1)
        if idx >= 0:
            self.combo.setCurrentIndex(idx)

    def name_for_new(self) -> str:
        return self.new_name.text().strip()

    def role_for_new(self) -> PartyRole | None:
        return PartyRole(self.new_role.currentData()) if self.new_role is not None else None

    def mark(self, low: bool) -> None:
        self.combo.setProperty("lowConfidence", bool(low))
        self.new_name.setProperty("lowConfidence", bool(low))
        repolish(self.combo)
        repolish(self.new_name)
