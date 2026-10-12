"""Migration 7: recurring invoices (rent and other fixed payments) with effective-dated amounts and a run log."""

VERSION = 7
NAME = "recurring"

SQL = """
CREATE TABLE recurring_invoices (
    id             INTEGER PRIMARY KEY,
    supplier_id    INTEGER NOT NULL REFERENCES parties(id),
    title          TEXT NOT NULL CHECK (length(trim(title)) > 0),
    period         TEXT NOT NULL CHECK (period IN ('monthly','quarterly','half_yearly','yearly')),
    day_of_month   INTEGER NOT NULL DEFAULT 1 CHECK (day_of_month BETWEEN 1 AND 31),
    start_date     TEXT NOT NULL,
    end_date       TEXT,
    due_days       INTEGER NOT NULL DEFAULT 0 CHECK (due_days >= 0),
    number_pattern TEXT NOT NULL DEFAULT '',
    vat_rate       TEXT NOT NULL DEFAULT '0',
    notes          TEXT NOT NULL DEFAULT '',
    category_id    INTEGER REFERENCES categories(id) ON DELETE SET NULL,
    company_id     INTEGER REFERENCES companies(id),
    hotel_id       INTEGER REFERENCES hotels(id),
    active         INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0,1)),
    created_at     TEXT NOT NULL
);
CREATE INDEX ix_recurring_supplier ON recurring_invoices(supplier_id);

CREATE TABLE recurring_amounts (
    id           INTEGER PRIMARY KEY,
    recurring_id INTEGER NOT NULL REFERENCES recurring_invoices(id) ON DELETE CASCADE,
    valid_from   TEXT NOT NULL,
    gross_cents  INTEGER NOT NULL CHECK (gross_cents > 0),
    UNIQUE (recurring_id, valid_from)
);

CREATE TABLE recurring_runs (
    id           INTEGER PRIMARY KEY,
    recurring_id INTEGER NOT NULL REFERENCES recurring_invoices(id) ON DELETE CASCADE,
    occurrence   TEXT NOT NULL,
    invoice_id   INTEGER NOT NULL REFERENCES invoices(id),
    created_at   TEXT NOT NULL,
    UNIQUE (recurring_id, occurrence)
);
CREATE INDEX ix_recurring_runs_invoice ON recurring_runs(invoice_id);
"""

PG_EXTRA = [
    f"CREATE TRIGGER trg_bump_{t} AFTER INSERT OR UPDATE OR DELETE ON {t} FOR EACH STATEMENT EXECUTE FUNCTION bump_data_version()"
    for t in ("recurring_invoices", "recurring_amounts", "recurring_runs")
]
