"""Common service plumbing."""

from __future__ import annotations

import functools
import logging
from collections.abc import Callable
from datetime import date
from typing import Any, TypeVar

from supplier_app.models.entities import AuditLogEntry
from supplier_app.repositories.interfaces import Repositories

F = TypeVar("F", bound=Callable[..., Any])


def atomic(func: F) -> F:
    """Run a service operation as one unit: the global write lock is taken *before* anything is read, so that
    balances, allocations and duplicate checks cannot be overtaken by another user working at the same moment."""

    @functools.wraps(func)
    def wrapper(self: Any, *args: Any, **kwargs: Any) -> Any:
        with self.repos.transaction():
            return func(self, *args, **kwargs)

    return wrapper  # type: ignore[return-value]


class ServiceBase:
    """Holds the repositories and offers audit logging."""

    def __init__(self, repos: Repositories) -> None:
        self.repos = repos
        self.log = logging.getLogger(type(self).__module__)

    def _audit(self, action: str, entity: str, entity_id: int | None, details: str = "") -> None:
        self.repos.audit.add(AuditLogEntry(action=action, entity=entity, entity_id=entity_id, details=details))


def today() -> date:
    return date.today()
