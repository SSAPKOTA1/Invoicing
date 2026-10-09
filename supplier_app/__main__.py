"""``python -m supplier_app [--selfcheck]`` entry point."""

from __future__ import annotations

import argparse
import sys


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="supplier_app", description="Lieferantenkonto & Mahnungs-Tracker")
    parser.add_argument("--selfcheck", action="store_true", help="headless start-up check, exit code 0 when ok")
    parser.add_argument("--data-dir", help="use this data folder instead of %%APPDATA%%/SupplierApp")
    parser.add_argument("--reset-pin", action="store_true", help="remove the PIN lock (documented recovery path)")
    parser.add_argument("--screenshots", metavar="DIR", help="render all screens (dark+light) with demo data to DIR")
    args = parser.parse_args(argv)
    if args.data_dir:
        import os

        os.environ["SUPPLIERAPP_DATA"] = args.data_dir
    if args.reset_pin:
        return _reset_pin()
    if args.selfcheck:
        from supplier_app.selfcheck import run_selfcheck

        return run_selfcheck()
    if args.screenshots:
        from supplier_app.views.screenshots import render_screenshots

        return render_screenshots(args.screenshots)
    from supplier_app.main import run_gui

    return run_gui()


def _reset_pin() -> int:
    """Recovery: after a typed confirmation the PIN is removed (the data itself is not encrypted)."""
    from supplier_app.main import build_context

    print("Die PIN-Sperre wird entfernt. Die Daten selbst sind nicht verschlüsselt.")
    if input("Zur Bestätigung 'PIN ZURUECKSETZEN' eingeben: ").strip() != "PIN ZURUECKSETZEN":
        print("Abgebrochen.")
        return 1
    ctx = build_context()
    try:
        ctx.services.pin.reset()
    finally:
        ctx.close()
    print("Die PIN wurde entfernt.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
