"""Composition root: builds the object graph (no global state)."""

from __future__ import annotations

from dataclasses import dataclass

from supplier_app.backup.auto import ensure_daily_backup
from supplier_app.bootstrap import Storage, open_pg_storage, open_storage
from supplier_app.reports.builders import ReportService
from supplier_app.services.container import Services, build_services
from supplier_app.services.dashboard_service import DashboardService
from supplier_app.services.demo_data import DemoDataService
from supplier_app.settings.connection import ConnectionConfig, check_shared_folder
from supplier_app.settings.local_prefs import LocalPrefs
from supplier_app.settings.logging_setup import setup_logging, shutdown_logging
from supplier_app.settings.paths import AppPaths, default_paths
from supplier_app.settings.shared import SessionRegistry


@dataclass
class AppContext:
    """Everything the UI layer needs; created once per process."""

    storage: Storage
    services: Services
    dashboard: DashboardService
    demo: DemoDataService
    reports: ReportService
    config: ConnectionConfig
    registry: SessionRegistry | None = None  # shared folder mode: who is connected

    @property
    def multi_user(self) -> bool:
        return self.config.is_multi_user

    @property
    def paths(self) -> AppPaths:
        return self.storage.paths

    def close(self) -> None:
        if self.registry is not None:
            self.registry.unregister()
        self.storage.close()
        shutdown_logging()


def build_context(paths: AppPaths | None = None, config: ConnectionConfig | None = None) -> AppContext:
    """Open the data (local SQLite file or PostgreSQL server) and build all services."""
    paths = paths or default_paths()
    paths.ensure()
    setup_logging(paths.logs)
    config = config or ConnectionConfig.load(paths.local)
    registry: SessionRegistry | None = None
    if config.is_shared:
        config.validate()
        paths = AppPaths(check_shared_folder(config.shared_path), local_root=paths.local)
        paths.ensure()
        storage = open_storage(paths, shared=True)
        ensure_daily_backup(storage.db, paths.backups / "auto")
        services = build_services(storage, multi_user=True, prefs=LocalPrefs(paths.local / "prefs.json"))
        registry = SessionRegistry(paths.root)
        services.backup.guard = registry.others_label
    elif config.is_server:
        config.validate()
        storage = open_pg_storage(paths, config.dsn())
        services = build_services(storage, multi_user=True, prefs=LocalPrefs(paths.local / "prefs.json"))
    else:
        storage = open_storage(paths)
        services = build_services(storage)
    return AppContext(
        storage=storage,
        services=services,
        dashboard=DashboardService(services.repos, services.ledger, services.settings),
        demo=DemoDataService(services),
        reports=ReportService(services),
        config=config,
        registry=registry,
    )


def run_gui() -> int:
    """Start the desktop application."""
    from supplier_app.views.app import run_application

    return run_application()
