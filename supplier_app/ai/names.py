"""Fuzzy comparison of company names: token based, tolerant to OCR errors, generic words count less."""

from __future__ import annotations

import math
import re
from collections import Counter
from collections.abc import Iterable
from difflib import SequenceMatcher

from supplier_app.util.normalize import normalize_name

#: words that appear in many company names and say little about which company it is
GENERIC_WORDS = frozenset("""
hotel hotels restaurant gasthaus gasthof service services dienst dienste dienstleistung dienstleistungen technik handel handels
grosshandel bau bauunternehmen gmbh haus haustechnik verwaltung verwaltungs immobilien vertrieb versand logistik transport
consulting beratung gruppe group holding international deutschland german systems solutions center zentrum werk werke
the and of limited company corp stadt gemeinde kanzlei praxis firma
""".split())

_SHORT = 3


def tokens_of(name: str) -> list[str]:
    return [t for t in normalize_name(name).split() if t]


def _token_match(a: str, b: str) -> float:
    """1.0 identical, up to ~0.8 for typos / one is the beginning of the other, 0 otherwise."""
    if a == b:
        return 1.0
    short, long = (a, b) if len(a) <= len(b) else (b, a)
    if len(short) >= 5 and long.startswith(short):
        return 0.8
    if len(short) >= 5 and abs(len(a) - len(b)) <= 2:
        ratio = SequenceMatcher(None, a, b).ratio()
        if ratio >= 0.79:  # one wrong letter in a word of five (OCR)
            return 0.4 + 0.5 * ratio
    if len(short) >= 7 and SequenceMatcher(None, short, long[: len(short)]).ratio() >= 0.9:
        return 0.7  # the beginning of the longer word with an OCR error
    return 0.0


class NameWeights:
    """Inverse document frequency of the name tokens of the master data (``stadtwerke`` is rarer than ``hotel``)."""

    def __init__(self, names: Iterable[str] = ()) -> None:
        names = list(names)
        self._df: Counter[str] = Counter()
        for n in names:
            self._df.update(set(tokens_of(n)))
        self._n = max(1, len(names))

    def weight(self, token: str) -> float:
        base = max(1.0, min(12.0, float(len(token))))
        idf = 1.0 + math.log(1 + self._n / (1 + self._df.get(token, 0))) / 2
        if token in GENERIC_WORDS:
            base *= 0.25
        if token.isdigit():
            base *= 0.6
        return base * idf


def similarity(a: str, b: str, weights: NameWeights | None = None) -> float:
    """0..1: how well do two printed names describe the same company?"""
    weights = weights or NameWeights()
    ta, tb = tokens_of(a), tokens_of(b)
    if not ta or not tb:
        return 0.0
    if ta == tb:
        return 1.0
    wa = {t: weights.weight(t) for t in ta}
    wb = {t: weights.weight(t) for t in tb}
    total_a, total_b = sum(wa.values()), sum(wb.values())

    def covered(src: list[str], dst: list[str], w_src: dict[str, float]) -> float:
        got = 0.0
        for t in src:
            best = max((_token_match(t, u) for u in dst), default=0.0)
            got += w_src[t] * best
        return got

    cov_a = covered(ta, tb, wa) / total_a  # share of a that is found in b
    cov_b = covered(tb, ta, wb) / total_b
    joined = SequenceMatcher(None, "".join(ta), "".join(tb)).ratio()
    token_score = max(0.7 * cov_b + 0.3 * cov_a, 0.7 * cov_a + 0.3 * cov_b)
    if len(ta) == 1 or len(tb) == 1:  # a single word is weak evidence ("Meier" would fit every "Meier & Söhne")
        token_score = min(token_score, 0.8)
    return max(token_score, joined if joined >= 0.88 else 0.0)


def contains_name(haystack: str, name: str) -> bool:
    """Is the (normalised) name a whole-word sequence inside the (normalised) text?"""
    h, n = f" {normalize_name(haystack)} ", normalize_name(name)
    return bool(n) and len(n) >= 4 and f" {n} " in h


def squash(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", normalize_name(text))
