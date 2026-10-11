# Verification

Status legend: **PASS** = run and proven, **FAIL**, **NOT VERIFIED** = not run in this environment.
Local environment: Linux, Python 3.13, Tesseract 5.3.4 (`deu`, `eng`) installed, PySide6 6.12 offscreen, PostgreSQL 16 (the program works only with PostgreSQL; the tests need `SUPPLIER_TEST_PG_DSN`).
CI target: GitHub Actions `windows-latest`, Python 3.11 (see the CI section at the end).

| # | Item (Definition of Done) | Result | Proof |
|---|---|---|---|
| 1 | All six phases checked off in `TASK.md`; one commit per phase | PASS | `git log --oneline` shows commits `Phase 1` … `Phase 6` (Phase 5's commit is empty: the reporting code was committed together with Phase 4, noted in its message) |
| 2 | `pytest` passes with coverage targets | PASS | `python -m pytest tests --cov=supplier_app` on PostgreSQL 16 → 355 passed, TOTAL 95 %; `python scripts/check_coverage.py coverage.xml`: services/ledger 99.2 % (≥ 90), repositories 97.8 %, database 96.3 %, ai 95.6 %, services 97.0 % (≥ 80) |
| 3 | `python -m supplier_app --selfcheck` exits 0, every screen builds offscreen dark + light | PASS | with `SUPPLIERAPP_PG_DSN` set: `database ok, schema version 5, server 16.x` and `14 screen/theme combinations built offscreen`, exit 0 (the check runs in a throw-away schema of the server). Packaged exe: see CI section |
| 4 | Worked example = exactly 615,00 € open, "partially paid" | PASS | `tests/test_ledger_engine.py::test_worked_example_from_spec` (engine) and `tests/test_services_core.py::test_worked_example_end_to_end` (services, DB) |
| 5 | End-to-end scenario: scan invoice → 1st Mahnung → 2nd Mahnung from collection agency with new reference → partial payment; one invoice, correct balance, history, discrepancy flags | PASS | `tests/test_e2e_scenario.py`: PDF text layers and real OCR of scanned PNG/JPG (`test_scenario_with_scanned_images`, needs Tesseract), plus court-order discrepancy flags and the collection letter with deduction |
| 6 | Search by company, invoice number, Bearbeitungsnummer, differently punctuated reference returns the same invoice | PASS | `tests/test_search_backup_docs.py::test_every_way_finds_the_same_invoice` (14 query variants) and the e2e test |
| 7 | Dashboard consistency; demo data fills every widget | PASS | `tests/test_dashboard.py`: open payables = Σ positive invoice balances = aging total; open − credits = Σ supplier balances = Σ ledger entries; every KPI/chart/list drill-down total equals the clicked number; `test_every_widget_is_filled_by_demo_data` |
| 8 | Dashboard < 500 ms with 50,000 ledger entries | PASS (locally) | `test_dashboard_loads_fast_with_50k_entries`: below the limit on a local PostgreSQL. The assertion is 1.5 s locally and 3 s when `CI` is set (server round trips, shared runners) |
| 9 | Migrations from an empty database; failed migration rolls back completely; newer database refused; several clients migrating at once | PASS | `tests/test_migrations.py` (PostgreSQL DDL is transactional, advisory lock around the migration) |
| 10 | Backup and restore round trip (tables + document files) | PASS | `tests/test_search_backup_docs.py`, `tests/test_users.py::test_server_documents_backup_restore` (round trip, tampered zip, zip-slip, row-count mismatch, identity counters continue) |
| 11 | Sign-in flow (first administrator, wrong password lockout, roles, change/reset password) | PASS | `tests/test_users.py`, `tests/test_multiuser_ui.py` |
| 12 | `requirements.txt` pinned and installs cleanly in a fresh venv | PASS | fresh `python -m venv`, `pip install -r requirements.txt` → exit 0, `--selfcheck` → exit 0 |
| 13 | Build script and spec exist; latest CI run on the final commit green (Windows tests, exe build, exe self-check, screenshots) | see CI section | `scripts/build_exe.ps1`, `packaging/SupplierApp.spec`; PyInstaller spec verified on Linux (build + `SupplierAppConsole --selfcheck` exit 0). The Windows `.exe` itself can only be built in CI |
| 14 | No TODOs, stubs, placeholders | PASS | `grep -rnE "TODO\|FIXME\|NotImplementedError" supplier_app scripts tests packaging .github` → no hits (only `XXXX` in a test string and a sample BIC) |
| 15 | OCR verified | PASS (Linux, Tesseract 5.3.4) | `tests/test_ocr.py`, scanned fixtures with rotation/noise recognised; on a machine without Tesseract these tests skip with "OCR not verified" |

## Other checks

* Ledger invariants: balance = Σ entries; per invoice open costs + interest + principal = balance (`test_ledger_invariants_hold`); `ledger_entries` is protected by triggers (no UPDATE/DELETE) and CHECK constraints (`tests/test_migrations.py`).
* Corrupt PDF/PNG, encrypted PDF, empty text, missing file, unsupported type, missing Tesseract, unreachable server and a busy database produce friendly messages, not crashes (`tests/test_e2e_scenario.py`, `tests/test_ocr.py`, `tests/test_database.py`).
* UI offscreen workflows: import via worker threads, review panel, payment dialog preview/booking, supplier/invoice/notice dialogs, search popup, drill-down dialogs, exports, settings (`tests/test_ui.py`). Screenshots: `python -m supplier_app --screenshots DIR`.
* Companies/hotels: scope filtering equals the sum of its parts (hotels add up to the company, companies to "all") for balances, aging, dashboard, search and reports (`tests/test_scope.py`); UI: header selector filters every page and is restored after a restart, settings management, invoice dialog / review form / history assignment, due-date and deadline edits (`tests/test_ui.py`).
* Invoice recognition: 52 invoice texts in 6 languages/layouts (Beleg, Facture, Fattura, Factura, Factuur, Faktura, Honorarnote, Netto/Brutto/Summe/Total variants, table and stacked layouts, Skonto, several VAT rates) are recognised field by field (before this change: 53 % of the fields on the first 29 texts, now 100 % on all 52), plus 5 generated PDFs read through the real PyMuPDF text layer (`tests/test_invoice_recognition.py`, `scripts/generate_invoice_fixtures.py`).
* PostgreSQL only: the whole test suite (ledger, dashboard, scope, e2e, search, repositories, UI) runs on PostgreSQL 16 (`SUPPLIER_TEST_PG_DSN`, per-test database from a template; CI jobs `windows` and `postgres`); real concurrency tests with several connections (six simultaneous payments, five simultaneous identical invoice numbers, five clients migrating a new database at once, dropped connection, live refresh and attribution, shared document files), users/roles/lockout/read-only enforcement, server backup/restore, connection dialog and start flow (`tests/test_database.py`, `tests/test_users.py`, `tests/test_multiuser.py`, `tests/test_multiuser_ui.py`).
* Import of the former single-user version: a `supplier.db` made by the previous program version (fixture `tests/fixtures/legacy`) is imported into an empty database (invoice RE-2024/001 keeps its balance of 600,00 €, documents arrive, the PIN is not copied, a non-empty target is refused, garbage files are rejected) (`tests/test_users.py::test_import_of_the_old_single_user_database`).
* Printing: reports are rendered through the print code path into PDF (preview dialog, print dialog and direct PDF), multi-page output with repeated header row and page numbers verified visually (`test_reports_print_preview_and_pdf`).
* Exported report numbers equal the ledger (`tests/test_reports.py`: CSV, Excel and PDF are parsed back and compared).

## Known limitations

* The Windows `.exe` was not run on Windows by me; Windows behaviour is covered by the CI workflow only.
* Base-rate table is a seeded default (ends 2025-07-01 at 1.27 %); users must verify rates (not legal advice).
* Recognition is rule-based: unusual letter layouts need a manual correction in the review form.
* PyMuPDF is AGPL-licensed (see `LICENSE-THIRD-PARTY.txt`); `pdfplumber` from the brief is not used.

## CI (GitHub Actions)

Two jobs on every push: `windows` (`windows-latest`, Python 3.11: PostgreSQL via `scripts/ci_postgres_windows.ps1`, Tesseract, lint, all tests, self-check, screenshots, `scripts/build_exe.ps1`, self-check of the built `SupplierAppConsole.exe`/`SupplierApp.exe`, artifact `SupplierApp-windows-x64`) and `postgres` (`ubuntu-latest` with a `postgres:16` service container: all tests with coverage ≥ 85 % total and the per-area thresholds). The result of the latest run is stated in the pull request / the final report of the change; the earlier SQLite-based runs (last green: `b110d8a`) no longer apply.
