PRAGMA foreign_keys = ON;

-- Master physician table
CREATE TABLE IF NOT EXISTS physicians (
    id   INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT    NOT NULL UNIQUE
);

-- Service price catalog; maps service names to cost and category
CREATE TABLE IF NOT EXISTS service_prices (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    service_type TEXT    NOT NULL UNIQUE,
    cost         NUMERIC NOT NULL DEFAULT 0,
    category     TEXT    NOT NULL DEFAULT 'Other'
);

-- Raw SOT (Source of Truth) mirror
CREATE TABLE IF NOT EXISTS sot_mirror (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    customer         TEXT    NOT NULL,
    tin_number       TEXT,
    description      TEXT    NOT NULL,
    item_id          TEXT,
    base_sku         TEXT    NOT NULL,
    quantity         INTEGER NOT NULL DEFAULT 1,
    unit_price       NUMERIC NOT NULL,
    sub_total        NUMERIC NOT NULL,
    tax_amount       REAL,
    withholding      TEXT,
    fs_number        INTEGER,
    transaction_date TEXT    NOT NULL,
    reference        TEXT,
    MRC              TEXT,
    physician_id     INTEGER REFERENCES physicians(id) ON DELETE SET NULL
);

-- Raw Abronal mirror (scraped from Abronal eHealth)
CREATE TABLE IF NOT EXISTS abronal_mirror (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    row_number        INTEGER,
    card_number       TEXT,
    patient_full_name TEXT    NOT NULL,
    patient_type      TEXT,
    service           TEXT,
    total             NUMERIC,
    net               NUMERIC,
    commission_percent REAL,
    commission_amount  REAL,
    payment_date      TEXT,
    visit_date        TEXT,
    status            TEXT,
    physician_id      INTEGER REFERENCES physicians(id) ON DELETE SET NULL
);

-- Records that matched between Abronal and SOT
CREATE TABLE IF NOT EXISTS matched_records (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    patient_name TEXT    NOT NULL,
    service_type TEXT    NOT NULL,
    category     TEXT    NOT NULL DEFAULT 'Other',
    total_amount REAL    NOT NULL,
    net_amount   REAL    NOT NULL,
    payment_date TEXT    NOT NULL,
    physician_id INTEGER NOT NULL REFERENCES physicians(id) ON DELETE CASCADE,
    match_type   TEXT    NOT NULL DEFAULT 'perfect'
);

-- Records that failed reconciliation (mismatches)
CREATE TABLE IF NOT EXISTS unmatched_records (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    abronal_patient_name  TEXT    NOT NULL,
    abronal_service_type  TEXT    NOT NULL,
    abronal_net_amount    NUMERIC NOT NULL,
    abronal_payment_date  TEXT    NOT NULL,
    physician_id          INTEGER NOT NULL REFERENCES physicians(id) ON DELETE CASCADE,
    sot_patient_name      TEXT    NOT NULL,
    sot_service_type      TEXT    NOT NULL,
    sot_amount            NUMERIC NOT NULL,
    sot_payment_date      TEXT    NOT NULL,
    reason_for_mismatch   TEXT    NOT NULL
);

-- Final aggregated commission per physician
-- category columns map to the 5 core service categories + extras
CREATE TABLE IF NOT EXISTS commission_per_physicians (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    physician_id            INTEGER NOT NULL REFERENCES physicians(id) ON DELETE CASCADE,
    period_start            TEXT,
    period_end              TEXT,
    ultrasound              NUMERIC NOT NULL DEFAULT 0,
    laboratory              NUMERIC NOT NULL DEFAULT 0,
    x_ray                   NUMERIC NOT NULL DEFAULT 0,
    nursing_and_procedures  NUMERIC NOT NULL DEFAULT 0,
    consultation            NUMERIC NOT NULL DEFAULT 0,
    ecg                     NUMERIC NOT NULL DEFAULT 0,
    echocardiography        NUMERIC NOT NULL DEFAULT 0,
    supplies                NUMERIC NOT NULL DEFAULT 0,
    other                   NUMERIC NOT NULL DEFAULT 0,
    total                   NUMERIC NOT NULL DEFAULT 0,
    commission_percent      REAL    NOT NULL DEFAULT 0,
    commission_amount       REAL    NOT NULL DEFAULT 0,
    UNIQUE(physician_id, period_start, period_end)
);

-- Run log for pipeline executions
CREATE TABLE IF NOT EXISTS run_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id      TEXT    NOT NULL UNIQUE,
    step        TEXT    NOT NULL,
    status      TEXT    NOT NULL DEFAULT 'running',
    started_at  TEXT    NOT NULL DEFAULT (datetime('now')),
    finished_at TEXT,
    message     TEXT
);
