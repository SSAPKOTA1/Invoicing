"""Builders shared by service tests."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from supplier_app.models.entities import Invoice, Party
from supplier_app.models.enums import PartyRole
from supplier_app.services.container import Services


@dataclass
class Scenario:
    supplier: Party
    agency: Party
    invoice: Invoice


def make_scenario(svc: Services, gross: int = 100000, number: str = "RE-2024/001") -> Scenario:
    supplier = svc.suppliers.create(Party(
        name="Müller Bürobedarf GmbH", aliases=["Mueller Buero"], ibans=["DE89370400440532013000"],
        vat_id="DE123456789"))
    agency = svc.suppliers.create(Party(
        name="Inkasso Schmidt & Partner", role=PartyRole.COLLECTION_AGENCY, represents_supplier_id=supplier.id))
    invoice = svc.invoices.create_invoice(
        supplier.id, number, date(2024, 1, 10), gross_cents=gross, due_date=date(2024, 2, 9))
    return Scenario(supplier, agency, invoice)
