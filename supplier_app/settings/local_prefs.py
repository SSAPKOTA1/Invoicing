"""Per-user preferences kept on the local machine (theme, selected hotel, dashboard period).

In the multi-user mode these must not be shared through the database: every user keeps their own.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

log = logging.getLogger(__name__)

#: settings keys that are personal (stored here in server mode, in the database in local mode)
PER_USER_KEYS = frozenset({"theme", "active_scope", "dash_period", "language", "tesseract_path"})


class LocalPrefs:
    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        self._data: dict[str, str] = {}
        try:
            if self.path.exists():
                loaded = json.loads(self.path.read_text(encoding="utf-8"))
                self._data = {str(k): str(v) for k, v in loaded.items()}
        except (OSError, ValueError):
            log.warning("preferences file unreadable, starting with defaults", exc_info=True)

    def get(self, key: str) -> str | None:
        return self._data.get(key)

    def set(self, key: str, value: str) -> None:
        self._data[key] = value
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps(self._data, ensure_ascii=False, indent=1), encoding="utf-8")
        except OSError:
            log.warning("preferences could not be saved", exc_info=True)
