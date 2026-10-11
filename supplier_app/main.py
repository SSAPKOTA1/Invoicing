"""Composition root: builds the object graph (no global state)."""

from __future__ import annotations

from dataclasses import dataclass

from supplier_app.bootstrap import Storage, open_storage
from supplier_app.reports.builders import ReportService
from supplier_app.services.container import Services, build_services
from supplier_app.services.dashboard_service import DashboardService
from supplier_app.services.demo_data import DemoDataService
from supplier_app.settings.connection import ConnectionConfig
from supplier_app.settings.local_prefs import LocalPrefs
from supplier_app.settings.logging_setup import setup_logging, shutdown_logging
from supplier_app.settings.paths import AppPaths, default_paths


@dataclass
class AppContext:
    """Everything the UI layer needs; created once per process."""

    storage: Storage
    services: Services
    dashboard: DashboardService
    demo: DemoDataService
    reports: ReportService
    config: ConnectionConfig

    @property
    def paths(self) -> AppPaths:
        return self.storage.paths

    def close(self) -> None:
        self.storage.close()
        shutdown_logging()


def build_context(paths: AppPaths | None = None, config: ConnectionConfig | None = None) -> AppContext:
    """Connect to the PostgreSQL server (settings: ``config`` or the saved connection) and build all services."""
    from supplier_app.errors import ValidationError

    paths = paths or default_paths()
    paths.ensure()
    setup_logging(paths.logs)
    config = config or ConnectionConfig.load(paths.root)
    if not config.is_configured:
        raise ValidationError("Es ist noch kein Datenbank-Server eingerichtet.")
    config.validate()
    storage = open_storage(paths, config.dsn())
    services = build_services(storage, multi_user=True, prefs=LocalPrefs(paths.root / "prefs.json"))
    return AppContext(
        storage=storage,
        services=services,
        dashboard=DashboardService(services.repos, services.ledger, services.settings),
        demo=DemoDataService(services),
        reports=ReportService(services),
        config=config,
    )


def run_gui() -> int:
    """Start the desktop application."""
    from supplier_app.views.app import run_application

    return run_application()
