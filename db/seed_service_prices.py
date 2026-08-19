import json
import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "database" / "commissions.db"
DICT_PATH = Path(__file__).resolve().parent.parent / "configs" / "dictionary.json"

# Default cost placeholder (0 means price not set yet)
DEFAULT_COST = 0


def seed() -> None:
    with open(DICT_PATH, encoding="utf-8") as f:
        dictionary = json.load(f)

    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON")
    cur = conn.cursor()
    inserted = 0
    for service_type, category in dictionary.items():
        try:
            cur.execute(
                "INSERT OR IGNORE INTO service_prices (service_type, cost, category) VALUES (?, ?, ?)",
                (service_type, DEFAULT_COST, category)
            )
            if cur.rowcount:
                inserted += 1
        except Exception as e:
            print(f"  Warning [{service_type}]: {e}")
    conn.commit()
    conn.close()
    print(f"[seed] Inserted {inserted} service price entries from dictionary.")


if __name__ == "__main__":
    seed()
