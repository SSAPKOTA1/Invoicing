from __future__ import annotations

import json
import re
from pathlib import Path

from supplier_app.i18n import all_keys, set_language, tr

ROOT = Path(__file__).resolve().parents[1] / "supplier_app"


def test_all_literal_translation_keys_exist() -> None:
    keys = all_keys("de")
    missing: set[str] = set()
    for path in ROOT.rglob("*.py"):
        for m in re.finditer(r"""\btr\(\s*(f?)(["'])(.+?)\2""", path.read_text(encoding="utf-8")):
            if not m.group(1) and not m.group(3).endswith("."):
                if m.group(3) not in keys:
                    missing.add(f"{path.name}: {m.group(3)}")
    assert not missing, sorted(missing)


def test_dynamic_enum_keys_exist() -> None:
    from supplier_app.models.enums import (
        AllocationComponent,
        AllocationRule,
        CaseStatus,
        DocumentType,
        InvoiceStatus,
        LedgerEntryType,
        PartyRole,
        PaymentMethod,
        ReferenceType,
        ReviewStatus,
    )
    keys = all_keys("de")
    for prefix, enum in (("entry", LedgerEntryType), ("status", InvoiceStatus), ("case", CaseStatus),
                         ("doctype", DocumentType), ("review", ReviewStatus), ("role", PartyRole), ("ref", ReferenceType),
                         ("method", PaymentMethod), ("component", AllocationComponent), ("rule", AllocationRule)):
        for member in enum:
            assert f"{prefix}.{member.value}" in keys, f"{prefix}.{member.value}"
    for lv in range(1, 7):
        assert f"level.{lv}" in keys
    for b in ("not_due", "1-30", "31-60", "61-90", "90+"):
        assert f"aging.{b}" in keys
    for k in ("month", "quarter", "year", "custom"):
        assert f"dash.period.{k}" in keys
    for k in ("total_open", "overdue", "due_7", "due_14", "due_30", "paid_period", "charges", "claim_diff", "credits",
              "open_cases", "escalated_cases", "docs_review"):
        assert f"dash.kpi.{k}" in keys


def test_tr_fallbacks_and_formatting() -> None:
    assert tr("does.not.exist") == "does.not.exist"
    assert tr("drill.count", n=3) == "3 Einträge"
    assert tr("drill.count") == "{n} Einträge"
    set_language("en")
    assert tr("app.title") == "Supplier Ledger & Dunning Tracker"
    assert tr("nav.dashboard") == "Übersicht"  # falls back to German
    set_language("xx")
    assert tr("nav.dashboard") == "Übersicht"
    set_language("de")
    json.loads((ROOT / "i18n" / "de.json").read_text(encoding="utf-8"))
