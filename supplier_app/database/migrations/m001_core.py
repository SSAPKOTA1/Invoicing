"""Migration 1: core tables."""

VERSION = 1
NAME = "core"

_TYPES = "'INVOICE','CREDIT_NOTE','PAYMENT','DUNNING_FEE','LATE_INTEREST','LATE_PAYMENT_FLAT_FEE','COLLECTION_COST','ADJUSTMENT','WRITE_OFF'"

SQL = f"""
CREATE TABLE settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE categories (
    id   INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE CHECK (length(trim(name)) > 0)
);

CREATE TABLE parties (
    id         INTEGER PRIMARY KEY,
    role       TEXT NOT NULL CHECK (role IN ('supplier','collection_agency','other')),
    name       TEXT NOT NULL CHECK (length(trim(name)) > 0),
    name_norm  TEXT NOT NULL,
    address    TEXT NOT NULL DEFAULT '',
    vat_id     TEXT NOT NULL DEFAULT '',
    tax_number TEXT NOT NULL DEFAULT '',
    email      TEXT NOT NULL DEFAULT '',
    phone      TEXT NOT NULL DEFAULT '',
    contact    TEXT NOT NULL DEFAULT '',
    payment_terms TEXT NOT NULL DEFAULT '',
    notes      TEXT NOT NULL DEFAULT '',
    represents_supplier_id INTEGER REFERENCES parties(id) ON DELETE SET NULL,
    created_at TEXT NOT NULL,
    CHECK (represents_supplier_id IS NULL OR role = 'collection_agency')
);
CREATE INDEX ix_parties_name_norm ON parties(name_norm);
CREATE INDEX ix_parties_role ON parties(role);

CREATE TABLE party_aliases (
    id         INTEGER PRIMARY KEY,
    party_id   INTEGER NOT NULL REFERENCES parties(id) ON DELETE CASCADE,
    alias      TEXT NOT NULL CHECK (length(trim(alias)) > 0),
    alias_norm TEXT NOT NULL,
    UNIQUE (party_id, alias_norm)
);
CREATE INDEX ix_party_aliases_norm ON party_aliases(alias_norm);

CREATE TABLE party_ibans (
    id       INTEGER PRIMARY KEY,
    party_id INTEGER NOT NULL REFERENCES parties(id) ON DELETE CASCADE,
    iban     TEXT NOT NULL CHECK (length(iban) BETWEEN 15 AND 34),
    UNIQUE (party_id, iban)
);
CREATE INDEX ix_party_ibans_iban ON party_ibans(iban);

CREATE TABLE documents (
    id            INTEGER PRIMARY KEY,
    stored_path   TEXT NOT NULL,
    sha256        TEXT NOT NULL UNIQUE CHECK (length(sha256) = 64),
    original_name TEXT NOT NULL,
    page_count    INTEGER NOT NULL DEFAULT 1 CHECK (page_count >= 0),
    doc_type      TEXT NOT NULL DEFAULT 'other',
    ocr_text      TEXT NOT NULL DEFAULT '',
    extraction_json TEXT NOT NULL DEFAULT '',
    review_status TEXT NOT NULL DEFAULT 'pending'
        CHECK (review_status IN ('pending','needs_review','accepted','rejected')),
    confidence    REAL NOT NULL DEFAULT 0 CHECK (confidence BETWEEN 0 AND 1),
    supplier_id   INTEGER REFERENCES parties(id) ON DELETE SET NULL,
    text_source   TEXT NOT NULL DEFAULT '',
    created_at    TEXT NOT NULL
);
CREATE INDEX ix_documents_review ON documents(review_status);

CREATE TABLE invoices (
    id             INTEGER PRIMARY KEY,
    supplier_id    INTEGER NOT NULL REFERENCES parties(id),
    invoice_number TEXT NOT NULL CHECK (length(trim(invoice_number)) > 0),
    invoice_number_norm TEXT NOT NULL,
    invoice_date   TEXT NOT NULL,
    due_date       TEXT,
    net_cents      INTEGER NOT NULL DEFAULT 0,
    vat_rate       TEXT NOT NULL DEFAULT '19',
    vat_cents      INTEGER NOT NULL DEFAULT 0,
    gross_cents    INTEGER NOT NULL CHECK (gross_cents >= 0),
    currency       TEXT NOT NULL DEFAULT 'EUR' CHECK (length(currency) = 3),
    status         TEXT NOT NULL DEFAULT 'open'
        CHECK (status IN ('open','partially_paid','paid','disputed','cancelled')),
    notes          TEXT NOT NULL DEFAULT '',
    category_id    INTEGER REFERENCES categories(id) ON DELETE SET NULL,
    created_at     TEXT NOT NULL,
    UNIQUE (supplier_id, invoice_number)
);
CREATE INDEX ix_invoices_norm ON invoices(invoice_number_norm);
CREATE INDEX ix_invoices_due ON invoices(due_date);
CREATE INDEX ix_invoices_status ON invoices(status);

CREATE TABLE cases (
    id          INTEGER PRIMARY KEY,
    supplier_id INTEGER NOT NULL REFERENCES parties(id),
    invoice_id  INTEGER REFERENCES invoices(id),
    title       TEXT NOT NULL DEFAULT '',
    status      TEXT NOT NULL DEFAULT 'open'
        CHECK (status IN ('open','waiting','in_dispute','paid','closed')),
    notes       TEXT NOT NULL DEFAULT '',
    auto_opened INTEGER NOT NULL DEFAULT 1 CHECK (auto_opened IN (0,1)),
    opened_at   TEXT NOT NULL,
    closed_at   TEXT
);
CREATE UNIQUE INDEX ux_cases_invoice ON cases(invoice_id) WHERE invoice_id IS NOT NULL;

CREATE TABLE case_events (
    id         INTEGER PRIMARY KEY,
    case_id    INTEGER NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
    event_date TEXT NOT NULL,
    kind       TEXT NOT NULL,
    text       TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);
CREATE INDEX ix_case_events_case ON case_events(case_id);

CREATE TABLE dunning_notices (
    id              INTEGER PRIMARY KEY,
    sender_party_id INTEGER NOT NULL REFERENCES parties(id),
    supplier_id     INTEGER NOT NULL REFERENCES parties(id),
    notice_date     TEXT NOT NULL,
    level           INTEGER NOT NULL CHECK (level BETWEEN 1 AND 6),
    new_deadline    TEXT,
    principal_cents INTEGER NOT NULL DEFAULT 0 CHECK (principal_cents >= 0),
    fees_cents      INTEGER NOT NULL DEFAULT 0 CHECK (fees_cents >= 0),
    interest_cents  INTEGER NOT NULL DEFAULT 0 CHECK (interest_cents >= 0),
    flat_fee_cents  INTEGER NOT NULL DEFAULT 0 CHECK (flat_fee_cents >= 0),
    other_costs_cents INTEGER NOT NULL DEFAULT 0 CHECK (other_costs_cents >= 0),
    total_claimed_cents INTEGER NOT NULL DEFAULT 0 CHECK (total_claimed_cents >= 0),
    credited_cents  INTEGER NOT NULL DEFAULT 0 CHECK (credited_cents >= 0),
    document_id     INTEGER REFERENCES documents(id) ON DELETE SET NULL,
    case_id         INTEGER REFERENCES cases(id) ON DELETE SET NULL,
    notes           TEXT NOT NULL DEFAULT '',
    dedup_key       TEXT NOT NULL UNIQUE,
    created_at      TEXT NOT NULL
);
CREATE INDEX ix_notices_supplier ON dunning_notices(supplier_id, notice_date);
CREATE INDEX ix_notices_case ON dunning_notices(case_id);

CREATE TABLE notice_invoices (
    id         INTEGER PRIMARY KEY,
    notice_id  INTEGER NOT NULL REFERENCES dunning_notices(id) ON DELETE CASCADE,
    invoice_id INTEGER NOT NULL REFERENCES invoices(id),
    principal_cents   INTEGER NOT NULL DEFAULT 0 CHECK (principal_cents >= 0),
    fees_cents        INTEGER NOT NULL DEFAULT 0 CHECK (fees_cents >= 0),
    interest_cents    INTEGER NOT NULL DEFAULT 0 CHECK (interest_cents >= 0),
    flat_fee_cents    INTEGER NOT NULL DEFAULT 0 CHECK (flat_fee_cents >= 0),
    other_costs_cents INTEGER NOT NULL DEFAULT 0 CHECK (other_costs_cents >= 0),
    total_cents       INTEGER NOT NULL DEFAULT 0 CHECK (total_cents >= 0),
    UNIQUE (notice_id, invoice_id)
);
CREATE INDEX ix_notice_invoices_invoice ON notice_invoices(invoice_id);

CREATE TABLE payments (
    id             INTEGER PRIMARY KEY,
    supplier_id    INTEGER NOT NULL REFERENCES parties(id),
    payment_date   TEXT NOT NULL,
    amount_cents   INTEGER NOT NULL CHECK (amount_cents > 0),
    method         TEXT NOT NULL DEFAULT 'bank_transfer'
        CHECK (method IN ('bank_transfer','direct_debit','cash','card','other')),
    bank_reference TEXT NOT NULL DEFAULT '',
    iban           TEXT NOT NULL DEFAULT '',
    notes          TEXT NOT NULL DEFAULT '',
    document_id    INTEGER REFERENCES documents(id) ON DELETE SET NULL,
    created_at     TEXT NOT NULL
);
CREATE INDEX ix_payments_supplier ON payments(supplier_id, payment_date);

CREATE TABLE payment_allocations (
    id           INTEGER PRIMARY KEY,
    payment_id   INTEGER NOT NULL REFERENCES payments(id),
    invoice_id   INTEGER NOT NULL REFERENCES invoices(id),
    component    TEXT NOT NULL CHECK (component IN ('costs','interest','principal')),
    amount_cents INTEGER NOT NULL CHECK (amount_cents <> 0)
);
CREATE INDEX ix_alloc_payment ON payment_allocations(payment_id);
CREATE INDEX ix_alloc_invoice ON payment_allocations(invoice_id);

CREATE TABLE ledger_entries (
    id           INTEGER PRIMARY KEY,
    entry_date   TEXT NOT NULL,
    supplier_id  INTEGER NOT NULL REFERENCES parties(id),
    invoice_id   INTEGER REFERENCES invoices(id),
    entry_type   TEXT NOT NULL CHECK (entry_type IN ({_TYPES},'REVERSAL')),
    category_type TEXT NOT NULL CHECK (category_type IN ({_TYPES})),
    amount_cents INTEGER NOT NULL CHECK (amount_cents <> 0),
    document_id  INTEGER REFERENCES documents(id) ON DELETE SET NULL,
    notice_id    INTEGER REFERENCES dunning_notices(id),
    payment_id   INTEGER REFERENCES payments(id),
    reverses_entry_id INTEGER REFERENCES ledger_entries(id),
    comment      TEXT NOT NULL DEFAULT '',
    created_at   TEXT NOT NULL,
    CHECK ((entry_type = 'REVERSAL') = (reverses_entry_id IS NOT NULL)),
    CHECK (entry_type = 'REVERSAL' OR category_type = entry_type),
    CHECK (entry_type <> 'PAYMENT' OR amount_cents < 0),
    CHECK (entry_type <> 'CREDIT_NOTE' OR amount_cents < 0),
    CHECK (entry_type <> 'WRITE_OFF' OR amount_cents < 0),
    CHECK (entry_type NOT IN ('INVOICE','DUNNING_FEE','LATE_INTEREST',
                              'LATE_PAYMENT_FLAT_FEE','COLLECTION_COST') OR amount_cents > 0)
);
CREATE UNIQUE INDEX ux_ledger_reversal ON ledger_entries(reverses_entry_id)
    WHERE reverses_entry_id IS NOT NULL;

CREATE TRIGGER trg_ledger_no_update BEFORE UPDATE ON ledger_entries
BEGIN
    SELECT RAISE(ABORT, 'ledger entries are immutable (append-only)');
END;

CREATE TRIGGER trg_ledger_no_delete BEFORE DELETE ON ledger_entries
BEGIN
    SELECT RAISE(ABORT, 'ledger entries cannot be deleted (use a reversal)');
END;

CREATE TABLE interest_rates (
    id         INTEGER PRIMARY KEY,
    valid_from TEXT NOT NULL UNIQUE,
    base_rate  TEXT NOT NULL
);

CREATE TABLE audit_log (
    id         INTEGER PRIMARY KEY,
    created_at TEXT NOT NULL,
    action     TEXT NOT NULL,
    entity     TEXT NOT NULL,
    entity_id  INTEGER,
    details    TEXT NOT NULL DEFAULT ''
);
CREATE INDEX ix_audit_created ON audit_log(created_at);
"""
