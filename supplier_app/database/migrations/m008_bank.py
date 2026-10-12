"""Migration 8: own bank accounts, imported bank statements and their transactions."""

VERSION = 8
NAME = "bank"

SQL = """
CREATE TABLE bank_accounts (
    id         INTEGER PRIMARY KEY,
    name       TEXT NOT NULL CHECK (length(trim(name)) > 0),
    iban       TEXT NOT NULL UNIQUE CHECK (length(iban) >= 15),
    bic        TEXT NOT NULL DEFAULT '',
    company_id INTEGER REFERENCES companies(id),
    hotel_id   INTEGER REFERENCES hotels(id),
    notes      TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);

CREATE TABLE bank_statements (
    id            INTEGER PRIMARY KEY,
    account_id    INTEGER REFERENCES bank_accounts(id),
    source_name   TEXT NOT NULL,
    file_hash     TEXT NOT NULL UNIQUE,
    format        TEXT NOT NULL,
    date_from     TEXT,
    date_to       TEXT,
    opening_cents INTEGER,
    closing_cents INTEGER,
    tx_count      INTEGER NOT NULL DEFAULT 0,
    imported_at   TEXT NOT NULL
);

CREATE TABLE bank_transactions (
    id                INTEGER PRIMARY KEY,
    statement_id      INTEGER NOT NULL REFERENCES bank_statements(id) ON DELETE CASCADE,
    account_id        INTEGER REFERENCES bank_accounts(id),
    booking_date      TEXT NOT NULL,
    value_date        TEXT,
    amount_cents      INTEGER NOT NULL CHECK (amount_cents <> 0),
    currency          TEXT NOT NULL DEFAULT 'EUR',
    counterparty_name TEXT NOT NULL DEFAULT '',
    counterparty_iban TEXT NOT NULL DEFAULT '',
    purpose           TEXT NOT NULL DEFAULT '',
    booking_text      TEXT NOT NULL DEFAULT '',
    reference         TEXT NOT NULL DEFAULT '',
    fingerprint       TEXT NOT NULL UNIQUE,
    status            TEXT NOT NULL DEFAULT 'new' CHECK (status IN ('new','matched','booked','ignored')),
    supplier_id       INTEGER REFERENCES parties(id),
    invoice_ids       TEXT NOT NULL DEFAULT '',
    confidence        REAL NOT NULL DEFAULT 0,
    reasons           TEXT NOT NULL DEFAULT '',
    payment_id        INTEGER REFERENCES payments(id),
    note              TEXT NOT NULL DEFAULT '',
    created_at        TEXT NOT NULL
);
CREATE INDEX ix_banktx_statement ON bank_transactions(statement_id);
CREATE INDEX ix_banktx_status ON bank_transactions(status, booking_date);
CREATE INDEX ix_banktx_account ON bank_transactions(account_id);
CREATE INDEX ix_banktx_supplier ON bank_transactions(supplier_id);
"""

PG_EXTRA = [
    f"CREATE TRIGGER trg_bump_{t} AFTER INSERT OR UPDATE OR DELETE ON {t} FOR EACH STATEMENT EXECUTE FUNCTION bump_data_version()"
    for t in ("bank_accounts", "bank_statements", "bank_transactions")
]
