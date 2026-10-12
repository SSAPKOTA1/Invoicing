"""Migration 6: more reference types (contract number, letter number); documents that wait for an invoice assignment."""

VERSION = 6
NAME = "refs_assignment"

SQL = """
CREATE TABLE document_references_new (
    id               INTEGER PRIMARY KEY,
    owner_kind       TEXT NOT NULL CHECK (owner_kind IN ('document','invoice','case')),
    owner_id         INTEGER NOT NULL,
    ref_type         TEXT NOT NULL CHECK (ref_type IN (
        'invoice_number','processing_number','file_number','case_number','claim_number',
        'customer_number','mandate_number','debtor_number','order_number','contract_number','letter_number',
        'payment_reference','other')),
    raw_value        TEXT NOT NULL CHECK (length(trim(raw_value)) > 0),
    normalized_value TEXT NOT NULL CHECK (length(normalized_value) > 0),
    created_at       TEXT NOT NULL DEFAULT '',
    UNIQUE (owner_kind, owner_id, ref_type, normalized_value)
);
INSERT INTO document_references_new(id, owner_kind, owner_id, ref_type, raw_value, normalized_value, created_at)
    SELECT id, owner_kind, owner_id, ref_type, raw_value, normalized_value, created_at FROM document_references;
DROP TABLE document_references;
ALTER TABLE document_references_new RENAME TO document_references;
CREATE INDEX ix_refs_norm ON document_references(normalized_value);
CREATE INDEX ix_refs_owner ON document_references(owner_kind, owner_id);

ALTER TABLE documents ADD COLUMN assignment_pending INTEGER NOT NULL DEFAULT 0 CHECK (assignment_pending IN (0,1));
ALTER TABLE documents ADD COLUMN pending_json TEXT NOT NULL DEFAULT '';
CREATE INDEX ix_documents_pending ON documents(assignment_pending);
"""

PG_EXTRA = [
    "SELECT setval(pg_get_serial_sequence('document_references', 'id'), COALESCE((SELECT MAX(id) FROM document_references), 0) + 1, false)",
    "CREATE TRIGGER trg_bump_document_references AFTER INSERT OR UPDATE OR DELETE ON document_references "
    "FOR EACH STATEMENT EXECUTE FUNCTION bump_data_version()",
]
