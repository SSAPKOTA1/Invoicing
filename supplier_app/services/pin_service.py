"""Optional PIN lock: scrypt hash with random salt, lockout after repeated failures."""

from __future__ import annotations

import hashlib
import hmac
import os
import re
from collections.abc import Callable
from datetime import datetime, timedelta

from supplier_app.errors import AuthError, ValidationError
from supplier_app.repositories.interfaces import Repositories
from supplier_app.services.base import ServiceBase

MAX_ATTEMPTS = 5
BASE_LOCKOUT_SECONDS = 30
_SCRYPT = {"n": 2**14, "r": 8, "p": 1, "maxmem": 64 * 1024 * 1024, "dklen": 32}


def hash_pin(pin: str, salt: bytes) -> bytes:
    return hashlib.scrypt(pin.encode("utf-8"), salt=salt, **_SCRYPT)  # type: ignore[arg-type]


class PinService(ServiceBase):
    """PIN handling. ``clock`` is injectable for tests."""

    def __init__(self, repos: Repositories, clock: Callable[[], datetime] = datetime.now) -> None:
        super().__init__(repos)
        self._clock = clock

    # -- state ---------------------------------------------------------------
    @property
    def enabled(self) -> bool:
        return bool(self.repos.settings.get("pin_hash"))

    def lockout_seconds_left(self) -> int:
        until = self.repos.settings.get("pin_locked_until")
        if not until:
            return 0
        left = (datetime.fromisoformat(until) - self._clock()).total_seconds()
        return max(0, int(left + 0.999))

    @staticmethod
    def _validate_format(pin: str) -> None:
        if not re.fullmatch(r"\d{4,8}", pin):
            raise ValidationError("Die PIN muss aus 4 bis 8 Ziffern bestehen.")

    # -- operations ----------------------------------------------------------
    def verify(self, pin: str) -> bool:
        """Check the PIN. Raises :class:`AuthError` while locked out; counts failures."""
        stored = self.repos.settings.get("pin_hash")
        if not stored:
            return True
        left = self.lockout_seconds_left()
        if left > 0:
            raise AuthError(f"Zu viele Fehlversuche. Bitte warten Sie {left} Sekunden.")
        salt = bytes.fromhex(self.repos.settings.get("pin_salt") or "")
        ok = hmac.compare_digest(hash_pin(pin, salt).hex(), stored)
        if ok:
            self.repos.settings.set("pin_failed", "0")
            self.repos.settings.delete("pin_locked_until")
            return True
        failed = int(self.repos.settings.get("pin_failed", "0") or 0) + 1
        self.repos.settings.set("pin_failed", str(failed))
        if failed >= MAX_ATTEMPTS:
            steps = failed - MAX_ATTEMPTS
            delay = min(BASE_LOCKOUT_SECONDS * (2**steps), 3600)
            self.repos.settings.set("pin_locked_until", (self._clock() + timedelta(seconds=delay)).isoformat())
        return False

    def _store(self, pin: str) -> None:
        salt = os.urandom(16)
        self.repos.settings.set("pin_salt", salt.hex())
        self.repos.settings.set("pin_hash", hash_pin(pin, salt).hex())
        self.repos.settings.set("pin_failed", "0")
        self.repos.settings.delete("pin_locked_until")

    def set_pin(self, new_pin: str, current_pin: str | None = None) -> None:
        """Enable or change the PIN; changing requires the current PIN."""
        self._validate_format(new_pin)
        if self.enabled and not self.verify(current_pin or ""):
            raise AuthError("Die aktuelle PIN ist falsch.")
        self._store(new_pin)
        self._audit("set_pin", "settings", None)

    def disable(self, current_pin: str) -> None:
        if not self.enabled:
            return
        if not self.verify(current_pin):
            raise AuthError("Die aktuelle PIN ist falsch.")
        self.reset()

    def reset(self) -> None:
        """Remove the PIN without checking it (documented recovery path)."""
        for key in ("pin_hash", "pin_salt", "pin_failed", "pin_locked_until"):
            self.repos.settings.delete(key)
        self._audit("reset_pin", "settings", None)
