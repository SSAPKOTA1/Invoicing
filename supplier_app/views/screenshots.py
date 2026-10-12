"""Render a screenshot of every screen in dark and light mode with demo data (used by CI)."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path


def render_screenshots(target: str) -> int:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from supplier_app.main import build_context
    from supplier_app.selfcheck_ui import THEMES, make_window
    from supplier_app.settings.paths import AppPaths

    out = Path(target)
    out.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="supplierapp-shots-") as tmp:
        ctx = build_context(AppPaths(Path(tmp)))
        try:
            ctx.demo.load()
            app, ctrl, window = make_window(ctx)
            window.resize(1600, 1000)
            window.show()
            for theme in THEMES:
                ctrl.set_theme(theme)
                for i, key in enumerate(window.pages, start=1):
                    window.show_page(key)
                    if key == "documents":
                        page = window.pages[key]
                        docs = ctx.services.repos.documents.list()
                        if docs:
                            page.select_document(docs[-1].id)  # type: ignore[attr-defined]
                    if key == "cases":
                        cases = ctx.services.cases.list()
                        if cases:
                            window.pages[key].select_invoice(cases[-1].invoice_id)  # type: ignore[attr-defined]
                    app.processEvents()
                    window.grab().save(str(out / f"{i:02d}-{key}-{theme}.png"), "PNG")
                if theme == "dark":
                    dash = window.pages["dashboard"]
                    dash.content.grab().save(str(out / "00-dashboard-full-dark.png"), "PNG")  # type: ignore[attr-defined]
            window.close()
        finally:
            ctx.close()
    print(f"screenshots written to {out}")
    return 0
