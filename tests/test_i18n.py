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


def _placeholders(text: str) -> list[str]:
    return sorted(re.findall(r"\{\w+\}", text))


def test_english_is_complete_and_keeps_placeholders() -> None:
    de, en = all_keys("de"), all_keys("en")
    assert de == en, f"missing in en: {sorted(de - en)}, extra in en: {sorted(en - de)}"
    texts_de = json.loads((ROOT / "i18n" / "de.json").read_text(encoding="utf-8"))
    texts_en = json.loads((ROOT / "i18n" / "en.json").read_text(encoding="utf-8"))
    for key, german in texts_de.items():
        assert _placeholders(german) == _placeholders(texts_en[key]), key
        assert texts_en[key].strip(), key
    # no German leftovers (umlauts) in the English texts except where the word is a proper German term
    leftovers = {k: v for k, v in texts_en.items() if re.search("[äöüß]", v)}
    assert set(leftovers) <= {"settings.vocab.hint"}, leftovers


def test_tr_fallbacks_and_formatting() -> None:
    assert tr("does.not.exist") == "does.not.exist"
    assert tr("drill.count", n=3) == "3 Einträge"
    assert tr("drill.count") == "{n} Einträge"
    set_language("en")
    assert tr("app.title") == "Supplier Ledger & Dunning Tracker"
    assert tr("nav.dashboard") == "Overview"
    assert tr("drill.count", n=3) == "3 entries"
    assert tr("does.not.exist") == "does.not.exist"
    set_language("xx")  # unknown language -> German
    assert tr("nav.dashboard") == "Übersicht"
    set_language("de")
    json.loads((ROOT / "i18n" / "de.json").read_text(encoding="utf-8"))


def test_program_texts_are_translated_only_in_english() -> None:
    from supplier_app.errors import ValidationError
    from supplier_app.i18n import tx

    assert tx("Rechnung nicht gefunden.") == "Rechnung nicht gefunden."  # German stays German
    set_language("en")
    try:
        assert tx("Rechnung nicht gefunden.") == "Invoice not found."
        assert tx("Zuordnung von 1,00 € übersteigt den offenen Betrag (0,50 €) der Rechnung.") == (
            "Allocation of 1,00 € exceeds the open amount (0,50 €) of the invoice.")
        assert tx("Offene Posten – alle Lieferanten") == "Open items – all suppliers"  # variable parts are translated too
        assert tx("Müller GmbH") == "Müller GmbH" and tx("") == ""  # names and unknown texts are untouched
        assert ValidationError("Der Port muss zwischen 1 und 65535 liegen.").message == "The port must be between 1 and 65535."
    finally:
        set_language("de")


def test_every_error_message_in_the_code_has_an_english_text() -> None:
    """All literal messages of ``raise XyzError(...)`` / ``XyzError(...)`` are in the catalogue."""
    import ast

    from supplier_app.i18n import messages, tx

    placeholder = re.compile(r"\{\w+\}")
    patterns = []
    for german in messages.EN:
        parts = placeholder.split(german)
        patterns.append(re.compile("^" + "(?:.+?)".join(re.escape(p) for p in parts) + "$", re.DOTALL))
    missing: list[str] = []
    for path in ROOT.rglob("*.py"):
        if path.parts[-2] == "i18n":
            continue
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id.endswith("Error") and node.args):
                continue
            arg = node.args[0]
            if isinstance(arg, ast.JoinedStr):
                text = "".join(str(v.value) if isinstance(v, ast.Constant) else "{x}" for v in arg.values)
            elif isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                text = arg.value
            else:
                continue
            if node.func.id in ("ValueError", "RuntimeError", "TypeError", "KeyError", "OSError", "AssertionError"):
                continue
            if not re.search(r"[A-Za-zÄÖÜäöüß]{3}", text) or not any(p.match(text) for p in patterns):
                missing.append(f"{path.name}:{node.lineno}: {text[:70]}")
    assert not missing, "\n".join(missing)
    assert tx  # imported for completeness


def test_saved_language_survives_other_preferences(tmp_path) -> None:
    from supplier_app.settings.local_prefs import LocalPrefs, saved_language

    first, second = LocalPrefs(tmp_path / "prefs.json"), LocalPrefs(tmp_path / "prefs.json")
    first.set("language", "en")
    second.set("theme", "light")  # an older instance must not overwrite the language
    assert saved_language(tmp_path) == "en" and LocalPrefs(tmp_path / "prefs.json").get("theme") == "light"
    assert saved_language(tmp_path / "nothing-here") == ""
