"""Migration 4: own companies (Gesellschaften) and their hotels; scope columns on invoices, payments, documents."""

VERSION = 4
NAME = "companies_hotels"

SQL = """
CREATE TABLE companies (
    id         INTEGER PRIMARY KEY,
    name       TEXT NOT NULL UNIQUE CHECK (length(trim(name)) > 0),
    notes      TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);

CREATE TABLE hotels (
    id         INTEGER PRIMARY KEY,
    company_id INTEGER NOT NULL REFERENCES companies(id),
    name       TEXT NOT NULL CHECK (length(trim(name)) > 0),
    notes      TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    UNIQUE (company_id, name)
);
CREATE INDEX ix_hotels_company ON hotels(company_id);

ALTER TABLE invoices  ADD COLUMN company_id INTEGER REFERENCES companies(id);
ALTER TABLE invoices  ADD COLUMN hotel_id   INTEGER REFERENCES hotels(id);
ALTER TABLE payments  ADD COLUMN company_id INTEGER REFERENCES companies(id);
ALTER TABLE payments  ADD COLUMN hotel_id   INTEGER REFERENCES hotels(id);
ALTER TABLE documents ADD COLUMN company_id INTEGER REFERENCES companies(id);
ALTER TABLE documents ADD COLUMN hotel_id   INTEGER REFERENCES hotels(id);

CREATE INDEX ix_invoices_company ON invoices(company_id);
CREATE INDEX ix_invoices_hotel ON invoices(hotel_id);
CREATE INDEX ix_payments_company ON payments(company_id);
CREATE INDEX ix_documents_company ON documents(company_id);

CREATE TRIGGER trg_invoices_hotel_ins BEFORE INSERT ON invoices
WHEN NEW.hotel_id IS NOT NULL AND (SELECT company_id FROM hotels WHERE id = NEW.hotel_id) IS NOT NEW.company_id
BEGIN
    SELECT RAISE(ABORT, 'hotel does not belong to the company');
END;

CREATE TRIGGER trg_invoices_hotel_upd BEFORE UPDATE OF company_id, hotel_id ON invoices
WHEN NEW.hotel_id IS NOT NULL AND (SELECT company_id FROM hotels WHERE id = NEW.hotel_id) IS NOT NEW.company_id
BEGIN
    SELECT RAISE(ABORT, 'hotel does not belong to the company');
END;

CREATE TRIGGER trg_payments_hotel_ins BEFORE INSERT ON payments
WHEN NEW.hotel_id IS NOT NULL AND (SELECT company_id FROM hotels WHERE id = NEW.hotel_id) IS NOT NEW.company_id
BEGIN
    SELECT RAISE(ABORT, 'hotel does not belong to the company');
END;

CREATE TRIGGER trg_documents_hotel_upd BEFORE UPDATE OF company_id, hotel_id ON documents
WHEN NEW.hotel_id IS NOT NULL AND (SELECT company_id FROM hotels WHERE id = NEW.hotel_id) IS NOT NEW.company_id
BEGIN
    SELECT RAISE(ABORT, 'hotel does not belong to the company');
END;
"""
