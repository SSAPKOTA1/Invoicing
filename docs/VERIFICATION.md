# Verification

Status legend: **PASS** = run and proven, **FAIL**, **NOT VERIFIED** = not run in this environment.
Local environment: Linux, Python 3.13, Tesseract 5.3.4 (`deu`, `eng`) installed, PySide6 6.12 offscreen.
CI target: GitHub Actions `windows-latest`, Python 3.11 (see the CI section at the end).

| # | Item (Definition of Done) | Result | Proof |
|---|---|---|---|
| 1 | All six phases checked off in `TASK.md`; one commit per phase | PASS | `git log --oneline` shows commits `Phase 1` … `Phase 6` (Phase 5's commit is empty: the reporting code was committed together with Phase 4, noted in its message) |
| 2 | `pytest` passes with coverage targets | PASS | `python -m pytest tests --cov=supplier_app` → 173 passed, TOTAL 95 %; `python scripts/check_coverage.py coverage.xml`: services/ledger 99.2 % (≥ 90), repositories 98.6 %, database/migrations 96.9 %, ai 94.1 %, services 96.6 % (≥ 80) |
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
* UI offscreen workflows: import via worker threads, review panel, payment dialog preview/booking, supplier/invoice/notice dialogs, search popup, drill-down dialogs, exports, settings (`tests/test_ui.py`, 13 tests). Screenshots: `python -m supplier_app --screenshots DIR`.
* Exported report numbers equal the ledger (`tests/test_reports.py`: CSV, Excel and PDF are parsed back and compared).

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
