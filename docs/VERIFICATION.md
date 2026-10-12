# Verification

Status legend: **PASS** = run and proven, **FAIL**, **NOT VERIFIED** = not run in this environment.
Local environment: Linux, Python 3.13, Tesseract 5.3.4 (`deu`, `eng`) installed, PySide6 6.12 offscreen.
CI target: GitHub Actions `windows-latest`, Python 3.11 (see the CI section at the end).

| # | Item (Definition of Done) | Result | Proof |
|---|---|---|---|
| 1 | All six phases checked off in `TASK.md`; one commit per phase | PASS | `git log --oneline` shows commits `Phase 1` … `Phase 6` (Phase 5's commit is empty: the reporting code was committed together with Phase 4, noted in its message) |
| 2 | `pytest` passes with coverage targets | PASS | `python -m pytest tests --cov=supplier_app` → 383 tests (on SQLite and, with `SUPPLIER_TEST_PG_DSN`, on PostgreSQL 16), TOTAL ≥ 95 %; `python scripts/check_coverage.py coverage.xml`: services/ledger 99.2 % (≥ 90), repositories 97.8 %, database 92.1 %, ai 95.6 %, services 97.1 % (≥ 80) |
| 3 | `python -m supplier_app --selfcheck` exits 0, every screen builds offscreen dark + light | PASS | output `14 screen/theme combinations built offscreen`, exit 0 (also with the PyInstaller build on Linux: `SupplierAppConsole --selfcheck` → 0) |
| 4 | Worked example = exactly 615,00 € open, "partially paid" | PASS | `tests/test_ledger_engine.py::test_worked_example_from_spec` (engine) and `tests/test_services_core.py::test_worked_example_end_to_end` (services, DB) |
| 5 | End-to-end scenario: scan invoice → 1st Mahnung → 2nd Mahnung from collection agency with new reference → partial payment; one invoice, correct balance, history, discrepancy flags | PASS | `tests/test_e2e_scenario.py`: PDF text layers and real OCR of scanned PNG/JPG (`test_scenario_with_scanned_images`, needs Tesseract), plus court-order discrepancy flags and the collection letter with deduction |
| 6 | Search by company, invoice number, Bearbeitungsnummer, differently punctuated reference returns the same invoice | PASS | `tests/test_search_backup_docs.py::test_every_way_finds_the_same_invoice` (14 query variants) and the e2e test |
| 7 | Dashboard consistency; demo data fills every widget | PASS | `tests/test_dashboard.py`: open payables = Σ positive invoice balances = aging total; open − credits = Σ supplier balances = Σ ledger entries; every KPI/chart/list drill-down total equals the clicked number; `test_every_widget_is_filled_by_demo_data` |
| 8 | Dashboard < 500 ms with 50,000 ledger entries | PASS (locally) | `test_dashboard_loads_fast_with_50k_entries`: ≈ 280 ms plain, ≈ 590 ms while coverage tracing is on. The assertion is 0.5 s locally and 1.5 s when `CI` is set (shared runners) |
| 9 | Migrations from empty DB and from every earlier version; failed migration rolls back and restores the backup | PASS | `tests/test_migrations.py` |
| 10 | Backup and restore round trip | PASS | `tests/test_search_backup_docs.py` (round trip, tampered zip, zip-slip, older schema restored and migrated) |
| 11 | PIN flow (set, wrong PIN lockout, change, disable) | PASS | `tests/test_services_core.py::test_pin_flow`, `tests/test_ui.py::test_settings_page_actions` |
| 12 | `requirements.txt` pinned and installs cleanly in a fresh venv | PASS | fresh `python -m venv`, `pip install -r requirements.txt` → exit 0, `--selfcheck` → exit 0 |
| 13 | Build script and spec exist; latest CI run on the final commit green (Windows tests, exe build, exe self-check, screenshots) | see CI section | `scripts/build_exe.ps1`, `packaging/SupplierApp.spec`; PyInstaller spec verified on Linux (build + `SupplierAppConsole --selfcheck` exit 0). The Windows `.exe` itself can only be built in CI |
| 14 | No TODOs, stubs, placeholders | PASS | `grep -rnE "TODO\|FIXME\|NotImplementedError" supplier_app scripts tests packaging .github` → no hits (only `XXXX` in a test string and a sample BIC) |
| 15 | OCR verified | PASS (Linux, Tesseract 5.3.4) | `tests/test_ocr.py`, scanned fixtures with rotation/noise recognised; on a machine without Tesseract these tests skip with "OCR not verified" |

## Other checks

* Ledger invariants: balance = Σ entries; per invoice open costs + interest + principal = balance (`test_ledger_invariants_hold`); `ledger_entries` is protected by triggers (no UPDATE/DELETE) and CHECK constraints (`tests/test_migrations.py`).
* Corrupt PDF/PNG, encrypted PDF, empty text, missing file, unsupported type, missing Tesseract and locked database produce friendly messages, not crashes (`tests/test_e2e_scenario.py`, `tests/test_ocr.py`, `tests/test_database.py`).
* UI offscreen workflows: import via worker threads, review panel, payment dialog preview/booking, supplier/invoice/notice dialogs, search popup, drill-down dialogs, exports, settings (`tests/test_ui.py`). Screenshots: `python -m supplier_app --screenshots DIR`.
* Companies/hotels: scope filtering equals the sum of its parts (hotels add up to the company, companies to "all") for balances, aging, dashboard, search and reports (`tests/test_scope.py`); UI: header selector filters every page and is restored after a restart, settings management, invoice dialog / review form / history assignment, due-date and deadline edits (`tests/test_ui.py`).
* Invoice recognition: 52 invoice texts in 6 languages/layouts (Beleg, Facture, Fattura, Factura, Factuur, Faktura, Honorarnote, Netto/Brutto/Summe/Total variants, table and stacked layouts, Skonto, several VAT rates) are recognised field by field (before this change: 53 % of the fields on the first 29 texts, now 100 % on all 52), plus 5 generated PDFs read through the real PyMuPDF text layer (`tests/test_invoice_recognition.py`, `scripts/generate_invoice_fixtures.py`).
* Multi-user: the whole service-level test suite (ledger, dashboard, scope, e2e, search, repositories) runs on SQLite **and** PostgreSQL 16 (`SUPPLIER_TEST_PG_DSN`, per-test database from a template; CI job `postgres`); real concurrency tests with several connections (six simultaneous payments, five simultaneous identical invoice numbers, four clients migrating a new database at once, dropped connection, live refresh and attribution, shared document files), users/roles/lockout/read-only enforcement, server backup/restore and local->server transfer (`tests/test_users.py`, `tests/test_multiuser.py`, `tests/test_multiuser_ui.py`).
* Shared folder (no server): two PCs on one folder see each other's users/bookings/documents, five threads and four separate processes paying the same invoice at once pay it exactly once, identical invoice numbers are rejected once, daily backup/pruning, damaged-file detection, session heartbeat, restore refused while colleagues are connected, local -> shared transfer, connection dialog and start flow (`tests/test_shared.py`).
* Printing: reports are rendered through the print code path into PDF (preview dialog, print dialog and direct PDF), multi-page output with repeated header row and page numbers verified visually (`test_reports_print_preview_and_pdf`).
* Exported report numbers equal the ledger (`tests/test_reports.py`: CSV, Excel and PDF are parsed back and compared).

* English interface: `en.json` is complete (same keys and placeholders as `de.json`); every screen, dialog, review panel, drill-down, report and invoice history is opened in English with demo data and checked for German function words; every error message of the source code has an English text; saving/restoring the language, the settings selector with restart, the `--language` option and the English report headings are tested (`tests/test_i18n.py`, `tests/test_english.py`).

* Recognition quality (change request "refine the identifier"): a generated corpus of 72 letters (invoices, reminders, agency letters, new and known suppliers, five reference layouts, OCR noise, look-alike names, own company names) is evaluated by `tests/recognition_corpus.py`; results: known supplier 100 % (clean) / 98 % (noisy, look-alike master data), new supplier name 100 %, references 100 % with 100 % precision (before: references 1/3 missed, the unknown agency letters matched to the wrong supplier). `tests/test_recognition_accuracy.py` fails below the thresholds in DECISIONS 37.
* Documents without invoice, changing the supplier/sender later, recurring invoices, bank statements: `tests/test_unassigned.py`, `tests/test_corrections.py`, `tests/test_recurring.py`, `tests/test_bank_parsers.py` (CSV incl. cp1252/preamble/debit-credit columns, CAMT.053, MT940 structured and SEPA tags, PDF text), `tests/test_bank.py` (matching, booking, learning, duplicates, overlapping statements, own-account transfers, reversal), UI tests for the picker, the claims editor, the bank page and the recurring dialog; the whole suite also runs on PostgreSQL 16.

## Known limitations

* The Windows `.exe` was not run on Windows by me; Windows behaviour is covered by the CI workflow only.
* Base-rate table is a seeded default (ends 2025-07-01 at 1.27 %); users must verify rates (not legal advice).
* Recognition is rule-based: unusual letter layouts need a manual correction in the review form.
* PyMuPDF is AGPL-licensed (see `LICENSE-THIRD-PARTY.txt`); `pdfplumber` from the brief is not used.

## CI (GitHub Actions, `windows-latest`, Python 3.11)

Run on commit `dbcea07` ([run 37944562914](https://github.com/SSAPKOTA1/Invoicing/actions/runs/37944562914)): **PASS** – every step green:
install Tesseract (`deu`, `eng`) → install requirements → lint → pytest with coverage (≥ 85 % total) → per-area coverage check →
`--selfcheck` → screenshots (artifact `screenshots`) → `scripts/build_exe.ps1` → self-check of the built
`SupplierAppConsole.exe` and `SupplierApp.exe` (exit code 0) → artifact `SupplierApp-windows-x64`.
The same pipeline is also green on the final code commit `f5e855d` ([run 37945324626](https://github.com/SSAPKOTA1/Invoicing/actions/runs/37945324626), tests, exe build, exe self-check, screenshots and zip artifacts all succeeded). (Item 13 above: PASS for the run named here;
`gh` was not authenticated in the authoring environment, so the run was read through the GitHub API tools.)

No pull request was opened: the repository has no `main` branch yet (only `claude/zen-cannon-x8l4cj`), and pushing to another branch was not permitted.
