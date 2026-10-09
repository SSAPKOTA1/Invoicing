"""Translation lookup. All user-visible UI strings live in ``de.json`` (en.json holds the English start of a second language)."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

_DIR = Path(__file__).parent
_language = "de"


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
