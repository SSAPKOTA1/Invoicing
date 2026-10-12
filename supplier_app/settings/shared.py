"""Who is working in the shared folder right now: one small heartbeat file per running program."""

from __future__ import annotations

import json
import logging
import os
import re
import socket
import time
from pathlib import Path

log = logging.getLogger(__name__)
STALE_SECONDS = 90


class SessionRegistry:
    """``sessions/<computer>-<pid>.json`` with user and time of the last heartbeat. Used to show colleagues and to
    refuse dangerous actions (restoring a backup) while others are connected."""

    def __init__(self, folder: Path | str, stale_seconds: int = STALE_SECONDS) -> None:
        self.dir = Path(folder) / "sessions"
        self.stale = stale_seconds
        self.host = socket.gethostname()
        self.pid = os.getpid()
        self.user = ""
        self.started = time.time()
        self._file = self.dir / (re.sub(r"[^\w.-]", "_", f"{self.host}-{self.pid}") + ".json")

    def register(self, username: str) -> None:
        self.user = username
        self.started = time.time()
        self.heartbeat()

    def heartbeat(self) -> None:
        try:
            self.dir.mkdir(parents=True, exist_ok=True)
            self._file.write_text(json.dumps({"user": self.user, "host": self.host, "pid": self.pid, "started": self.started,
                                              "seen": time.time()}), encoding="utf-8")
        except OSError:
            log.debug("session heartbeat failed", exc_info=True)

    def unregister(self) -> None:
        self._file.unlink(missing_ok=True)

    def active(self) -> list[dict]:
        """All live sessions including this one."""
        now, out = time.time(), []
        for f in self.dir.glob("*.json") if self.dir.is_dir() else []:
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if now - float(data.get("seen", 0)) <= self.stale:
                out.append(data)
        return out

    def others(self) -> list[dict]:
        return [d for d in self.active() if not (d.get("host") == self.host and d.get("pid") == self.pid)]

    def others_label(self) -> list[str]:
        return [f"{d.get('user') or '?'} ({d.get('host')})" for d in self.others()]
