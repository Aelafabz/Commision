"""
primary_reconciliation.py
Headless reconciliation pipeline for the FastAPI web app.

Philosophy:
- No tkinter / GUI dependencies
- Progress reported via a callback: progress_cb(step: str, pct: int, msg: str)
- Physician name extracted from the Abronal Excel filename
- Results saved directly to the SQLite database
"""
from __future__ import annotations

import json
import os
import re
import sqlite3
from pathlib import Path
from typing import Callable

import pandas as pd
from difflib import get_close_matches, SequenceMatcher

DB_PATH = Path(__file__).resolve().parent.parent.parent / "database" / "commissions.db"
DICT_PATH = Path(__file__).resolve().parent.parent.parent / "configs" / "dictionary.json"


# ── Utility functions ────────────────────────────────────────────────────────

def normalize_string(s: str) -> str:
    if not isinstance(s, str):
        return ""
    s = s.upper()
    s = re.sub(r'[^A-Z0-9\s]', '', s)
    return ' '.join(s.split())


def parse_abronal_date(s: str) -> pd.Timestamp:
    if not isinstance(s, str):
        return pd.NaT
    s = s.replace(':AM', ' AM').replace(':PM', ' PM').replace(':am', ' AM').replace(':pm', ' PM')
    return pd.to_datetime(s, errors='coerce')


def advanced_name_match(name1: str, name2: str) -> float:
    """Returns a similarity score 0.0-1.0 using char + word-subset matching."""
    char_sim = SequenceMatcher(None, name1, name2).ratio()
    w1 = name1.split()
    w2 = name2.split()
    if not w1 or not w2:
        return char_sim
    shorter, longer = (w1, w2) if len(w1) < len(w2) else (w2, w1)
    if len(shorter) < 2:
        return char_sim
    matched = sum(
        1 for sw in shorter
        if get_close_matches(sw, longer, n=1, cutoff=0.85)
    )
    ratio = matched / len(shorter)
    if ratio == 1.0:
        return max(char_sim, 0.95)
    if ratio >= 0.66 and len(shorter) >= 3:
        return max(char_sim, 0.85)
    return char_sim


def date_distance_days(d1, d2) -> int:
    if pd.isna(d1) or pd.isna(d2):
        return 999999
    return abs((d1.normalize() - d2.normalize()).days)


def signed_day_diff(d1, d2):
    if pd.isna(d1) or pd.isna(d2):
        return "N/A"
    return (d1.normalize() - d2.normalize()).days


def extract_physician_name(filename: str) -> str:
    """
    Extract physician name from Abronal export filename.
    Expected format: 'July 20 to July 22 Dr. Ahmed Reja.xlsx'
    Returns: 'Dr. Ahmed Reja'
    """
    stem = Path(filename).stem  # remove .xlsx
    # Try to find 'Dr.' prefix
    match = re.search(r'(Dr\.?\s+.+)$', stem, re.IGNORECASE)
    if match:
        name = match.group(1).strip()
        # Normalize "Dr " -> "Dr. "
        name = re.sub(r'^Dr\.?\s+', 'Dr. ', name, flags=re.IGNORECASE)
        return name
    # Fallback: use the whole stem
    return stem


def load_category_map() -> dict[str, str]:
    """Load service → category mapping from dictionary.json."""
    if DICT_PATH.exists():
        with open(DICT_PATH, encoding='utf-8') as f:
            return json.load(f)
    return {}


# ── DB helpers ───────────────────────────────────────────────────────────────

def get_or_create_physician(conn: sqlite3.Connection, name: str) -> int:
    """Return physician id, inserting if not present."""
    cur = conn.execute("SELECT id FROM physicians WHERE name = ?", (name,))
    row = cur.fetchone()
    if row:
        return row[0]
    cur = conn.execute("INSERT INTO physicians (name) VALUES (?)", (name,))
    conn.commit()
    return cur.lastrowid


def save_matched_records(
    conn: sqlite3.Connection,
    matched: list[dict],
    category_map: dict[str, str],
) -> int:
    """Insert matched records into matched_records table."""
    inserted = 0
    for m in matched:
        abr = m['abr']
        sot = m['sot']
        physician_id = m.get('physician_id')
        service = abr.get('Original_Service', '')
        category = category_map.get(service, 'Other')
        try:
            conn.execute("""
                INSERT INTO matched_records
                    (patient_name, service_type, category, total_amount, net_amount,
                     payment_date, physician_id, match_type)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                abr.get('Original_Name', ''),
                service,
                category,
                abr.get('Amount', 0),
                abr.get('Amount', 0),
                str(sot.get('Date', '')),
                physician_id,
                m.get('match_type', 'perfect'),
            ))
            inserted += 1
        except Exception as e:
            pass  # Skip duplicates / constraint errors
    conn.commit()
    return inserted


def save_unmatched_records(
    conn: sqlite3.Connection,
    unmatched: list[dict],
) -> int:
    """Insert unmatched/mismatch records into unmatched_records table."""
    inserted = 0
    for m in unmatched:
        abr = m.get('Abronal Entry') or {}
        sot = m.get('SoT Entry') or {}
        physician_id = m.get('physician_id')
        try:
            conn.execute("""
                INSERT INTO unmatched_records
                    (abronal_patient_name, abronal_service_type, abronal_net_amount,
                     abronal_payment_date, physician_id, sot_patient_name,
                     sot_service_type, sot_amount, sot_payment_date, reason_for_mismatch)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                abr.get('Original_Name', m.get('Abronal Name', '')),
                abr.get('Original_Service', m.get('Abronal Service', '')),
                abr.get('Amount', m.get('Abronal Amount', 0)),
                str(abr.get('Original_Timestamp', m.get('Abronal Payment Date', ''))),
                physician_id,
                sot.get('Original_Name', m.get('SoT Name', '')),
                sot.get('Original_Service', m.get('SoT Service', '')),
                sot.get('Amount', m.get('SoT Amount', 0)),
                str(sot.get('Date', m.get('SoT Payment Date', ''))),
                m.get('Status', 'Mismatch'),
            ))
            inserted += 1
        except Exception as e:
            pass
    conn.commit()
    return inserted


# ── Loading functions ────────────────────────────────────────────────────────

def load_sot(sot_dir: str | Path, progress_cb: Callable) -> tuple[list, list]:
    """Load SOT Excel files from directory. Returns (named_rows, nameless_rows)."""
    sot_dir = Path(sot_dir)
    all_sot, nameless_sot = [], []
    named_counter = 1
    nameless_counter = 1

    for filename in os.listdir(sot_dir):
        if not filename.endswith(".xlsx"):
            continue
        progress_cb('load', 10, f"Loading SOT: {filename}")
        path = sot_dir / filename
        df = pd.read_excel(path, header=None)

        # Find header row
        h_idx = None
        for i in range(min(50, len(df))):
            row_str = [str(x).lower() for x in df.iloc[i]]
            if 'customer' in row_str and ('mrc' in row_str or 'reference' in row_str):
                h_idx = i
                break
        headers = (
            df.iloc[h_idx].tolist() if h_idx is not None
            else [f"Col_{j}" for j in range(len(df.columns))]
        )
        start_row = (h_idx + 1) if h_idx is not None else 0

        for i in range(start_row, len(df)):
            row = df.iloc[i]
            try:
                name_raw = row[0]
                name_str = str(name_raw).strip()
                amt = float(row[7])
                service = str(row[2]) if pd.notna(row[2]) else "N/A"
                date_val = pd.to_datetime(row[11], errors='coerce')
                if amt > 0 and amt < 1_000_000:
                    row_raw = {str(headers[j]): row[j] for j in range(len(row))}
                    if pd.isna(name_raw) or name_str.lower() in ('', 'nan', 'none', 'row labels'):
                        nameless_sot.append({
                            'Row_ID': f"SOT-NAMELESS-{nameless_counter:06d}",
                            'Amt': amt, 'Date': date_val, 'Service': service,
                            'Source': filename.replace('.xlsx', ''), 'Raw': row_raw,
                        })
                        nameless_counter += 1
                    else:
                        all_sot.append({
                            'Row_ID': f"SOT-{named_counter:06d}",
                            'Norm_Name': normalize_string(name_str),
                            'Original_Name': name_str,
                            'Norm_Service': normalize_string(service),
                            'Original_Service': service,
                            'Amount': amt, 'Date': date_val,
                            'Source': filename.replace('.xlsx', ''), 'Raw': row_raw,
                        })
                        named_counter += 1
            except Exception:
                continue

    return all_sot, nameless_sot


def load_abronal(
    abr_dir: str | Path,
    progress_cb: Callable,
    conn: sqlite3.Connection,
) -> list:
    """Load Abronal Excel files. Physician name taken from filename."""
    abr_dir = Path(abr_dir)
    all_abr = []
    row_counter = 1

    for filename in os.listdir(abr_dir):
        if not filename.endswith(".xlsx"):
            continue
        physician_name = extract_physician_name(filename)
        physician_id = get_or_create_physician(conn, physician_name)
        progress_cb('load', 15, f"Loading Abronal: {filename} → {physician_name}")

        path = abr_dir / filename
        df = pd.read_excel(path, header=None)

        h_idx = None
        for i in range(min(20, len(df))):
            if 'customer' in str(df.iloc[i]).lower() or 'patient' in str(df.iloc[i]).lower():
                h_idx = i
                break
        headers = (
            df.iloc[h_idx].tolist() if h_idx is not None
            else [f"Col_{i}" for i in range(len(df.columns))]
        )
        start_row = (h_idx + 1) if h_idx is not None else 0

        for i in range(start_row, len(df)):
            row = df.iloc[i]
            try:
                name = str(row[3])
                amt = float(row[6])
                service = str(row[5]) if pd.notna(row[5]) else "N/A"
                date_str = str(row[10])
                date_val = parse_abronal_date(date_str)
                if amt > 0 and len(name) > 3 and name.lower() not in ('nan', 'customer', 'row labels'):
                    row_dict = {str(headers[j]): row[j] for j in range(len(row))}
                    row_dict['Source_File'] = filename
                    all_abr.append({
                        'Row_ID': f"ABR-{row_counter:06d}",
                        'Norm_Name': normalize_string(name),
                        'Original_Name': name,
                        'Norm_Service': normalize_string(service),
                        'Original_Service': service,
                        'Amount': amt, 'Date': date_val,
                        'Original_Timestamp': date_str,
                        'File': filename,
                        'physician_id': physician_id,
                        'physician_name': physician_name,
                        'Raw': row_dict,
                    })
                    row_counter += 1
            except Exception:
                continue

    return all_abr


def best_date_pairs(abr_entries: list, sot_entries: list, same_service: bool = True) -> list:
    """Pair duplicate candidates by closest dates."""
    candidates = []
    for ai, a in enumerate(abr_entries):
        for si, s in enumerate(sot_entries):
            if same_service and a['Norm_Service'] != s['Norm_Service']:
                continue
            if abs(a['Amount'] - s['Amount']) >= 0.01:
                continue
            candidates.append((date_distance_days(a['Date'], s['Date']), ai, si))
    candidates.sort()
    matched_a, matched_s, pairs = set(), set(), []
    for _, ai, si in candidates:
        if ai in matched_a or si in matched_s:
            continue
        matched_a.add(ai)
        matched_s.add(si)
        pairs.append((ai, si))
    return pairs


# ── Main reconciliation function ─────────────────────────────────────────────

def run_reconciliation(
    abr_dir: str | Path,
    sot_dir: str | Path,
    progress_cb: Callable[[str, int, str], None],
    clear_existing: bool = True,
) -> dict:
    """
    Run the full primary reconciliation pipeline.

    Args:
        abr_dir: Folder containing Abronal Excel files.
        sot_dir: Folder containing SOT Excel files.
        progress_cb: Callback(step, percent, message).
        clear_existing: If True, clears existing matched/unmatched records before run.

    Returns:
        Summary dict with counts.
    """
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON")

    if clear_existing:
        conn.execute("DELETE FROM matched_records")
        conn.execute("DELETE FROM unmatched_records")
        conn.commit()

    category_map = load_category_map()
    progress_cb('load', 5, "── Loading Files ──")

    all_sot, nameless_sot = load_sot(sot_dir, progress_cb)
    all_abr = load_abronal(abr_dir, progress_cb, conn)
    progress_cb('load', 20, f"Loaded {len(all_abr)} Abronal rows, {len(all_sot)} SOT rows")

    # Group by normalized name
    abr_by_name: dict[str, list] = {}
    sot_by_name: dict[str, list] = {}
    for e in all_abr:
        abr_by_name.setdefault(e['Norm_Name'], []).append(e)
    for e in all_sot:
        sot_by_name.setdefault(e['Norm_Name'], []).append(e)

    progress_cb('reconcile', 25, "── Phase 1-3: Exact Name Matching ──")
    perfect, mismatch = [], []
    remaining_abr: dict[str, list] = {}
    remaining_sot: dict[str, list] = {}

    for name in set(list(abr_by_name.keys()) + list(sot_by_name.keys())):
        a_list = abr_by_name.get(name, [])
        s_list = sot_by_name.get(name, [])
        rem_a = a_list[:]
        rem_s = s_list[:]

        exact_pairs = best_date_pairs(rem_a, rem_s, same_service=True)
        for ai, si in exact_pairs:
            phys_id = rem_a[ai].get('physician_id')
            perfect.append({
                'abr': rem_a[ai], 'sot': rem_s[si],
                'physician_id': phys_id,
                'day_diff': signed_day_diff(rem_a[ai]['Date'], rem_s[si]['Date']),
                'match_type': 'perfect',
            })
        matched_a = {ai for ai, _ in exact_pairs}
        matched_s = {si for _, si in exact_pairs}
        rem_a = [a for i, a in enumerate(rem_a) if i not in matched_a]
        rem_s = [s for i, s in enumerate(rem_s) if i not in matched_s]

        # Service mismatch pass
        i = 0
        while i < len(rem_a):
            a = rem_a[i]
            found = False
            for j, s in enumerate(rem_s):
                if abs(a['Amount'] - s['Amount']) < 0.01:
                    mismatch.append({
                        'Status': 'Service Mismatch',
                        'Abronal Entry': a, 'SoT Entry': s,
                        'physician_id': a.get('physician_id'),
                    })
                    rem_s.pop(j)
                    rem_a.pop(i)
                    found = True
                    break
            if not found:
                i += 1

        while rem_a and rem_s:
            a = rem_a.pop(0)
            s = rem_s.pop(0)
            mismatch.append({
                'Status': 'Amount Mismatch',
                'Abronal Entry': a, 'SoT Entry': s,
                'physician_id': a.get('physician_id'),
            })

        if rem_a:
            remaining_abr[name] = rem_a
        if rem_s:
            remaining_sot[name] = rem_s

    progress_cb('reconcile', 55, f"  Perfect: {len(perfect)}, Mismatches: {len(mismatch)}")

    # Phase 4: Fuzzy name matching
    progress_cb('reconcile', 60, "── Phase 4: Fuzzy Name-Level Linkage ──")
    abr_names_left = list(remaining_abr.keys())
    sot_names_by_letter: dict[str, list] = {}
    for sn in remaining_sot:
        letter = sn[0] if sn else ''
        sot_names_by_letter.setdefault(letter, []).append(sn)

    fuzzy_pairs = []
    consumed_sot = set()
    for an in abr_names_left:
        letter = an[0] if an else ''
        candidates = [c for c in sot_names_by_letter.get(letter, []) if c not in consumed_sot]
        best_score, best_match = 0, None
        for cand in candidates:
            score = advanced_name_match(an, cand)
            if score > best_score:
                best_score, best_match = score, cand
        if best_score >= 0.8 and best_match:
            fuzzy_pairs.append((an, best_match, best_score))
            consumed_sot.add(best_match)

    progress_cb('reconcile', 75, f"  Found {len(fuzzy_pairs)} fuzzy name pairs")

    consumed_abr_names = set()
    consumed_sot_names = set()
    for abr_norm, sot_norm, sim in fuzzy_pairs:
        abr_entries = remaining_abr.get(abr_norm, [])
        sot_entries = remaining_sot.get(sot_norm, [])
        # Treat fuzzy-matched pairs as possible matches — add to mismatch with spelling status
        for ae in abr_entries:
            for se in sot_entries:
                if abs(ae['Amount'] - se['Amount']) < 0.01:
                    perfect.append({
                        'abr': ae, 'sot': se,
                        'physician_id': ae.get('physician_id'),
                        'day_diff': signed_day_diff(ae['Date'], se['Date']),
                        'match_type': 'fuzzy',
                    })
        consumed_abr_names.add(abr_norm)
        consumed_sot_names.add(sot_norm)

    progress_cb('reconcile', 85, "── Saving Results to DB ──")
    matched_count = save_matched_records(conn, perfect, category_map)
    unmatched_count = save_unmatched_records(conn, mismatch)

    conn.close()
    progress_cb('done', 100, f"── Reconciliation Complete: {matched_count} matched, {unmatched_count} unmatched ──")

    return {
        'matched': matched_count,
        'unmatched': unmatched_count,
        'total_abr': len(all_abr),
        'total_sot': len(all_sot),
        'fuzzy_pairs': len(fuzzy_pairs),
    }
