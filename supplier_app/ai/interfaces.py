"""Interfaces of the recognition components (a different backend, e.g. an LLM, can implement them)."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence

from .result_types import (
    Classification,
    ExtractedFields,
    ExtractedReference,
    LinkCandidate,
    SenderMatch,
)


class DocumentClassifier(ABC):
    @abstractmethod
    def classify(self, text: str) -> Classification: ...


class FieldExtractor(ABC):
    @abstractmethod
    def extract(self, text: str, classification: Classification) -> ExtractedFields: ...


class ReferenceExtractor(ABC):
    @abstractmethod
    def extract(self, text: str) -> list[ExtractedReference]: ...


class SenderMatcher(ABC):
    @abstractmethod
    def match(self, text: str, fields: ExtractedFields, classification: Classification) -> SenderMatch | None: ...


class LinkMatcher(ABC):
    @abstractmethod
    def match(
        self, text: str, fields: ExtractedFields, classification: Classification, sender: SenderMatch | None
    ) -> Sequence[LinkCandidate]: ...
