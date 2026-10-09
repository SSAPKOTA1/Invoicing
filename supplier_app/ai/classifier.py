"""Keyword/pattern scoring classifier."""

from __future__ import annotations

import re

from supplier_app.models.enums import DocumentType

from .interfaces import DocumentClassifier
from .result_types import Classification
from .rules import CLASSIFIER_RULES, TITLE_BONUS, TITLE_LINES


class KeywordClassifier(DocumentClassifier):
    """Scores every document type from weighted regexes; title-zone hits count more."""

    def __init__(self, rules: dict[DocumentType, list[tuple[str, float]]] | None = None) -> None:
        self._rules = {
            dtype: [(re.compile(rx, re.I | re.M), w) for rx, w in patterns]
            for dtype, patterns in (rules or CLASSIFIER_RULES).items()
        }

    def classify(self, text: str) -> Classification:
        title_zone = "\n".join(text.splitlines()[:TITLE_LINES])
        scores: dict[str, float] = {}
        reasons: dict[str, list[str]] = {}
        for dtype, patterns in self._rules.items():
            total = 0.0
            hits: list[str] = []
            for rx, weight in patterns:
                m = rx.search(text)
                if not m:
                    continue
                contribution = weight * (TITLE_BONUS if rx.search(title_zone) else 1.0)
                total += contribution
                hits.append(f"'{m.group(0).strip()[:40]}' (+{contribution:g})")
            scores[dtype.value] = total
            reasons[dtype.value] = hits
        ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
        top_name, top = ranked[0]
        second = ranked[1][1] if len(ranked) > 1 else 0.0
        if top < 2.0:
            return Classification(DocumentType.OTHER, 0.2 if text.strip() else 0.0, scores, ["Keine eindeutigen Schlüsselwörter"])
        margin = (top - second) / max(top * 0.6, 1.0)
        confidence = min(1.0, top / 6.0) * (0.55 + 0.45 * min(1.0, margin))
        return Classification(DocumentType(top_name), round(confidence, 3), scores, reasons[top_name])
