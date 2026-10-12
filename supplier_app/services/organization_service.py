"""Own companies (Gesellschaften) and hotels; scope helpers used by every screen."""

from __future__ import annotations

from dataclasses import dataclass

from supplier_app.errors import NotFoundError, ValidationError
from supplier_app.i18n import tx
from supplier_app.models.entities import Company, Hotel
from supplier_app.models.scope import ALL, Scope
from supplier_app.repositories.interfaces import Repositories
from supplier_app.services.base import ServiceBase, atomic
from supplier_app.util.normalize import normalize_name


@dataclass(frozen=True)
class ScopeChoice:
    """One entry of the scope selector: indentation level 0 (all), 1 (company) or 2 (hotel)."""

    scope: Scope
    label: str
    level: int


class OrganizationService(ServiceBase):
    def __init__(self, repos: Repositories) -> None:
        super().__init__(repos)

    # -- companies ------------------------------------------------------------------------
    @atomic
    def create_company(self, name: str, notes: str = "") -> Company:
        if not name.strip():
            raise ValidationError("Bitte einen Namen für die Gesellschaft angeben.")
        with self.repos.transaction():
            company = self.repos.organization.add_company(Company(name=name.strip(), notes=notes))
            self._audit("create", "company", company.id, company.name)
        return company

    def rename_company(self, company_id: int, name: str, notes: str | None = None) -> Company:
        company = self.company(company_id)
        company.name = name.strip()
        if notes is not None:
            company.notes = notes
        self.repos.organization.update_company(company)
        self._audit("update", "company", company_id, company.name)
        return company

    @atomic
    def delete_company(self, company_id: int) -> None:
        self.repos.organization.delete_company(company_id)
        self._audit("delete", "company", company_id)

    def company(self, company_id: int) -> Company:
        company = self.repos.organization.get_company(company_id)
        if company is None:
            raise NotFoundError("Gesellschaft nicht gefunden.")
        return company

    def companies(self) -> list[Company]:
        return self.repos.organization.companies()

    # -- hotels ------------------------------------------------------------------------------
    @atomic
    def create_hotel(self, company_id: int, name: str, notes: str = "") -> Hotel:
        self.company(company_id)
        if not name.strip():
            raise ValidationError("Bitte einen Namen für das Hotel angeben.")
        with self.repos.transaction():
            hotel = self.repos.organization.add_hotel(Hotel(name=name.strip(), company_id=company_id, notes=notes))
            self._audit("create", "hotel", hotel.id, hotel.name)
        return hotel

    def rename_hotel(self, hotel_id: int, name: str, notes: str | None = None) -> Hotel:
        hotel = self.hotel(hotel_id)
        hotel.name = name.strip()
        if notes is not None:
            hotel.notes = notes
        self.repos.organization.update_hotel(hotel)
        self._audit("update", "hotel", hotel_id, hotel.name)
        return hotel

    @atomic
    def delete_hotel(self, hotel_id: int) -> None:
        self.repos.organization.delete_hotel(hotel_id)
        self._audit("delete", "hotel", hotel_id)

    def hotel(self, hotel_id: int) -> Hotel:
        hotel = self.repos.organization.get_hotel(hotel_id)
        if hotel is None:
            raise NotFoundError("Hotel nicht gefunden.")
        return hotel

    def hotels(self, company_id: int | None = None) -> list[Hotel]:
        return self.repos.organization.hotels(company_id)

    @property
    def configured(self) -> bool:
        return bool(self.repos.organization.companies())

    # -- scope ------------------------------------------------------------------------------------
    def resolve(self, company_id: int | None, hotel_id: int | None) -> tuple[int | None, int | None]:
        """Assigning a hotel fills in its company; a company alone is allowed; a mismatch is rejected."""
        if hotel_id is not None:
            hotel = self.hotel(hotel_id)
            if company_id is not None and company_id != hotel.company_id:
                raise ValidationError("Das Hotel gehört nicht zur gewählten Gesellschaft.")
            return hotel.company_id, hotel_id
        if company_id is not None:
            self.company(company_id)
        return company_id, None

    def scope_for(self, company_id: int | None, hotel_id: int | None) -> Scope:
        company_id, hotel_id = self.resolve(company_id, hotel_id)
        return Scope(company_id, hotel_id)

    def scope_from_key(self, key: str) -> Scope:
        """Inverse of :meth:`Scope.key`; unknown or deleted entries fall back to 'everything'."""
        try:
            kind, _, raw = key.partition(":")
            if kind == "h":
                hotel = self.repos.organization.get_hotel(int(raw))
                return Scope(hotel.company_id, hotel.id) if hotel else ALL
            if kind == "c":
                company = self.repos.organization.get_company(int(raw))
                return Scope(company.id) if company else ALL
        except ValueError:
            return ALL
        return ALL

    def label(self, scope: Scope | None) -> str:
        if scope is None or scope.is_all:
            return tx("Alle Gesellschaften")
        if scope.hotel_id is not None:
            hotel = self.repos.organization.get_hotel(scope.hotel_id)
            company = self.repos.organization.get_company(hotel.company_id) if hotel else None
            return f"{company.name} / {hotel.name}" if hotel and company else tx("Hotel")
        company = self.repos.organization.get_company(scope.company_id or 0)
        return tx(f"{company.name} (alle Hotels)") if company else tx("Gesellschaft")

    def item_label(self, company_id: int | None, hotel_id: int | None) -> str:
        """Short text for tables: ``Hotel (Firma)``, ``Firma`` or ``–``."""
        if hotel_id is not None:
            hotel = self.repos.organization.get_hotel(hotel_id)
            company = self.repos.organization.get_company(hotel.company_id) if hotel else None
            return f"{hotel.name} ({company.name})" if hotel and company else "–"
        if company_id is not None:
            company = self.repos.organization.get_company(company_id)
            return company.name if company else "–"
        return "–"

    def choices(self) -> list[ScopeChoice]:
        out = [ScopeChoice(ALL, tx("Alle Gesellschaften"), 0)]
        hotels = self.repos.organization.hotels()
        for company in self.companies():
            out.append(ScopeChoice(Scope(company.id), tx(f"{company.name} (alle Hotels)"), 1))
            out.extend(ScopeChoice(Scope(company.id, h.id), h.name, 2) for h in hotels if h.company_id == company.id)
        return out

    def detect_in_text(self, text: str) -> tuple[int | None, int | None]:
        """Guess the addressed hotel/company from the recipient part of a document (names found in the text)."""
        haystack = f" {normalize_name(text)} "
        for hotel in self.repos.organization.hotels():
            needle = normalize_name(hotel.name)
            if len(needle) >= 4 and f" {needle} " in haystack:
                return hotel.company_id, hotel.id
        for company in self.companies():
            needle = normalize_name(company.name)
            if len(needle) >= 4 and f" {needle} " in haystack:
                return company.id, None
        return None, None
