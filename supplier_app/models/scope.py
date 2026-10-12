"""View scope: everything, one company (all its hotels and company-level items) or a single hotel."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Scope:
    """``hotel_id`` set -> only that hotel; else ``company_id`` set -> the company incl. all hotels; else everything."""

    company_id: int | None = None
    hotel_id: int | None = None

    @property
    def is_all(self) -> bool:
        return self.company_id is None and self.hotel_id is None

    def key(self) -> str:
        """Compact form for settings: ``''`` | ``c:3`` | ``h:7`` (hotel implies its company)."""
        if self.hotel_id is not None:
            return f"h:{self.hotel_id}"
        return f"c:{self.company_id}" if self.company_id is not None else ""

    @staticmethod
    def hotel(hotel_id: int, company_id: int) -> Scope:
        return Scope(company_id=company_id, hotel_id=hotel_id)


ALL = Scope()
