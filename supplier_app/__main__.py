"""``python -m supplier_app [--selfcheck]`` entry point."""

from __future__ import annotations

import argparse
import sys


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="supplier_app", description="Lieferantenkonto & Mahnungs-Tracker")
    parser.add_argument("--selfcheck", action="store_true", help="headless start-up check, exit code 0 when ok")
    parser.add_argument("--data-dir", help="use this data folder instead of %%APPDATA%%/SupplierApp")
    parser.add_argument("--screenshots", metavar="DIR", help="render all screens (dark+light) with demo data to DIR")
    args = parser.parse_args(argv)
    if args.data_dir:
        import os

        os.environ["SUPPLIERAPP_DATA"] = args.data_dir
    if args.selfcheck:
        from supplier_app.selfcheck import run_selfcheck

        return run_selfcheck()
    if args.screenshots:
        from supplier_app.views.screenshots import render_screenshots

        return render_screenshots(args.screenshots)
    from supplier_app.main import run_gui

    return run_gui()


if __name__ == "__main__":
    sys.exit(main())
