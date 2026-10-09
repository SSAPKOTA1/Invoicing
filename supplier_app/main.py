"""Composition root: builds the object graph (no global state)."""

from __future__ import annotations

from dataclasses import dataclass

from supplier_app.bootstrap import Storage, open_storage
from supplier_app.settings.logging_setup import setup_logging
from supplier_app.settings.paths import AppPaths, default_paths


@dataclass
class AppContext:
    """Everything the UI layer needs; created once per process."""

    storage: Storage

    def close(self) -> None:
        self.storage.close()


def build_context(paths: AppPaths | None = None) -> AppContext:
    paths = paths or default_paths()
    paths.ensure()
    setup_logging(paths.logs)
    return AppContext(storage=open_storage(paths))


def run_gui() -> int:  # pragma: no cover - replaced when UI is in place
    raise SystemExit("GUI not available")
