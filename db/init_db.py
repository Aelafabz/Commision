import argparse
import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "database" / "commissions.db"
SCHEMA_PATH = Path(__file__).resolve().parent / "schema.sql"


def init_db(reset: bool = False) -> None:
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON")
    cur = conn.cursor()

    if reset:
        print("[init_db] Dropping all tables...")
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
        print("[init_db] All tables dropped.")

    schema = SCHEMA_PATH.read_text(encoding="utf-8")
    conn.executescript(schema)
    conn.commit()
    conn.close()
    print(f"[init_db] Database initialized at: {DB_PATH}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Initialize the commissions database")
    parser.add_argument("--reset", action="store_true", help="Drop and recreate all tables")
    args = parser.parse_args()
    init_db(reset=args.reset)