from __future__ import annotations

import re
import sqlite3
from pathlib import Path

import pandas as pd

from primary_recon import run_primary_reconciliation
from secondary_recon import load_mismatched_data, name_comparator, grafter
from category_merger import Condensor, DEFAULT_COMMISSION_RATE


def _perfect_matches_frame(matched: list) -> pd.DataFrame:
    rows = []
    for item in matched:
        a, s = item["abr"], item["sot"]
        rows.append({
            "Patient Name": a["Original_Name"],
            "Service": a["Original_Service"],
            "Amount": a["Amount"],
            "Abronal Date": a.get("Original_Timestamp", ""),
            "SoT Date": s.get("Date"),
            "Day Difference": item.get("day_diff"),
            "Spelling Match": item.get("spelling_match", False),
        })
    return pd.DataFrame(rows)


def _mismatch_frame(mismatched: list) -> pd.DataFrame:
    rows = []
    for m in mismatched:
        a, s = m["Abronal Entry"], m["SoT Entry"]
        rows.append({
            "Status": m["Status"],
            "Abronal Name": a["Original_Name"], "Abronal Service": a["Original_Service"],
            "Abronal Amount": a["Amount"], "Abronal Date": a.get("Original_Timestamp", ""),
            "SoT Name": s["Original_Name"], "SoT Service": s["Original_Service"],
            "SoT Amount": s["Amount"], "SoT Date": s.get("Date"),
            "Difference": m.get("Difference", ""),
        })
    return pd.DataFrame(rows)


def _sanitize_table_name(name: str) -> str:
    name = re.sub(r"[^A-Za-z0-9_]", "_", name.strip())
    return name or "table"


def persist_tables_to_db(tables: dict[str, pd.DataFrame], db_path: str | Path, log_fn=print) -> None:
    """Mirror every named DataFrame into its own SQLite table, appending rows."""
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as conn:
        for name, df in tables.items():
            if df is None or df.empty:
                continue
            table = _sanitize_table_name(name)
            df_to_write = df.copy()
            # sqlite can't store pandas Timestamp objects directly
            for col in df_to_write.columns:
                if pd.api.types.is_datetime64_any_dtype(df_to_write[col]):
                    df_to_write[col] = df_to_write[col].astype(str)
            df_to_write.to_sql(table, conn, if_exists="append", index=False)
            log_fn(f"  Appended {len(df_to_write)} row(s) to table '{table}' in {db_path}")


def run_pipeline(
    abr_dir: str,
    sot_dir: str,
    dictionary_path: str,
    db_path: str,
    date_label: str = "",
    commission_rate: float = DEFAULT_COMMISSION_RATE,
    name_match_confidence: float = 0.70,
    date_window_days: int = 1,
    log_fn=print,
) -> dict[str, pd.DataFrame]:
    """
    Runs the full pipeline and persists results. Returns the in-memory
    tables (perfect matches, mismatches, and the final commission summary)
    for a caller (e.g. a FastAPI route) that wants to return them directly
    without re-reading the DB.
    """
    # 1. primary reconciliation
    primary = run_primary_reconciliation(abr_dir, sot_dir, log_fn=log_fn)

    # 2. secondary name matching on whatever primary couldn't resolve by name
    log_fn("-- Secondary name matching --")
    remaining_abr, remaining_sot = load_mismatched_data(
        primary.remaining_abr_by_name, primary.remaining_sot_by_name
    )
    buffer, unreconciled_abr, unreconciled_sot = name_comparator(
        remaining_abr, remaining_sot,
        confidence=name_match_confidence,
        date_window_days=date_window_days,
    )
    log_fn(f"  Resolved {len(buffer)} additional name group(s) via fuzzy matching.")
    fully_matched = grafter(primary.matched, buffer)

    # 3. category merger -> final per-patient commission table
    log_fn("-- Category merger --")
    perfect_df = _perfect_matches_frame(fully_matched)
    condensor = Condensor(dictionary_path=dictionary_path)
    condensor.load_data(perfect_df)
    summary_df = condensor.list_condensor(date_label=date_label, commission_rate=commission_rate)

    mismatch_df = _mismatch_frame(primary.mismatched)

    tables = {
        "perfect_matches": perfect_df,
        "unmatched": mismatch_df,
        "commission_summary": summary_df,
    }

    # 4. persist -- one table per output, mirroring the old excel files
    log_fn("-- Persisting to database --")
    persist_tables_to_db(tables, db_path, log_fn=log_fn)

    log_fn("Pipeline complete.")
    return tables


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Run the reconciliation pipeline headlessly")
    parser.add_argument("--abr", required=True, help="Folder of Abronal excel exports")
    parser.add_argument("--sot", required=True, help="Folder of SoT excel files")
    parser.add_argument("--dictionary", required=True, help="Path to the service->category dictionary JSON")
    parser.add_argument("--db", required=True, help="Path to the sqlite database to append into")
    parser.add_argument("--date-label", default="")
    parser.add_argument("--commission-rate", type=float, default=DEFAULT_COMMISSION_RATE)
    args = parser.parse_args()

    run_pipeline(
        args.abr, args.sot, args.dictionary, args.db,
        date_label=args.date_label, commission_rate=args.commission_rate,
    )