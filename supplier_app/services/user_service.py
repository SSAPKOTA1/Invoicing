"""Users of the multi-user mode: accounts, passwords (scrypt), roles, lockout after failed logins."""

from __future__ import annotations

import hashlib
import hmac
import os
from collections.abc import Callable
from datetime import datetime, timedelta

from supplier_app.errors import AuthError, NotFoundError, ValidationError
from supplier_app.models.entities import AppUser
from supplier_app.models.enums import UserRole
from supplier_app.repositories.interfaces import Repositories
from supplier_app.services.base import ServiceBase, atomic
from supplier_app.services.session import Session

MIN_PASSWORD = 8
MAX_ATTEMPTS = 5
LOCKOUT_SECONDS = 30
_SCRYPT = {"n": 2**14, "r": 8, "p": 1, "maxmem": 64 * 1024 * 1024, "dklen": 32}


def hash_password(password: str, salt: bytes) -> str:
    return hashlib.scrypt(password.encode("utf-8"), salt=salt, **_SCRYPT).hex()  # type: ignore[arg-type]


class UserService(ServiceBase):
    """Accounts; ``session`` is filled by :meth:`login` and read by the rest of the application."""

    def __init__(self, repos: Repositories, session: Session, clock: Callable[[], datetime] = datetime.now) -> None:
        super().__init__(repos)
        self.session = session
        self._clock = clock

    # -- queries ---------------------------------------------------------------------------------
    def users(self) -> list[AppUser]:
        return self.repos.users.list()

    def needs_first_admin(self) -> bool:
        return self.repos.users.count() == 0

    def get(self, user_id: int) -> AppUser:
        user = self.repos.users.get(user_id)
        if user is None:
            raise NotFoundError("Benutzer nicht gefunden.")
        return user

    # -- validation ------------------------------------------------------------------------------------
    @staticmethod
    def _check_password(password: str) -> None:
        if len(password) < MIN_PASSWORD:
            raise ValidationError(f"Das Passwort muss mindestens {MIN_PASSWORD} Zeichen lang sein.")

    def _active_admins(self, excluding: int | None = None) -> int:
        return sum(1 for u in self.repos.users.list() if u.role == UserRole.ADMIN and u.active and u.id != excluding)

    def _require_admin(self) -> None:
        if self.session.multi_user and not self.session.is_admin:
            raise AuthError("Nur Administratoren dürfen Benutzer verwalten.")

    # -- accounts ----------------------------------------------------------------------------------------
    @atomic
    def create_user(self, username: str, password: str, role: UserRole = UserRole.EDITOR, display_name: str = "") -> AppUser:
        username = username.strip()
        if not self.needs_first_admin():
            self._require_admin()
        if len(username) < 2 or any(c.isspace() for c in username):
            raise ValidationError("Der Benutzername muss mindestens 2 Zeichen haben und darf keine Leerzeichen enthalten.")
        self._check_password(password)
        salt = os.urandom(16)
        user = AppUser(username=username, role=role, display_name=display_name.strip(), password_salt=salt.hex(),
                       password_hash=hash_password(password, salt))
        with self.repos.transaction():
            user = self.repos.users.add(user)
            self._audit("create", "user", user.id, f"{username} ({role.value})")
        return user

    @atomic
    def update_user(self, user_id: int, *, role: UserRole | None = None, display_name: str | None = None,
                    active: bool | None = None) -> AppUser:
        self._require_admin()
        user = self.get(user_id)
        new_role = role if role is not None else user.role
        new_active = user.active if active is None else active
        if user.role == UserRole.ADMIN and user.active and (new_role != UserRole.ADMIN or not new_active) \
                and self._active_admins(excluding=user.id) == 0:
            raise ValidationError("Es muss mindestens ein aktiver Administrator vorhanden bleiben.")
        user.role, user.active = new_role, new_active
        if display_name is not None:
            user.display_name = display_name.strip()
        self.repos.users.update(user)
        self._audit("update", "user", user.id, f"{user.username} ({user.role.value}, {'aktiv' if user.active else 'gesperrt'})")
        return user

    @atomic
    def delete_user(self, user_id: int) -> None:
        self._require_admin()
        user = self.get(user_id)
        if self.session.user is not None and self.session.user.id == user_id:
            raise ValidationError("Sie können sich nicht selbst löschen.")
        if user.role == UserRole.ADMIN and user.active and self._active_admins(excluding=user_id) == 0:
            raise ValidationError("Es muss mindestens ein aktiver Administrator vorhanden bleiben.")
        self.repos.users.delete(user_id)
        self._audit("delete", "user", user_id, user.username)

    def reset_password(self, user_id: int, new_password: str) -> None:
        """Administrator sets a new password (and lifts a lockout)."""
        self._require_admin()
        self._check_password(new_password)
        self._store_password(self.get(user_id), new_password)
        self._audit("reset_password", "user", user_id)

    def change_password(self, user_id: int, old_password: str, new_password: str) -> None:
        user = self.get(user_id)
        if not self._matches(user, old_password):
            raise AuthError("Das aktuelle Passwort ist falsch.")
        self._check_password(new_password)
        self._store_password(user, new_password)
        self._audit("change_password", "user", user_id)

    def _store_password(self, user: AppUser, password: str) -> None:
        salt = os.urandom(16)
        user.password_salt, user.password_hash = salt.hex(), hash_password(password, salt)
        user.failed_logins, user.locked_until = 0, ""
        self.repos.users.update(user)

    @staticmethod
    def _matches(user: AppUser, password: str) -> bool:
        return hmac.compare_digest(hash_password(password, bytes.fromhex(user.password_salt)), user.password_hash)

    # -- login ---------------------------------------------------------------------------------------------------
    def lockout_seconds_left(self, user: AppUser) -> int:
        if not user.locked_until:
            return 0
        left = (datetime.fromisoformat(user.locked_until) - self._clock()).total_seconds()
        return max(0, int(left + 0.999))

    def verify(self, username: str, password: str) -> AppUser:
        """Check credentials. Raises :class:`AuthError` (same message for unknown user and wrong password)."""
        user = self.repos.users.get_by_username(username)
        if user is None:
            raise AuthError("Benutzername oder Passwort ist falsch.")
        left = self.lockout_seconds_left(user)
        if left > 0:
            raise AuthError(f"Zu viele Fehlversuche. Bitte warten Sie {left} Sekunden.")
        if not user.active:
            raise AuthError("Dieser Benutzer ist gesperrt. Bitte wenden Sie sich an einen Administrator.")
        if not self._matches(user, password):
            user.failed_logins += 1
            if user.failed_logins >= MAX_ATTEMPTS:
                delay = min(LOCKOUT_SECONDS * 2 ** (user.failed_logins - MAX_ATTEMPTS), 3600)
                user.locked_until = (self._clock() + timedelta(seconds=delay)).isoformat()
            self.repos.users.update(user)
            raise AuthError("Benutzername oder Passwort ist falsch.")
        return user

    def login(self, username: str, password: str) -> AppUser:
        """Verify and start the session (read-only role -> the database refuses all writes)."""
        user = self.verify(username, password)
        user.failed_logins, user.locked_until = 0, ""
        user.last_login = self._clock().isoformat(timespec="seconds")
        self.repos.users.update(user)
        self.start_session(user)
        return user

    def start_session(self, user: AppUser) -> None:
        self.session.user = user
        db = getattr(self.repos, "db", None)
        if db is not None:
            db.read_only = False
            db.user_name = user.username
        self._audit("login", "user", user.id, user.username)
        if db is not None:
            db.read_only = user.role == UserRole.VIEWER

    def logout(self) -> None:
        db = getattr(self.repos, "db", None)
        if db is not None:
            db.read_only = False
            db.user_name = ""
        self.session.user = None
