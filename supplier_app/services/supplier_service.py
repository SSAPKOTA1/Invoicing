"""Suppliers, collection agencies and other parties."""

from __future__ import annotations

from supplier_app.errors import NotFoundError, ValidationError
from supplier_app.models.entities import Party
from supplier_app.models.enums import PartyRole
from supplier_app.repositories.interfaces import Repositories
from supplier_app.services.base import ServiceBase
from supplier_app.util.normalize import normalize_iban, valid_iban, valid_vat_id


class SupplierService(ServiceBase):
    def __init__(self, repos: Repositories) -> None:
        super().__init__(repos)

    def _validate(self, party: Party) -> None:
        if not party.name.strip():
            raise ValidationError("Bitte einen Namen angeben.")
        for iban in party.ibans:
            if iban.strip() and not valid_iban(iban):
                raise ValidationError(f"Die IBAN '{iban}' ist ungültig (Prüfsumme).")
        if party.vat_id.strip() and not valid_vat_id(party.vat_id):
            raise ValidationError(f"Die USt-IdNr. '{party.vat_id}' hat ein ungültiges Format.")
        if party.represents_supplier_id is not None:
            if party.role != PartyRole.COLLECTION_AGENCY:
                raise ValidationError("Nur ein Inkassobüro kann einen Lieferanten vertreten.")
            if self.repos.parties.get(party.represents_supplier_id) is None:
                raise ValidationError("Der vertretene Lieferant existiert nicht.")

    def create(self, party: Party) -> Party:
        self._validate(party)
        party.ibans = [normalize_iban(i) for i in party.ibans if i.strip()]
        with self.repos.transaction():
            created = self.repos.parties.add(party)
            self._audit("create", "party", created.id, created.name)
        return created

    def update(self, party: Party) -> None:
        self._validate(party)
        party.ibans = [normalize_iban(i) for i in party.ibans if i.strip()]
        with self.repos.transaction():
            self.repos.parties.update(party)
            self._audit("update", "party", party.id, party.name)

    def get(self, party_id: int) -> Party:
        party = self.repos.parties.get(party_id)
        if party is None:
            raise NotFoundError("Partei nicht gefunden.")
        return party

    def list(self, role: PartyRole | None = None) -> list[Party]:
        return self.repos.parties.list(role)

    def suppliers(self) -> list[Party]:
        return self.repos.parties.list(PartyRole.SUPPLIER)

    def delete(self, party_id: int) -> None:
        with self.repos.transaction():
            self.repos.parties.delete(party_id)
            self._audit("delete", "party", party_id)

    def add_alias(self, party_id: int, alias: str) -> None:
        party = self.get(party_id)
        if alias.strip() and alias.strip() not in party.aliases:
            party.aliases.append(alias.strip())
            self.repos.parties.update(party)

    def add_iban(self, party_id: int, iban: str) -> None:
        party = self.get(party_id)
        if not valid_iban(iban):
            raise ValidationError(f"Die IBAN '{iban}' ist ungültig (Prüfsumme).")
        if normalize_iban(iban) not in party.ibans:
            party.ibans.append(normalize_iban(iban))
            self.repos.parties.update(party)

    def supplier_for(self, party: Party) -> Party | None:
        """The supplier whose ledger a letter from ``party`` belongs to."""
        if party.role == PartyRole.COLLECTION_AGENCY:
            return self.repos.parties.get(party.represents_supplier_id) if party.represents_supplier_id else None
        return party
