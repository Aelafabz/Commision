#!/usr/bin/env python3
"""Generate test databases for reconciliation scenarios.

Usage:
  python generate_test_data.py --scenario 1.1
  python generate_test_data.py --scenario 1.1.1
  python generate_test_data.py --scenario 1.2
  python generate_test_data.py --scenario 1.2.1

This script creates folders under the project's `data/` directory
named `test_1_1`, `test_1_1_1`, etc and initializes a `test.db`
there containing the schema and minimal sample rows for SOT and
Abronal to reproduce the described date-range reconciliation cases.

It also creates a `dev` admin user in each test DB with a printed
password so you can log into the app when running it against the
test DB (see README below how to run app using COMMISSIONS_DB).
"""
from __future__ import annotations

import argparse
import secrets
import hashlib
import sqlite3
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "data"
DB_SCHEMA_PATH = ROOT / "db" / "schema.sql"


def ensure_schema(conn: sqlite3.Connection) -> None:
    sql = DB_SCHEMA_PATH.read_text(encoding="utf-8")
    conn.executescript(sql)


def insert_sample_rows(conn: sqlite3.Connection, scenario: str) -> None:
    # Create a few services/physicians
    conn.execute("INSERT INTO service_prices (service_type, category, cost) VALUES ('Test Service','Other',0)")
    conn.execute("INSERT INTO physicians (physician_name) VALUES ('Dr. Test')")
    service_id = conn.execute("SELECT service_id FROM service_prices WHERE service_type = 'Test Service'").fetchone()[0]
    physician_id = conn.execute("SELECT physician_id FROM physicians WHERE physician_name = 'Dr. Test'").fetchone()[0]

    base = date.today()

    if scenario == "1.1":
        # SOT has wider range containing Abronal
        # Abronal payment dates concentrated in a short range
        ab_start = base - timedelta(days=10)
        ab_dates = [ab_start + timedelta(days=i) for i in range(3)]
        sot_start = ab_start - timedelta(days=5)
        sot_dates = [sot_start + timedelta(days=i) for i in range(15)]

    elif scenario == "1.1.1":
        # Re-run with abronal adjusted to match SOT (all dates overlap)
        sot_start = base - timedelta(days=20)
        sot_dates = [sot_start + timedelta(days=i) for i in range(31)]
        ab_dates = [sot_start + timedelta(days=i) for i in range(10, 20)]

    elif scenario == "1.2":
        # Abronal wider than SOT
        ab_start = base - timedelta(days=20)
        ab_dates = [ab_start + timedelta(days=i) for i in range(31)]
        sot_start = ab_start + timedelta(days=8)
        sot_dates = [sot_start + timedelta(days=i) for i in range(6)]

    elif scenario == "1.2.1":
        # Re-run with SOT expanded to match Abronal
        ab_start = base - timedelta(days=30)
        ab_dates = [ab_start + timedelta(days=i) for i in range(41)]
        sot_dates = [ab_start + timedelta(days=i) for i in range(41)]

    else:
        raise SystemExit("Unknown scenario")

    # Insert abronal rows
    for i, d in enumerate(ab_dates, start=1):
        conn.execute(
            """INSERT INTO abronal_mirror (row_number, card_number, patient_full_name, service_id, service_raw, total, net, commission_percent, commision_amount, payment_date, visit_date, status, physician_id, source_file, batch_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                i,
                f"CARD{i:03}",
                f"Patient A {i}",
                service_id,
                "Test Service",
                100.0,
                80.0,
                10.0,
                8.0,
                d.isoformat(),
                d.isoformat(),
                "paid",
                physician_id,
                "abr_test.xlsx",
                "batch-test",
            ),
        )

    # Insert sot rows
    for i, d in enumerate(sot_dates, start=1):
        conn.execute(
            """INSERT INTO sot_mirror (customer, tin_number, description, item_id, base_sku, quantity, unit_price, sub_total, tax_amount, withholding, fs_number, transaction_date, reference, MRC, service_id, source_file, batch_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                f"Customer {i}",
                f"TIN{i:05}",
                "desc",
                f"item{i}",
                f"sku{i}",
                1,
                100.0,
                100.0,
                0.0,
                "",
                i,
                d.isoformat(),
                f"ref{i}",
                "",
                service_id,
                "sot_test.xlsx",
                "batch-test",
            ),
        )

        # Also write CSV versions into data/csv_datasets/test_<scenario>/
        try:
            import csv
            csv_dir = ROOT / "data" / "csv_datasets" / f"test_{scenario}"
            csv_dir.mkdir(parents=True, exist_ok=True)

            # abronal_mirror CSV
            ab_columns = [
                "row_number", "card_number", "patient_full_name", "patient_type",
                "service_id", "service_raw", "total", "net", "commission_percent",
                "commision_amount", "payment_date", "visit_date", "status", "physician_id", "source_file", "batch_id",
            ]
            with (csv_dir / "abronal_mirror.csv").open("w", newline='', encoding='utf-8') as fh:
                writer = csv.DictWriter(fh, fieldnames=ab_columns)
                writer.writeheader()
                for i, d in enumerate(ab_dates, start=1):
                    writer.writerow({
                        "row_number": i,
                        "card_number": f"CARD{i:03}",
                        "patient_full_name": f"Patient A {i}",
                        "patient_type": "",
                        "service_id": service_id,
                        "service_raw": "Test Service",
                        "total": 100.0,
                        "net": 80.0,
                        "commission_percent": 10.0,
                        "commision_amount": 8.0,
                        "payment_date": (ab_dates[i-1]).isoformat(),
                        "visit_date": (ab_dates[i-1]).isoformat(),
                        "status": "paid",
                        "physician_id": physician_id,
                        "source_file": "abr_test.xlsx",
                        "batch_id": "batch-test",
                    })

            # sot_mirror CSV
            sot_columns = [
                "customer", "tin_number", "description", "item_id", "base_sku", "quantity", "unit_price", "sub_total", "tax_amount", "withholding", "fs_number", "transaction_date", "reference", "MRC", "service_id", "source_file", "batch_id",
            ]
            with (csv_dir / "sot_mirror.csv").open("w", newline='', encoding='utf-8') as fh:
                writer = csv.DictWriter(fh, fieldnames=sot_columns)
                writer.writeheader()
                for i, d in enumerate(sot_dates, start=1):
                    writer.writerow({
                        "customer": f"Customer {i}",
                        "tin_number": f"TIN{i:05}",
                        "description": "desc",
                        "item_id": f"item{i}",
                        "base_sku": f"sku{i}",
                        "quantity": 1,
                        "unit_price": 100.0,
                        "sub_total": 100.0,
                        "tax_amount": 0.0,
                        "withholding": "",
                        "fs_number": i,
                        "transaction_date": (sot_dates[i-1]).isoformat(),
                        "reference": f"ref{i}",
                        "MRC": "",
                        "service_id": service_id,
                        "source_file": "sot_test.xlsx",
                        "batch_id": "batch-test",
                    })

            # service_prices CSV
            sp_cols = ["service_id", "service_type", "category", "cost"]
            with (csv_dir / "service_prices.csv").open("w", newline='', encoding='utf-8') as fh:
                writer = csv.DictWriter(fh, fieldnames=sp_cols)
                writer.writeheader()
                writer.writerow({"service_id": service_id, "service_type": "Test Service", "category": "Other", "cost": 0})

            # physicians CSV
            ph_cols = ["physician_id", "physician_name"]
            with (csv_dir / "physicians.csv").open("w", newline='', encoding='utf-8') as fh:
                writer = csv.DictWriter(fh, fieldnames=ph_cols)
                writer.writeheader()
                writer.writerow({"physician_id": physician_id, "physician_name": "Dr. Test"})
        except Exception:
            # non-fatal if CSV writing fails
            pass


def create_test_db(scenario: str, dest_dir: Path) -> Path:
    dest_dir.mkdir(parents=True, exist_ok=True)
    db_path = dest_dir / "test.db"
    if db_path.exists():
        db_path.unlink()
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        ensure_schema(conn)
        insert_sample_rows(conn, scenario)
        # create a dev admin user with known password in the test DB
        password = secrets.token_urlsafe(8)
        # PBKDF2-HMAC-SHA256 compatible with db_manager.hash_password
        salt = secrets.token_bytes(16)
        dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 200_000)
        pass_hash = f"{salt.hex()}${dk.hex()}"
        conn.execute(
            "INSERT INTO users (username, pass_hash, role, created_at) VALUES (?, ?, ?, datetime('now'))",
            ("dev", pass_hash, "admin"),
        )
        conn.commit()
        # Print the generated password so the operator can log in as `dev`.
        print("Created test user:")
        print("  username: dev")
        print(f"  password: {password}")
    finally:
        conn.close()
    return db_path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--scenario", required=True, help="Scenario to generate (1.1, 1.1.1, 1.2, 1.2.1)")
    args = parser.parse_args()
    scenario = args.scenario.replace(".", "_")
    dest = DATA_DIR / f"test_{scenario}"
    print(f"Creating test DB for scenario {args.scenario} in {dest}")
    db = create_test_db(args.scenario, dest)
    print(f"Created {db}")
    print("")
    print("To run the app against this test DB, start the server with:")
    print("  COMMISSIONS_DB=./data/test_{} python backend/main.py".format(scenario))


if __name__ == "__main__":
    main()
