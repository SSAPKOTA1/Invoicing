# Decisions

1. Repo root is the project root; the Python package is `supplier_app/`. The environment fixed the working branch `claude/zen-cannon-x8l4cj` instead of `build/initial`.
2. Dev venv at `.venv` (ignored). Local Python is 3.13, CI targets 3.11; code stays 3.11-compatible.
3. Ledger entries carry both `entry_type` (incl. `REVERSAL`) and `category_type` (economic type; for reversals the type of the reversed entry) so SQL aggregates and the pure engine need no joins.
4. Notice claims are cumulative per invoice (principal / fees / interest / flat fee / other costs). Booking posts only the delta against charges already in the ledger, which prevents double counting when later letters restate earlier fees.
5. Unapplied payment money is a PAYMENT ledger entry with `invoice_id = NULL` (credit on account of the supplier).
6. Interest: days counted for `due < d <= until`; a payment on day P reduces the principal from P+1. Interest rounded once (ROUND_HALF_UP). Seeded base rates are defaults to verify, not legal advice.
7. Money is integer cents; VAT rate is stored as text decimal; interest rate as `Decimal`.
8. Extra column `flat_fee_cents` on notices (Verzugspauschale) in addition to the fields in the brief.
