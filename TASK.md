# TASK.md – source of truth

Supplier Ledger & Dunning Tracker (Windows desktop, Python / PySide6).
Resume rule: read this file + `docs/DECISIONS.md`, continue at the first unchecked item.

Branch: `claude/zen-cannon-x8l4cj` (designated by the environment; stands in for `build/initial`).

## Phase 1 – Architecture, database, migrations
- [x] 1.1 Skeleton, packaging files, `--selfcheck` entry point
- [x] 1.2 Models (enums + dataclasses)
- [x] 1.3 Database layer (connection, transactions, savepoints)
- [x] 1.4 Migrations runner (backup, rollback) + schema 001..003 incl. FTS5
- [x] 1.5 Repository interfaces + SQLite implementations
- [x] 1.6 Tests (migrations, repositories) green; app creates its DB
- [x] 1.7 Commit `Phase 1`

## Phase 2 – Ledger engine and backend services
- [x] 2.1 Ledger engine tests first (worked example etc.)
- [x] 2.2 Ledger engine (balances, allocation, notice postings, reconciliation, interest, aging)
- [x] 2.3 Services: supplier, invoice, payment, dunning, case, ledger, audit
- [x] 2.4 Search service
- [x] 2.5 Backup / restore, PIN, settings
- [x] 2.6 Commit `Phase 2`

## Phase 3 – OCR and recognition
- [x] 3.1 Fixture generator (PDF + scanned PNG)
- [x] 3.2 `ocr/` (text layer, Tesseract wrapper, preprocessing)
- [x] 3.3 `ai/` classifier, field extractor, reference extractor, validator, link matcher
- [x] 3.4 Document ingest + review services; end-to-end scenario test
- [x] 3.5 Commit `Phase 3`

## Phase 4 – UI
- [ ] 4.1 Themes, main window, navigation, global search
- [ ] 4.2 Dashboard service + dashboard screen (filters, KPIs, charts, lists, drill-down)
- [ ] 4.3 Suppliers, Cases/history view, Transactions, Documents + review workflow
- [ ] 4.4 Payment dialog, Settings, PIN screen
- [ ] 4.5 Demo data, offscreen smoke tests, screenshots script
- [ ] 4.6 Commit `Phase 4`

## Phase 5 – Reporting
- [ ] 5.1 Report builders + CSV/Excel/PDF export
- [ ] 5.2 Dashboard export (PDF/PNG)
- [ ] 5.3 Tests: exported numbers == DB
- [ ] 5.4 Commit `Phase 5`

## Phase 6 – Packaging and CI
- [ ] 6.1 Pinned requirements, fresh venv install test
- [ ] 6.2 `scripts/build_exe.ps1`, PyInstaller spec, Tesseract bundling
- [ ] 6.3 CI + release workflows
- [ ] 6.4 README (German end user + dev), VERIFICATION.md
- [ ] 6.5 Full test run + coverage, TODO/stub search
- [ ] 6.6 Push, watch CI, PR to main
- [ ] 6.7 Commit `Phase 6`

## Known issues
(none yet)

## Log
- 2026-10-09 Phase 1: schema m001-m003, repositories, 24 tests green, --selfcheck ok
- 2026-10-09 Phase 2: ledger engine (ledger/ coverage ~99%), services, search, backup/restore, PIN; worked example = 615,00 EUR
- 2026-10-09 Phase 3: OCR (text layer + Tesseract), rule-based ai/, ingest+review services; e2e scenario passes with PDF and scans
