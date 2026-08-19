BEGIN TRANSACTION;
CREATE TABLE IF NOT EXISTS "abronal_mirror" (
	"row_number"	INTEGER NOT NULL,
	"card_number"	TEXT NOT NULL,
	"patient_full_name"	TEXT NOT NULL,
	"patient_type"	TEXT,
	"service"	TEXT,
	"total"	NUMERIC,
	"net"	NUMERIC,
	"commission_percent"	REAL,
	"commision_amount"	REAL,
	"payment_date"	TEXT,
	"visit_date"	TEXT,
	"status"	TEXT,
	"physician_name"	TEXT,
	PRIMARY KEY("patient_full_name")
);
CREATE TABLE IF NOT EXISTS "commission_per_physicians" (
	"physician_name"	TEXT NOT NULL,
	"ultrasound"	NUMERIC NOT NULL,
	"laboratory"	NUMERIC NOT NULL,
	"x-ray"	NUMERIC NOT NULL,
	"nursing_and_procedures"	NUMERIC NOT NULL,
	"consultation"	NUMERIC NOT NULL,
	"total"	NUMERIC NOT NULL,
	"commision_percent"	REAL NOT NULL,
	"commision_amount"	REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS "matched_records" (
	"patient_name"	TEXT NOT NULL,
	"service_type"	TEXT NOT NULL,
	"total_amount"	REAL NOT NULL,
	"net_amount"	REAL NOT NULL,
	"payment_date"	TEXT NOT NULL,
	"physician_name"	TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS "service_prices" (
	"service_type"	TEXT NOT NULL,
	"cost"	NUMERIC NOT NULL
);
CREATE TABLE IF NOT EXISTS "sot_mirror" (
	"customer"	TEXT NOT NULL,
	"tin_number"	TEXT,
	"description"	TEXT NOT NULL,
	"item_id"	TEXT,
	"base_sku"	TEXT NOT NULL,
	"quantity"	INTEGER NOT NULL,
	"unit_price"	NUMERIC NOT NULL,
	"sub_total"	NUMERIC NOT NULL,
	"tax_amount"	REAL,
	"withholding"	TEXT,
	"fs_number"	INTEGER NOT NULL,
	"transaction_date"	TEXT NOT NULL,
	"reference"	TEXT NOT NULL,
	"MRC"	TEXT NOT NULL,
	PRIMARY KEY("customer")
);
CREATE TABLE IF NOT EXISTS "unmatched_records" (
	"abronal_patient_name"	TEXT NOT NULL,
	"abronal_service_type"	TEXT NOT NULL,
	"abronal_net_amount"	NUMERIC NOT NULL,
	"abronal_payment_date"	TEXT NOT NULL,
	"physician_name"	TEXT NOT NULL,
	"sot_patient_name"	TEXT NOT NULL,
	"sot_service_type"	TEXT NOT NULL,
	"sot_amount"	NUMERIC NOT NULL,
	"sot_payment_date"	TEXT NOT NULL,
	"reason_for_mismatch"	TEXT NOT NULL
);
COMMIT;
