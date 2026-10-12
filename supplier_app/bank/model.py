"""What a parser returns: neutral, format independent statement data."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date


@dataclass
class ParsedTransaction:
    booking_date: date
    amount_cents: int  # negative = money out
    value_date: date | None = None
    currency: str = "EUR"
    counterparty_name: str = ""
    counterparty_iban: str = ""
    purpose: str = ""
    booking_text: str = ""
    reference: str = ""


@dataclass
class ParsedStatement:
    format: str  # 'csv' | 'camt053' | 'mt940' | 'pdf'
    transactions: list[ParsedTransaction] = field(default_factory=list)
    account_iban: str = ""  # own account, when the file says so
    account_label: str = ""  # other hint (bank code/account number) when there is no IBAN
    bic: str = ""
    opening_cents: int | None = None
    closing_cents: int | None = None
    warnings: list[str] = field(default_factory=list)

    @property
    def date_from(self) -> date | None:
        return min((t.booking_date for t in self.transactions), default=None)

    @property
    def date_to(self) -> date | None:
        return max((t.booking_date for t in self.transactions), default=None)
