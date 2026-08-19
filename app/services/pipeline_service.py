from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Callable

DB_PATH = Path(__file__).resolve().parent.parent.parent / "database" / "commissions.db"


class PipelineService:
    """Thin wrapper around the neo-scripts for use by the API layer."""

    @staticmethod
    def get_db_connection() -> sqlite3.Connection:
        conn = sqlite3.connect(DB_PATH)
        conn.execute("PRAGMA foreign_keys = ON")
        conn.row_factory = sqlite3.Row
        return conn

    @staticmethod
    def get_pipeline_summary() -> dict:
        """Returns counts from all key tables for dashboard display."""
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        try:
            summary = {}
            for table in ('matched_records', 'unmatched_records', 'physicians',
                          'commission_per_physicians', 'sot_mirror', 'abronal_mirror'):
                try:
                    row = conn.execute(f"SELECT COUNT(*) as cnt FROM {table}").fetchone()
                    summary[table] = row['cnt'] if row else 0
                except Exception:
                    summary[table] = 0
            return summary
        finally:
            conn.close()
