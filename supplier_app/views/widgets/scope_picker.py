"""Company + hotel selector for forms: choosing a hotel fills in its company, a company alone is allowed."""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QComboBox, QHBoxLayout, QWidget

from supplier_app.i18n import tr
from supplier_app.services.organization_service import OrganizationService


class ScopePicker(QWidget):
    changed = Signal()

    def __init__(self, org: OrganizationService, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.org = org
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.company = QComboBox()
        self.hotel = QComboBox()
        self.company.setMinimumWidth(190)
        self.hotel.setMinimumWidth(190)
        lay.addWidget(self.company, 1)
        lay.addWidget(self.hotel, 1)
        self._fill_companies()
        self._fill_hotels(None, None)
        self.company.activated.connect(self._company_chosen)
        self.hotel.activated.connect(self._hotel_chosen)
        self.setVisible(org.configured)

    def reload(self) -> None:
        """Re-read companies/hotels (they can change in the settings while the form lives on)."""
        company_id, hotel_id = self.company_id, self.hotel_id
        self._fill_companies()
        self.set_values(company_id, hotel_id)
        self.setVisible(self.org.configured)

    # -- values ------------------------------------------------------------------------------------------
    @property
    def company_id(self) -> int | None:
        return self.company.currentData()

    @property
    def hotel_id(self) -> int | None:
        return self.hotel.currentData()

    def set_values(self, company_id: int | None, hotel_id: int | None) -> None:
        if hotel_id is not None and company_id is None:
            company_id = self.org.hotel(hotel_id).company_id
        self.company.setCurrentIndex(max(0, self.company.findData(company_id)))
        self._fill_hotels(company_id, hotel_id)

    # -- internals -------------------------------------------------------------------------------------------------
    def _fill_companies(self) -> None:
        self.company.clear()
        self.company.addItem(tr("org.no_company"), None)
        for c in self.org.companies():
            self.company.addItem(c.name, c.id)

    def _fill_hotels(self, company_id: int | None, hotel_id: int | None) -> None:
        self.hotel.clear()
        self.hotel.addItem(tr("org.no_hotel"), None)
        names = {c.id: c.name for c in self.org.companies()}
        for h in self.org.hotels(company_id):
            self.hotel.addItem(h.name if company_id else f"{h.name} ({names.get(h.company_id, '')})", h.id)
        self.hotel.setCurrentIndex(max(0, self.hotel.findData(hotel_id)))

    def _company_chosen(self, _index: int) -> None:
        self._fill_hotels(self.company_id, None)
        self.changed.emit()

    def _hotel_chosen(self, _index: int) -> None:
        if self.hotel_id is not None:
            self.set_values(None, self.hotel_id)
        self.changed.emit()
