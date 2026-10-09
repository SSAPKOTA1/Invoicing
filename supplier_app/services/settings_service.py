"""Typed access to settings plus seeded defaults (interest base rates, categories)."""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal, InvalidOperation

from supplier_app.errors import ValidationError
from supplier_app.models.entities import InterestRate
from supplier_app.models.enums import AllocationRule
from supplier_app.repositories.interfaces import Repositories
from supplier_app.services.base import ServiceBase
from supplier_app.services.ledger import RatePoint

#: Bundesbank base rate (Basiszinssatz) history. DEFAULTS TO VERIFY - not legal advice.
DEFAULT_BASE_RATES: list[tuple[date, str]] = [
    (date(2020, 1, 1), "-0.88"), (date(2021, 1, 1), "-0.88"), (date(2022, 1, 1), "-0.88"),
    (date(2022, 7, 1), "-0.88"), (date(2023, 1, 1), "1.62"), (date(2023, 7, 1), "3.12"),
    (date(2024, 1, 1), "3.62"), (date(2024, 7, 1), "3.37"), (date(2025, 1, 1), "2.27"),
    (date(2025, 7, 1), "1.27"),
]

DEFAULT_CATEGORIES = ["Büro", "Material", "Dienstleistung", "Software", "Sonstiges"]

DEFAULTS: dict[str, str] = {
    "theme": "dark",
    "language": "de",
    "debtor_type": "b2b",  # b2b | b2c
    "margin_b2b": "9",
    "margin_b2c": "5",
    "flat_fee_b2b_cents": "4000",
    "flat_fee_b2c_cents": "0",
    "allocation_rule": AllocationRule.STATUTORY.value,
    "default_payment_days": "30",
    "tesseract_path": "",
    "idle_lock_minutes": "10",
    "low_confidence": "0.75",
    "reference_rules": "",
}


class SettingsService(ServiceBase):
    """Reads/writes settings with validation and defaults."""

    def __init__(self, repos: Repositories) -> None:
        super().__init__(repos)

    def get(self, key: str) -> str:
        value = self.repos.settings.get(key)
        if value is None:
            return DEFAULTS.get(key, "")
        return value

    def set(self, key: str, value: str) -> None:
        self.repos.settings.set(key, str(value))

    def get_int(self, key: str) -> int:
        try:
            return int(self.get(key))
        except ValueError:
            return int(DEFAULTS.get(key, "0") or 0)

    def get_decimal(self, key: str) -> Decimal:
        try:
            return Decimal(self.get(key))
        except InvalidOperation:
            return Decimal(DEFAULTS.get(key, "0") or "0")

    # -- typed ---------------------------------------------------------------
    @property
    def theme(self) -> str:
        return "light" if self.get("theme") == "light" else "dark"

    def set_theme(self, theme: str) -> None:
        if theme not in ("dark", "light"):
            raise ValidationError("Unbekanntes Design.")
        self.set("theme", theme)

    @property
    def allocation_rule(self) -> AllocationRule:
        try:
            return AllocationRule(self.get("allocation_rule"))
        except ValueError:
            return AllocationRule.STATUTORY

    @property
    def debtor_type(self) -> str:
        return "b2c" if self.get("debtor_type") == "b2c" else "b2b"

    @property
    def interest_margin(self) -> Decimal:
        return self.get_decimal("margin_b2c" if self.debtor_type == "b2c" else "margin_b2b")

    @property
    def flat_fee_cents(self) -> int:
        return self.get_int("flat_fee_b2c_cents" if self.debtor_type == "b2c" else "flat_fee_b2b_cents")

    @property
    def default_payment_days(self) -> int:
        return max(0, self.get_int("default_payment_days"))

    @property
    def low_confidence(self) -> float:
        try:
            return float(self.get("low_confidence"))
        except ValueError:
            return 0.75

    def rate_points(self) -> list[RatePoint]:
        return [RatePoint(r.valid_from, r.base_rate) for r in self.repos.rates.list()]

    def reference_rules(self) -> dict[str, list[str]]:
        """User-defined extra keywords per reference type (JSON in settings)."""
        raw = self.get("reference_rules")
        if not raw:
            return {}
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return {}
        return {str(k): [str(x) for x in v] for k, v in data.items() if isinstance(v, list)}

    def set_reference_rules(self, rules: dict[str, list[str]]) -> None:
        self.set("reference_rules", json.dumps(rules, ensure_ascii=False))

    def set_rate(self, valid_from: date, base_rate: Decimal) -> None:
        self.repos.rates.upsert(InterestRate(valid_from, base_rate))
        self._audit("set_rate", "interest_rate", None, f"{valid_from} {base_rate}")

    def ensure_defaults(self) -> None:
        """Seed base rates and categories on first start (idempotent)."""
        if not self.repos.rates.list():
            for valid_from, rate in DEFAULT_BASE_RATES:
                self.repos.rates.upsert(InterestRate(valid_from, Decimal(rate)))
        if not self.repos.categories.list():
            for name in DEFAULT_CATEGORIES:
                self.repos.categories.add(name)
