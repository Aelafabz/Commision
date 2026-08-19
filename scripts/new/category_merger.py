"""
category_merger.py
Final aggregation stage of the reconciliation pipeline.

Philosophy:
- No tkinter / GUI dependencies
- Progress reported via a callback: progress_cb(step: str, pct: int, msg: str)
- Groups matched_records by (patient_name, physician_id), sums total_amount
  per category, and writes the rollup to commission_per_physicians
"""
from __future__ import annotations

import json
import sqlite3
from collections import defaultdict
from pathlib import Path
from typing import Callable

DB_PATH = Path(__file__).resolve().parent.parent.parent / "database" / "commissions.db"
DICT_PATH = Path(__file__).resolve().parent.parent.parent / "configs" / "dictionary.json"


# ── Condensor ─────────────────────────────────────────────────────────────────

class Condensor:
    """
    Reads matched_records, groups rows by (patient_name, physician_id), sums
    total_amount per category within each group, and persists the rollup to
    commission_per_physicians.
    """

    def __init__(self, conn: sqlite3.Connection, dict_path: str | Path = DICT_PATH):
        self.conn = conn
        self.dictionary: dict[str, str] = {}
        self.data: list[dict] = []
        self.condensed: list[dict] = []
        self.read_dictionary(dict_path)

    # ── Loading ──────────────────────────────────────────────────────────

    def read_dictionary(self, path: str | Path) -> dict[str, str]:
        """Load service → category mapping from dictionary.json."""
        path = Path(path)
        if path.exists():
            with open(path, encoding='utf-8') as f:
                self.dictionary = json.load(f)
        else:
            self.dictionary = {}
        return self.dictionary

    def load_data(self) -> list[dict]:
        """Load matched_records rows from the DB, joined with physician name."""
        self.conn.row_factory = sqlite3.Row
        cur = self.conn.execute("""
            SELECT m.*, p.name AS physician_name
            FROM matched_records m
            LEFT JOIN physicians p ON p.id = m.physician_id
        """)
        self.data = [dict(r) for r in cur.fetchall()]
        self.conn.row_factory = None
        return self.data

    # ── Aggregation ──────────────────────────────────────────────────────

    def list_condensor(
        self,
        progress_cb: Callable[[str, int, str], None] | None = None,
    ) -> list[dict]:
        """
        Group loaded matched_records by (patient_name, physician_id), sum
        total_amount per category, and write the rollup into
        commission_per_physicians.
        """
        if not self.data:
            self.load_data()

        sums: dict[tuple, dict] = defaultdict(lambda: defaultdict(float))
        counts: dict[tuple, dict] = defaultdict(lambda: defaultdict(int))
        physician_names: dict[int, str] = {}

        total = len(self.data) or 1
        for idx, row in enumerate(self.data):
            if progress_cb and idx % 50 == 0:
                progress_cb('condense', 20 + int(50 * idx / total), f"Grouping {idx + 1}/{total}")

            patient = row.get('patient_name') or 'Unknown'
            physician_id = row.get('physician_id')
            category = row.get('category') or self.dictionary.get(row.get('service_type', ''), 'Other')
            try:
                amount = float(row.get('total_amount') or 0)
            except (TypeError, ValueError):
                amount = 0.0

            key = (patient, physician_id)
            sums[key][category] += amount
            counts[key][category] += 1
            physician_names[physician_id] = row.get('physician_name') or ''

        condensed = []
        for (patient, physician_id), by_category in sums.items():
            for category, total_amount in by_category.items():
                condensed.append({
                    'patient_name': patient,
                    'physician_id': physician_id,
                    'physician_name': physician_names.get(physician_id, ''),
                    'category': category,
                    'total_amount': round(total_amount, 2),
                    'record_count': counts[(patient, physician_id)][category],
                })

        self.condensed = condensed
        self._save(condensed)
        return condensed

    # ── Persistence ──────────────────────────────────────────────────────

    def _save(self, rows: list[dict]) -> int:
        """Clear and rewrite commission_per_physicians with the latest rollup."""
        self.conn.execute("DELETE FROM commission_per_physicians")
        inserted = 0
        for r in rows:
            try:
                self.conn.execute("""
                    INSERT INTO commission_per_physicians
                        (physician_id, patient_name, category, total_amount, record_count)
                    VALUES (?, ?, ?, ?, ?)
                """, (
                    r['physician_id'],
                    r['patient_name'],
                    r['category'],
                    r['total_amount'],
                    r['record_count'],
                ))
                inserted += 1
            except Exception:
                continue  # Skip constraint errors
        self.conn.commit()
        return inserted


# ── Main category-merge function ─────────────────────────────────────────────

def run_category_merge(progress_cb: Callable[[str, int, str], None]) -> dict:
    """
    Run the full category-merge pipeline stage.

    Args:
        progress_cb: Callback(step, percent, message).

    Returns:
        Summary dict with counts.
    """
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON")

    progress_cb('load', 5, "── Loading Matched Records ──")
    condensor = Condensor(conn)
    data = condensor.load_data()
    progress_cb('load', 20, f"Loaded {len(data)} matched records")

    progress_cb('condense', 25, "── Grouping by Patient + Physician ──")
    condensed = condensor.list_condensor(progress_cb=progress_cb)

    physician_count = len({r['physician_id'] for r in condensed}) if condensed else 0
    conn.close()
    progress_cb(
        'done', 100,
        f"── Category Merge Complete: {len(condensed)} rollup rows "
        f"across {physician_count} physicians ──"
    )

    return {
        'source_records': len(data),
        'rollup_rows': len(condensed),
        'physicians': physician_count,
    }


if __name__ == "__main__":
    def _cli_progress(step: str, pct: int, msg: str) -> None:
        print(f"[{pct:3d}%] {step:>10} | {msg}")

    run_category_merge(_cli_progress)