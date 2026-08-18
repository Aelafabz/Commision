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


def persist_tables_to_db(tables: dict[str, pd.DataFrame], db_path: str | Path, log_fn=print, on_conflict: str = "abort") -> None:
    """Mirror every named DataFrame into its own SQLite table, appending rows.

    Special handling for a `records` table (or DataFrames with `doctor_name` and `date` columns):
    - `on_conflict` can be `abort` (default), `overwrite` (delete overlapping existing rows), or `ignore` (skip duplicates).
    """
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        for name, df in tables.items():
            # only persist pandas DataFrame objects
            if not isinstance(df, pd.DataFrame):
                continue
            if df is None or df.empty:
                continue
            table = _sanitize_table_name(name)

            # If this looks like the raw records table, handle duplicates carefully
            cols = set(df.columns.str.lower())
            is_records_like = ('doctor_name' in cols and 'date' in cols)

            if is_records_like or table == 'records':
                # ensure records schema exists
                try:
                    cur.execute(
                        """
                        CREATE TABLE IF NOT EXISTS records (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            doctor_name TEXT NOT NULL,
                            service TEXT NOT NULL,
                            amount REAL NOT NULL,
                            category TEXT NOT NULL,
                            date TEXT NOT NULL
                        )
                        """
                    )
                    cur.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_records_unique ON records(doctor_name, service, amount, category, date)")
                    conn.commit()
                except Exception:
                    pass
                # normalize df columns to expected names
                df2 = df.copy()
                # ensure required columns exist
                for expected in ('doctor_name', 'service', 'amount', 'category', 'date'):
                    if expected not in df2.columns:
                        df2[expected] = None

                # convert dates to ISO strings
                try:
                    df2['date'] = pd.to_datetime(df2['date'], errors='coerce').astype(str)
                except Exception:
                    df2['date'] = df2['date'].astype(str)

                # detect overlaps per doctor by min/max date
                overlaps = []
                for doctor in df2['doctor_name'].dropna().unique():
                    sub = df2[df2['doctor_name'] == doctor]
                    if sub.empty:
                        continue
                    try:
                        min_date = sub['date'].min()
                        max_date = sub['date'].max()
                    except Exception:
                        continue
                    q = "SELECT COUNT(*) as c, MIN(date) as min_date, MAX(date) as max_date FROM records WHERE doctor_name = ? AND DATE(date) BETWEEN DATE(?) AND DATE(?)"
                    cur.execute(q, (doctor, min_date, max_date))
                    row = cur.fetchone()
                    if row and row['c'] and int(row['c']) > 0:
                        overlaps.append({
                            'doctor': doctor,
                            'existing_count': int(row['c']),
                            'existing_min_date': row['min_date'],
                            'existing_max_date': row['max_date'],
                            'incoming_min_date': min_date,
                            'incoming_max_date': max_date,
                        })

                if overlaps:
                    if on_conflict == 'abort':
                        raise RuntimeError({'type': 'overlap', 'table': table, 'overlaps': overlaps})
                    elif on_conflict == 'overwrite':
                        # delete overlapping rows per doctor/date-range
                        for o in overlaps:
                            cur.execute("DELETE FROM records WHERE doctor_name = ? AND DATE(date) BETWEEN DATE(?) AND DATE(?)",
                                        (o['doctor'], o['incoming_min_date'], o['incoming_max_date']))
                        conn.commit()
                    elif on_conflict == 'ignore':
                        # we will skip inserting rows that match existing identical rows
                        pass

                # insert rows one by one, optionally skipping exact duplicates
                inserted = 0
                for _, r in df2.iterrows():
                    doctor = r.get('doctor_name')
                    service = r.get('service')
                    amount = r.get('amount')
                    category = r.get('category')
                    date_val = r.get('date')
                    if on_conflict == 'ignore':
                        cur.execute("SELECT COUNT(*) FROM records WHERE doctor_name = ? AND service = ? AND amount = ? AND category = ? AND DATE(date)=DATE(?)",
                                    (doctor, service, amount, category, date_val))
                        if cur.fetchone()[0] > 0:
                            continue
                    cur.execute("INSERT INTO records (doctor_name, service, amount, category, date) VALUES (?,?,?,?,?)",
                                (doctor, service, amount, category, date_val))
                    inserted += 1
                conn.commit()
                log_fn(f"  Inserted {inserted} row(s) into records table in {db_path}")
                continue

            # default behavior for other tables
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
    dry_run: bool = False,
    on_conflict: str = "abort",
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
    # Build raw `records` DataFrame (doctor_name, service, amount, category, date)
    records_rows = []
    for item in fully_matched:
        a, s = item['abr'], item['sot']
        date_val = s.get('Date') if s.get('Date') is not None else a.get('Original_Timestamp')
        records_rows.append({
            'doctor_name': a.get('Original_Name', ''),
            'service': a.get('Original_Service', ''),
            'amount': float(a.get('Amount', 0)),
            'category': None,  # will be filled from condensor._data
            'date': date_val,
        })
    records_df = pd.DataFrame(records_rows)
    condensor = Condensor(dictionary_path=dictionary_path)
    condensor.load_data(perfect_df)
    summary_df = condensor.list_condensor(date_label=date_label, commission_rate=commission_rate)

    mismatch_df = _mismatch_frame(primary.mismatched)

    tables = {
        "perfect_matches": perfect_df,
        "unmatched": mismatch_df,
        "commission_summary": summary_df,
    }

    # Doctor-centric summaries
    try:
        if not perfect_df.empty:
            # totals per doctor (using 'Patient Name' as doctor identifier)
            doc_totals = (
                perfect_df.groupby('Patient Name', as_index=False)['Amount']
                .sum()
                .rename(columns={'Patient Name': 'doctor_name', 'Amount': 'total'})
            )
            doc_counts = (
                perfect_df.groupby('Patient Name').size().reset_index(name='count').rename(columns={'Patient Name': 'doctor_name'})
            )
            doctor_df = doc_totals.merge(doc_counts, on='doctor_name')

            # load per-doctor commission rates from configs/commisions.json
            try:
                import json
                repo_root = Path(__file__).resolve().parents[1]
                comm_path = repo_root / 'configs' / 'commisions.json'
                commissions = {}
                if comm_path.exists():
                    with comm_path.open('r', encoding='utf-8') as cf:
                        commissions = json.load(cf) or {}
            except Exception:
                commissions = {}

            def get_rate(name):
                try:
                    return float(commissions.get(name) or commissions.get(name.lower()) or commission_rate)
                except Exception:
                    return commission_rate

            doctor_df['commission_rate'] = doctor_df['doctor_name'].map(get_rate)
            doctor_df['commission_amount'] = doctor_df['total'] * doctor_df['commission_rate']

            tables['doctor_summary'] = doctor_df

            # breakdown per doctor by category (using condensor._data)
            if getattr(condensor, '_data', None) is not None and not condensor._data.empty:
                doc_cat = (
                    condensor._data.groupby(['Patient Name', 'Category'], as_index=False)['Amount']
                    .sum()
                    .rename(columns={'Patient Name': 'doctor_name', 'Amount': 'total'})
                )
                tables['doctor_by_category'] = doc_cat
    except Exception as exc:
        log_fn(f"WARNING: failed to build doctor summaries: {exc}")

    # Additional condensed summary: total amounts per Category (merged subcategories)
    try:
        # condensor._data has columns: Patient Name, Service, Amount, Category
        if condensor._data is not None and not condensor._data.empty:
            category_totals = (
                condensor._data.groupby("Category", as_index=False)["Amount"].sum().rename(columns={"Amount": "Total"})
            )
            category_totals["Commission %"] = f"{commission_rate * 100:.1f}%"
            category_totals["Commission Amount"] = category_totals["Total"] * commission_rate
            tables["commission_by_category"] = category_totals
    except Exception as exc:
        log_fn(f"WARNING: failed to build category summary: {exc}")

    # Create an 'analyzed' folder near the database (repo-root/database -> repo-root/analyzed)
    try:
        db_path_obj = Path(db_path)
        # default repo root guess: two levels up from database file (database/commission.db)
        repo_root = db_path_obj.resolve().parents[1]
    except Exception:
        repo_root = Path('.')

    # Use provided date_label to name the analyzed folder, fall back to timestamp
    label = (date_label or '').strip()
    if label:
        folder_name = _sanitize_table_name(label + 'analyzed')
    else:
        from datetime import datetime
        folder_name = datetime.utcnow().strftime('run-%Y%m%dT%H%M%SZ-analyzed')

    analyzed_dir = repo_root / 'analyzed' / folder_name
    analyzed_dir.mkdir(parents=True, exist_ok=True)

    # Write each table to its own Excel file inside the analyzed folder
    try:
        for name, df in list(tables.items()):
            if isinstance(df, pd.DataFrame) and not df.empty:
                out_path = analyzed_dir / f"{_sanitize_table_name(name)}.xlsx"
                df.to_excel(out_path, index=False)

        # write a small manifest with inputs
        manifest = analyzed_dir / 'manifest.txt'
        with manifest.open('w', encoding='utf-8') as mf:
            mf.write(f"abr_dir: {abr_dir}\n")
            mf.write(f"sot_dir: {sot_dir}\n")
            mf.write(f"db_path: {db_path}\n")
            mf.write(f"date_label: {date_label}\n")
    except Exception as exc:
        log_fn(f"WARNING: failed to write analyzed files: {exc}")

    # expose the analyzed folder path to callers
    tables['analyzed_dir'] = str(analyzed_dir)

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