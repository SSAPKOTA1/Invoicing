# Decisions

1. Repo root is the project root; the Python package is `supplier_app/`. The environment fixed the working branch `claude/zen-cannon-x8l4cj` instead of `build/initial`.
2. Dev venv at `.venv` (ignored). Local Python is 3.13, CI targets 3.11; code stays 3.11-compatible.
3. Ledger entries carry both `entry_type` (incl. `REVERSAL`) and `category_type` (economic type; for reversals the type of the reversed entry) so SQL aggregates and the pure engine need no joins.
4. Notice claims are cumulative per invoice (principal / fees / interest / flat fee / other costs). Booking posts only the delta against charges already in the ledger, which prevents double counting when later letters restate earlier fees.
5. Unapplied payment money is a PAYMENT ledger entry with `invoice_id = NULL` (credit on account of the supplier).
6. Interest: days counted for `due < d <= until`; a payment on day P reduces the principal from P+1. Interest rounded once (ROUND_HALF_UP). Seeded base rates are defaults to verify, not legal advice.
7. Money is integer cents; VAT rate is stored as text decimal; interest rate as `Decimal`.
8. Extra column `flat_fee_cents` on notices (Verzugspauschale) in addition to the fields in the brief.
9. Recognition is review-first: every imported document gets status `pending` (or `needs_review` when confidence < 0.75 or errors exist); bookings only happen in `IngestService.confirm`.
10. Collection letters that print a total before deducting payments ("Gesamtforderung" + "abzüglich Zahlung" + "Noch zu zahlen") are mapped to claim total = remaining amount and principal = principal − paid, so reconciliation compares like with like.
11. Court costs are booked as `COLLECTION_COST` (no separate ledger type); `ReferenceType` labels are matched case-insensitively and tolerate one OCR-inserted space inside compound words.
12. Modules named `types.py` were avoided (they shadow the stdlib when a script runs inside the folder): `result_types.py`, `ledger_types.py`.
13. The synthetic fixtures use only invented companies; IBANs are public example IBANs with valid checksums.
