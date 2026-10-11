"""``python -m supplier_app [--selfcheck | --screenshots DIR | --set-password USER]`` entry point."""

from __future__ import annotations

import argparse
import sys


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="supplier_app", description="Lieferantenkonto & Mahnungs-Tracker")
    parser.add_argument("--selfcheck", action="store_true", help="headless start-up check, exit code 0 when ok")
    parser.add_argument("--data-dir", help="use this data folder instead of %%APPDATA%%/SupplierApp")
    parser.add_argument("--set-password", metavar="USER", help="multi-user mode: set a new password for USER (lost password)")
    parser.add_argument("--screenshots", metavar="DIR", help="render all screens (dark+light) with demo data to DIR")
    args = parser.parse_args(argv)
    if args.data_dir:
        import os

        os.environ["SUPPLIERAPP_DATA"] = args.data_dir
    if args.set_password:
        return _set_password(args.set_password)
    if args.selfcheck:
        from supplier_app.selfcheck import run_selfcheck

        return run_selfcheck()
    if args.screenshots:
        from supplier_app.views.screenshots import render_screenshots

        return render_screenshots(args.screenshots)
    from supplier_app.main import run_gui

    return run_gui()


def _set_password(username: str) -> int:
    """Recovery for a lost administrator password (needs the database access of this PC)."""
    import getpass

    from supplier_app.errors import SupplierAppError
    from supplier_app.main import build_context

    ctx = build_context()
    try:
        user = ctx.services.users.repos.users.get_by_username(username)
        if user is None:
            print(f"Benutzer '{username}' nicht gefunden.")
            return 1
        first, second = getpass.getpass("Neues Passwort: "), getpass.getpass("Wiederholen: ")
        if first != second:
            print("Die Passwörter stimmen nicht überein.")
            return 1
        try:
            ctx.services.session.multi_user = False  # recovery runs with database access = full control
            ctx.services.users.reset_password(user.id, first)  # type: ignore[arg-type]
        except SupplierAppError as exc:
            print(exc.message)
            return 1
    finally:
        ctx.close()
    print(f"Das Passwort von '{username}' wurde geändert.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
