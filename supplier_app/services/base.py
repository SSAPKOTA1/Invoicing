"""Common service plumbing."""

from __future__ import annotations

import logging
from datetime import date

from supplier_app.models.entities import AuditLogEntry
from supplier_app.repositories.interfaces import Repositories


class ServiceBase:
    """Holds the repositories and offers audit logging."""

    def __init__(self, repos: Repositories) -> None:
        self.repos = repos
        self.log = logging.getLogger(type(self).__module__)

    def _audit(self, action: str, entity: str, entity_id: int | None, details: str = "") -> None:
        self.repos.audit.add(AuditLogEntry(action=action, entity=entity, entity_id=entity_id, details=details))


def today() -> date:
    return date.today()
