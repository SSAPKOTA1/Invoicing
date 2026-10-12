"""Migration 3: indexes for ledger/dashboard aggregation and notice lookups."""

VERSION = 3
NAME = "reporting_indexes"

SQL = """
CREATE INDEX ix_ledger_invoice ON ledger_entries(invoice_id, entry_date);
CREATE INDEX ix_ledger_supplier_date ON ledger_entries(supplier_id, entry_date);
CREATE INDEX ix_ledger_type_date ON ledger_entries(category_type, entry_date);
CREATE INDEX ix_ledger_notice ON ledger_entries(notice_id);
CREATE INDEX ix_ledger_payment ON ledger_entries(payment_id);
CREATE INDEX ix_invoices_supplier ON invoices(supplier_id, invoice_date);
CREATE INDEX ix_documents_sha ON documents(supplier_id, doc_type);
"""
