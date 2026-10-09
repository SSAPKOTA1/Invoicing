"""Migration 2: document references (search keys) and FTS5 over OCR text."""

VERSION = 2
NAME = "references_search"

SQL = """
CREATE TABLE document_references (
    id               INTEGER PRIMARY KEY,
    owner_kind       TEXT NOT NULL CHECK (owner_kind IN ('document','invoice','case')),
    owner_id         INTEGER NOT NULL,
    ref_type         TEXT NOT NULL CHECK (ref_type IN (
        'invoice_number','processing_number','file_number','case_number','claim_number',
        'customer_number','mandate_number','debtor_number','order_number',
        'payment_reference','other')),
    raw_value        TEXT NOT NULL CHECK (length(trim(raw_value)) > 0),
    normalized_value TEXT NOT NULL CHECK (length(normalized_value) > 0),
    created_at       TEXT NOT NULL DEFAULT '',
    UNIQUE (owner_kind, owner_id, ref_type, normalized_value)
);
CREATE INDEX ix_refs_norm ON document_references(normalized_value);
CREATE INDEX ix_refs_owner ON document_references(owner_kind, owner_id);

CREATE VIRTUAL TABLE document_fts USING fts5(
    original_name, ocr_text,
    content='documents', content_rowid='id',
    tokenize='unicode61 remove_diacritics 2'
);

CREATE TRIGGER documents_ai AFTER INSERT ON documents BEGIN
    INSERT INTO document_fts(rowid, original_name, ocr_text)
    VALUES (new.id, new.original_name, new.ocr_text);
END;

CREATE TRIGGER documents_ad AFTER DELETE ON documents BEGIN
    INSERT INTO document_fts(document_fts, rowid, original_name, ocr_text)
    VALUES ('delete', old.id, old.original_name, old.ocr_text);
END;

CREATE TRIGGER documents_au AFTER UPDATE OF original_name, ocr_text ON documents BEGIN
    INSERT INTO document_fts(document_fts, rowid, original_name, ocr_text)
    VALUES ('delete', old.id, old.original_name, old.ocr_text);
    INSERT INTO document_fts(rowid, original_name, ocr_text)
    VALUES (new.id, new.original_name, new.ocr_text);
END;

INSERT INTO document_fts(document_fts) VALUES ('rebuild');
"""
