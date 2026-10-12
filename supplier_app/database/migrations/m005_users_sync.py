"""Migration 5: application users (multi-user mode), user name in the audit log, change counter, document files."""

VERSION = 5
NAME = "users_sync"

SQL = """
CREATE TABLE app_users (
    id            INTEGER PRIMARY KEY,
    username      TEXT NOT NULL UNIQUE CHECK (length(trim(username)) > 0),
    display_name  TEXT NOT NULL DEFAULT '',
    password_hash TEXT NOT NULL,
    password_salt TEXT NOT NULL,
    role          TEXT NOT NULL CHECK (role IN ('admin','editor','viewer')),
    active        INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0,1)),
    failed_logins INTEGER NOT NULL DEFAULT 0,
    locked_until  TEXT,
    created_at    TEXT NOT NULL,
    last_login    TEXT
);

CREATE UNIQUE INDEX ux_users_lower ON app_users(lower(username));

ALTER TABLE audit_log ADD COLUMN username TEXT NOT NULL DEFAULT '';

CREATE TABLE data_version (
    id         INTEGER PRIMARY KEY CHECK (id = 1),
    version    INTEGER NOT NULL DEFAULT 0,
    changed_by TEXT NOT NULL DEFAULT ''
);
INSERT INTO data_version(id, version) VALUES (1, 0);

CREATE TABLE document_files (
    document_id INTEGER PRIMARY KEY REFERENCES documents(id) ON DELETE CASCADE,
    content     BLOB NOT NULL
);
"""

_TABLES = ("parties", "party_aliases", "party_ibans", "documents", "document_files", "invoices", "cases", "case_events",
           "dunning_notices", "notice_invoices", "payments", "payment_allocations", "ledger_entries", "interest_rates",
           "categories", "settings", "companies", "hotels", "document_references", "app_users")

PG_EXTRA = [
    """CREATE FUNCTION bump_data_version() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    UPDATE data_version SET version = version + 1, changed_by = coalesce(current_setting('supplier.user', true), '') WHERE id = 1;
    RETURN NULL;
END $$""",
    *[f"CREATE TRIGGER trg_bump_{t} AFTER INSERT OR UPDATE OR DELETE ON {t} FOR EACH STATEMENT EXECUTE FUNCTION bump_data_version()"
      for t in _TABLES],
]
