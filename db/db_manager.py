"""
db_manager.py
──────────────────────────────────────────────────────────────────
The single point of contact between Python and commissions.db.
Every other script (neo-scripts, FastAPI routers, export tools)
imports this module instead of touching sqlite3 directly, so the
schema stays consistent and foreign keys are always enforced.

Run this file directly to (re)create the database from schema.sql
and seed the service_prices / dictionary category table:

    python db_manager.py --init
    python db_manager.py --seed-dictionary ../dictionary.json
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

DB_DIR = Path(__file__).resolve().parent
DB_PATH = DB_DIR / "commissions.db"
SCHEMA_PATH = DB_DIR / "schema.sql"

VALID_CATEGORIES = [
    "Consultation", "Laboratory", "X-ray", "Ultrasound",
    "ECG", "Echocardiography", "Nursing & Procedures", "Supplies", "Other",
]

CATEGORY_COLUMN_MAP = {
    "Ultrasound": "ultrasound",
    "Laboratory": "laboratory",
    "X-ray": "x-ray",
    "Nursing & Procedures": "nursing_and_procedures",
    "Consultation": "consultation",
}


def new_batch_id() -> str:
    return uuid.uuid4().hex[:12]


@contextmanager
def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    with get_conn() as conn:
        conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
    print(f"Database initialized at {DB_PATH}")


def seed_dictionary(dictionary_path: Path) -> int:
    """Load service->category pairs from dictionary.json into
    service_prices (cost defaults to 0 and can be edited later)."""
    data = json.loads(Path(dictionary_path).read_text(encoding="utf-8"))
    n = 0
    with get_conn() as conn:
        for service, category in data.items():
            cat = category if category in VALID_CATEGORIES else "Other"
            conn.execute(
                """INSERT INTO service_prices (service_type, category, cost)
                   VALUES (?, ?, 0)
                   ON CONFLICT(service_type) DO UPDATE SET category=excluded.category""",
                (service, cat),
            )
            n += 1
    print(f"Seeded/updated {n} services from {dictionary_path}")
    return n


# ── Reference helpers used across the pipeline & API ────────────

def get_or_create_physician(conn: sqlite3.Connection, name: str) -> int:
    name = (name or "Unknown").strip()
    row = conn.execute(
        "SELECT physician_id FROM physicians WHERE physician_name = ?", (name,)
    ).fetchone()
    if row:
        return row["physician_id"]
    cur = conn.execute("INSERT INTO physicians (physician_name) VALUES (?)", (name,))
    return cur.lastrowid


def get_or_create_service(conn: sqlite3.Connection, service_type: str, category: str | None = None) -> int:
    service_type = (service_type or "Unknown").strip()
    row = conn.execute(
        "SELECT service_id FROM service_prices WHERE service_type = ?", (service_type,)
    ).fetchone()
    if row:
        return row["service_id"]
    cat = category if category in VALID_CATEGORIES else "Other"
    cur = conn.execute(
        "INSERT INTO service_prices (service_type, category, cost) VALUES (?, ?, 0)",
        (service_type, cat),
    )
    return cur.lastrowid


def start_run(batch_id: str, step: str = "started") -> None:
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO pipeline_runs (batch_id, started_at, status, step, message)
               VALUES (?, ?, 'running', ?, '')""",
            (batch_id, datetime.utcnow().isoformat(), step),
        )


def update_run(batch_id: str, step: str, message: str = "", status: str = "running") -> None:
    with get_conn() as conn:
        conn.execute(
            "UPDATE pipeline_runs SET step=?, message=?, status=? WHERE batch_id=?",
            (step, message, status, batch_id),
        )


def finish_run(batch_id: str, status: str, message: str = "") -> None:
    with get_conn() as conn:
        conn.execute(
            "UPDATE pipeline_runs SET status=?, message=?, finished_at=? WHERE batch_id=?",
            (status, message, datetime.utcnow().isoformat(), batch_id),
        )


TABLES = [
    "physicians", "service_prices", "abronal_mirror", "sot_mirror",
    "matched_records", "unmatched_records", "commission_per_physicians",
    "pipeline_runs",
]


def table_columns(table: str) -> list[str]:
    if table not in TABLES:
        raise ValueError(f"Unknown table: {table}")
    with get_conn() as conn:
        rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return [r["name"] for r in rows]


def fetch_table(table: str, filters: dict | None = None, limit: int = 5000) -> list[dict]:
    if table not in TABLES:
        raise ValueError(f"Unknown table: {table}")
    query = f"SELECT * FROM {table}"
    params: list = []
    if filters:
        clauses = []
        for col, val in filters.items():
            if val in (None, "", "All"):
                continue
            clauses.append(f'"{col}" = ?')
            params.append(val)
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
    query += f" LIMIT {int(limit)}"
    with get_conn() as conn:
        rows = conn.execute(query, params).fetchall()
    return [dict(r) for r in rows]


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Manage commissions.db")
    parser.add_argument("--init", action="store_true", help="(Re)create schema")
    parser.add_argument("--seed-dictionary", type=str, help="Path to dictionary.json")
    args = parser.parse_args()

    if args.init:
        init_db()
    if args.seed_dictionary:
        seed_dictionary(Path(args.seed_dictionary))
    if not args.init and not args.seed_dictionary:
        parser.print_help()
