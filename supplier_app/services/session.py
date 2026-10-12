"""The logged-in user of the multi-user mode and what the role allows."""

from __future__ import annotations

from dataclasses import dataclass

from supplier_app.models.entities import AppUser
from supplier_app.models.enums import UserRole


@dataclass
class Session:
    """Local mode has no login: everybody is the administrator of their own data."""

    user: AppUser | None = None
    multi_user: bool = False

    @property
    def username(self) -> str:
        return self.user.username if self.user else ""

    @property
    def label(self) -> str:
        return self.user.label if self.user else ""

    @property
    def role(self) -> UserRole:
        return self.user.role if self.user else UserRole.ADMIN

    @property
    def is_admin(self) -> bool:
        return self.role == UserRole.ADMIN

    @property
    def can_write(self) -> bool:
        return self.role != UserRole.VIEWER
