"""Translation lookup.

All user-visible UI strings live in ``<language>.json`` (German is the master, English is complete). Texts that the program
code produces itself (error messages, warnings, report headings, booking texts) are written in German in the code and are
translated by :func:`tx` with the catalogue in :mod:`supplier_app.i18n.messages`.
"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

_DIR = Path(__file__).parent
_language = "de"

#: languages offered in the settings: code -> name in its own language
LANGUAGES: dict[str, str] = {"de": "Deutsch", "en": "English"}


@lru_cache(maxsize=4)
def _load(language: str) -> dict[str, str]:
    path = _DIR / f"{language}.json"
    if not path.exists():
        return {}
    with path.open(encoding="utf-8") as fh:
        data = json.load(fh)
    return {str(k): str(v) for k, v in data.items()}


def set_language(language: str) -> None:
    global _language
    _language = language if (_DIR / f"{language}.json").exists() else "de"


def current_language() -> str:
    return _language


def tr(key: str, **kwargs: object) -> str:
    """Translate ``key``; falls back to German, then to the key itself."""
    text = _load(_language).get(key) or _load("de").get(key) or key
    if kwargs:
        try:
            return text.format(**kwargs)
        except (KeyError, IndexError, ValueError):
            return text
    return text


def all_keys(language: str = "de") -> set[str]:
    return set(_load(language))


def level_label(level: int) -> str:
    return tr(f"level.{int(level)}")


_PLACEHOLDER = re.compile(r"\{(\w+)\}")


@lru_cache(maxsize=4)
def _catalogue(language: str) -> tuple[dict[str, str], list[tuple[re.Pattern[str], str]]]:
    """(exact texts, [(pattern, English template)]) for the German program texts of ``language``."""
    if language != "en":
        return {}, []
    from supplier_app.i18n.messages import EN

    exact: dict[str, str] = {}
    patterns: list[tuple[int, re.Pattern[str], str]] = []
    for german, english in EN.items():
        parts = _PLACEHOLDER.split(german)  # literal, name, literal, name, ... literal
        if len(parts) == 1:
            exact[german] = english
            continue
        rx = "".join(re.escape(p) if i % 2 == 0 else f"(?P<{p}>.+?)" for i, p in enumerate(parts))
        patterns.append((sum(len(p) for p in parts[::2]), re.compile(f"^{rx}$", re.DOTALL), english))
    patterns.sort(key=lambda item: -item[0])  # the most specific (longest fixed text) first
    return exact, [(rx, english) for _n, rx, english in patterns]


@lru_cache(maxsize=16384)
def _tx(language: str, text: str) -> str:
    exact, patterns = _catalogue(language)
    hit = exact.get(text)
    if hit is not None:
        return hit
    for rx, english in patterns:
        match = rx.match(text)
        if match:  # the variable parts may be German texts as well (e.g. "alle Lieferanten")
            return english.format_map({k: _tx(language, v) for k, v in match.groupdict().items()})
    return text


def tx(text: str | None) -> str:
    """Translate a German text that the program code produced (see :mod:`supplier_app.i18n.messages`).

    German (and every text that is not in the catalogue, e.g. already English or a name) is returned unchanged."""
    if not text or _language == "de":
        return text or ""
    return _tx(_language, text)
