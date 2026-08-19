"""
Migration script: migrate existing commissions.db to the new schema with foreign keys.
Usage: python db/migrate_db.py

This script:
1. Reads existing data from old tables
2. Recreates schema with proper foreign keys
3. Re-inserts data preserving existing records
"""
import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "database" / "commissions.db"
SCHEMA_PATH = Path(__file__).resolve().parent / "schema.sql"


def migrate() -> None:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    print("[migrate] Reading existing data...")

    # Read existing data from old tables (if they exist)
    old_service_prices = []
    old_commission_per_physicians = []
    try:
        old_service_prices = cur.execute(
            "SELECT service_type, cost FROM service_prices"
        ).fetchall()
    except Exception:
        pass
    try:
        old_commission_per_physicians = cur.execute(
            "SELECT physician_name, ultrasound, laboratory, [x-ray], "
            "nursing_and_procedures, consultation, total, "
            "commision_percent, commision_amount FROM commission_per_physicians"
        ).fetchall()
    except Exception:
        pass

    print(f"[migrate] Found {len(old_service_prices)} service prices, "
          f"{len(old_commission_per_physicians)} physician commission records")

    # Drop old tables and recreate
    print("[migrate] Recreating schema...")
    cur.executescript("""
        PRAGMA foreign_keys = OFF;
        DROP TABLE IF EXISTS run_log;
        DROP TABLE IF EXISTS commission_per_physicians;
        DROP TABLE IF EXISTS unmatched_records;
        DROP TABLE IF EXISTS matched_records;
        DROP TABLE IF EXISTS abronal_mirror;
        DROP TABLE IF EXISTS sot_mirror;
        DROP TABLE IF EXISTS service_prices;
        DROP TABLE IF EXISTS physicians;
        PRAGMA foreign_keys = ON;
    """)

    schema = SCHEMA_PATH.read_text(encoding="utf-8")
    conn.executescript(schema)
    conn.commit()

    # Re-insert service prices
    if old_service_prices:
        print("[migrate] Restoring service prices...")
        for row in old_service_prices:
            try:
                cur.execute(
                    "INSERT OR IGNORE INTO service_prices (service_type, cost) VALUES (?, ?)",
                    (row["service_type"], row["cost"])
                )
            except Exception as e:
                print(f"  Warning: {e}")

    # Re-insert physicians and commission records
    if old_commission_per_physicians:
        print("[migrate] Restoring physician commission records...")
        for row in old_commission_per_physicians:
            physician_name = row["physician_name"]
            # Insert physician
            cur.execute(
                "INSERT OR IGNORE INTO physicians (name) VALUES (?)",
                (physician_name,)
            )
            cur.execute("SELECT id FROM physicians WHERE name = ?", (physician_name,))
            phys_row = cur.fetchone()
            if phys_row:
                phys_id = phys_row["id"]
                try:
                    cur.execute("""
                        INSERT OR IGNORE INTO commission_per_physicians
                        (physician_id, ultrasound, laboratory, x_ray,
                         nursing_and_procedures, consultation, total,
                         commission_percent, commission_amount)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        phys_id,
                        row["ultrasound"],
                        row["laboratory"],
                        row["x-ray"],
                        row["nursing_and_procedures"],
                        row["consultation"],
                        row["total"],
                        row["commision_percent"],
                        row["commision_amount"],
                    ))
                except Exception as e:
                    print(f"  Warning for {physician_name}: {e}")

    conn.commit()
    conn.close()
    print("[migrate] Migration complete.")


if __name__ == "__main__":
    migrate()
