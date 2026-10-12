"""Repository of the application users (multi-user mode); portable SQL for SQLite and PostgreSQL."""

from __future__ import annotations

from supplier_app.database.errors import INTEGRITY_ERRORS
from supplier_app.errors import DuplicateError
from supplier_app.models.entities import AppUser
from supplier_app.models.enums import UserRole
from supplier_app.repositories.interfaces import UserRepository
from supplier_app.repositories.sqlite_base import SqliteRepo, stamp


def _user(row) -> AppUser:  # type: ignore[no-untyped-def]
    return AppUser(
        id=row["id"], username=row["username"], display_name=row["display_name"], role=UserRole(row["role"]),
        password_hash=row["password_hash"], password_salt=row["password_salt"], active=bool(row["active"]),
        failed_logins=row["failed_logins"], locked_until=row["locked_until"] or "", created_at=row["created_at"],
        last_login=row["last_login"] or "")


class SqliteUserRepository(SqliteRepo, UserRepository):
    def add(self, user: AppUser) -> AppUser:
        user.created_at = stamp(user.created_at)
        try:
            user.id = self.db.insert(
                "INSERT INTO app_users(username, display_name, password_hash, password_salt, role, active, failed_logins,"
                " locked_until, created_at, last_login) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (user.username.strip(), user.display_name, user.password_hash, user.password_salt, user.role.value,
                 int(user.active), user.failed_logins, user.locked_until or None, user.created_at, user.last_login or None))
        except INTEGRITY_ERRORS as exc:
            raise DuplicateError(f"Der Benutzername '{user.username}' ist bereits vergeben oder ungültig.") from exc
        return user

    def update(self, user: AppUser) -> None:
        self.db.execute(
            "UPDATE app_users SET display_name=?, password_hash=?, password_salt=?, role=?, active=?, failed_logins=?,"
            " locked_until=?, last_login=? WHERE id=?",
            (user.display_name, user.password_hash, user.password_salt, user.role.value, int(user.active),
             user.failed_logins, user.locked_until or None, user.last_login or None, user.id))

    def get(self, user_id: int) -> AppUser | None:
        row = self.db.query_one("SELECT * FROM app_users WHERE id=?", (user_id,))
        return _user(row) if row else None

    def get_by_username(self, username: str) -> AppUser | None:
        row = self.db.query_one("SELECT * FROM app_users WHERE lower(username)=lower(?)", (username.strip(),))
        return _user(row) if row else None

    def list(self) -> list[AppUser]:
        return [_user(r) for r in self.db.query_all("SELECT * FROM app_users ORDER BY lower(username)")]

    def count(self) -> int:
        return int(self.db.scalar("SELECT COUNT(*) FROM app_users", default=0))

    def delete(self, user_id: int) -> None:
        self.db.execute("DELETE FROM app_users WHERE id=?", (user_id,))
