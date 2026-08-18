from __future__ import annotations

import os
import re
from dataclasses import dataclass, field

import pandas as pd


# ── Parsing helpers ──────────────────────────────────────────────────────

def normalize_string(s) -> str:
    if not isinstance(s, str):
        return ""
    s = s.upper()
    s = re.sub(r"[^A-Z0-9\s]", "", s)
    return " ".join(s.split())


def parse_abronal_date(s):
    if not isinstance(s, str):
        return pd.NaT
    s_clean = (
        s.replace(":AM", " AM")
        .replace(":PM", " PM")
        .replace(":am", " AM")
        .replace(":pm", " PM")
    )
    return pd.to_datetime(s_clean, errors="coerce")


def date_distance_days(date1, date2) -> int:
    if pd.isna(date1) or pd.isna(date2):
        return 999_999
    return abs((date1.normalize() - date2.normalize()).days)


def signed_day_difference(date1, date2):
    if pd.isna(date1) or pd.isna(date2):
        return "N/A"
    return (date1.normalize() - date2.normalize()).days


# ── File loading ─────────────────────────────────────────────────────────

def load_sot(sot_dir: str, log_fn=print):
    """Read every .xlsx in sot_dir. Returns (named_rows, nameless_rows)."""
    named, nameless = [], []
    named_counter = nameless_counter = 1

    for filename in os.listdir(sot_dir):
        if not filename.endswith(".xlsx"):
            continue
        log_fn(f"Loading SoT: {filename}")
        df = pd.read_excel(os.path.join(sot_dir, filename), header=None)

        h_idx = None
        for i in range(min(50, len(df))):
            row_str = [str(x).lower() for x in df.iloc[i]]
            if "customer" in row_str and ("mrc" in row_str or "reference" in row_str):
                h_idx = i
                break
        headers = df.iloc[h_idx].tolist() if h_idx is not None else [f"Col_{j}" for j in range(len(df.columns))]
        start_row = h_idx + 1 if h_idx is not None else 0

        for i in range(start_row, len(df)):
            row = df.iloc[i]
            try:
                name_raw = row[0]
                name_str = str(name_raw).strip()
                amt = float(row[7])
                service = str(row[2]) if pd.notna(row[2]) else "N/A"
                date_val = pd.to_datetime(row[11], errors="coerce")
                if not (0 < amt < 1_000_000):
                    continue
                row_raw = {str(headers[j]): row[j] for j in range(len(row))}
                if pd.isna(name_raw) or name_str.lower() in ("", "nan", "none", "row labels"):
                    row_id = f"SOT-NAMELESS-{nameless_counter:06d}"
                    nameless_counter += 1
                    nameless.append({
                        "Row_ID": row_id, "Amt": amt, "Date": date_val, "Service": service,
                        "Source": filename.replace(".xlsx", ""), "Raw": row_raw,
                    })
                else:
                    row_id = f"SOT-{named_counter:06d}"
                    named_counter += 1
                    named.append({
                        "Row_ID": row_id, "Norm_Name": normalize_string(name_str), "Original_Name": name_str,
                        "Norm_Service": normalize_string(service), "Original_Service": service,
                        "Amount": amt, "Date": date_val, "Source": filename.replace(".xlsx", ""), "Raw": row_raw,
                    })
            except Exception:
                continue
    return named, nameless


def load_abr(abr_dir: str, log_fn=print):
    """Read every .xlsx in abr_dir (Abronal exports)."""
    rows = []
    row_counter = 1

    for filename in os.listdir(abr_dir):
        if not filename.endswith(".xlsx"):
            continue
        log_fn(f"Loading Abronal: {filename}")
        df = pd.read_excel(os.path.join(abr_dir, filename), header=None)

        h_idx = None
        for i in range(min(20, len(df))):
            cell = str(df.iloc[i]).lower()
            if "customer" in cell or "patient" in cell:
                h_idx = i
                break
        headers = df.iloc[h_idx].tolist() if h_idx is not None else [f"Col_{i}" for i in range(len(df.columns))]
        start_row = h_idx + 1 if h_idx is not None else 0

        for i in range(start_row, len(df)):
            row = df.iloc[i]
            try:
                name = str(row[3])
                amt = float(row[6])
                service = str(row[5]) if pd.notna(row[5]) else "N/A"
                date_str = str(row[10])
                date_val = parse_abronal_date(date_str)
                if amt <= 0 or len(name) <= 3 or name.lower() in ("nan", "customer", "row labels"):
                    continue
                row_dict = {str(headers[j]): row[j] for j in range(len(row))}
                row_dict["Source_File"] = filename
                row_id = f"ABR-{row_counter:06d}"
                row_counter += 1
                rows.append({
                    "Row_ID": row_id, "Norm_Name": normalize_string(name), "Original_Name": name,
                    "Norm_Service": normalize_string(service), "Original_Service": service,
                    "Amount": amt, "Date": date_val, "Original_Timestamp": date_str,
                    "File": filename, "Raw": row_dict,
                })
            except Exception:
                continue
    return rows


# ── Matching ─────────────────────────────────────────────────────────────

def best_date_pairs(abr_entries, sot_entries, same_service_required=True):
    """Pair duplicate (name, service, amount) candidates by closest date."""
    candidates = []
    for ai, a in enumerate(abr_entries):
        for si, s in enumerate(sot_entries):
            if same_service_required and a["Norm_Service"] != s["Norm_Service"]:
                continue
            if abs(a["Amount"] - s["Amount"]) >= 0.01:
                continue
            candidates.append((date_distance_days(a["Date"], s["Date"]), ai, si))

    candidates.sort()
    matched_abr, matched_sot, pairs = set(), set(), []
    for _, ai, si in candidates:
        if ai in matched_abr or si in matched_sot:
            continue
        matched_abr.add(ai)
        matched_sot.add(si)
        pairs.append((ai, si))
    return pairs


@dataclass
class PrimaryResult:
    matched: list = field(default_factory=list)          
    mismatched: list = field(default_factory=list)       
    remaining_abr_by_name: dict = field(default_factory=dict)  
    remaining_sot_by_name: dict = field(default_factory=dict)
    all_abr: list = field(default_factory=list)
    all_sot: list = field(default_factory=list)
    nameless_sot: list = field(default_factory=list)


def run_primary_reconciliation(abr_dir: str, sot_dir: str, log_fn=print) -> PrimaryResult:
    log_fn("-- Loading files --")
    all_sot, nameless_sot = load_sot(sot_dir, log_fn)
    all_abr = load_abr(abr_dir, log_fn)
    log_fn(f"Loaded {len(all_abr)} Abronal, {len(all_sot)} SoT, {len(nameless_sot)} nameless SoT rows.")

    abr_by_name, sot_by_name = {}, {}
    for e in all_abr:
        abr_by_name.setdefault(e["Norm_Name"], []).append(e)
    for e in all_sot:
        sot_by_name.setdefault(e["Norm_Name"], []).append(e)

    result = PrimaryResult(all_abr=all_abr, all_sot=all_sot, nameless_sot=nameless_sot)
    unique_names = set(abr_by_name) | set(sot_by_name)

    for name in unique_names:
        rem_a = abr_by_name.get(name, [])[:]
        rem_s = sot_by_name.get(name, [])[:]

        exact_pairs = best_date_pairs(rem_a, rem_s, same_service_required=True)
        for ai, si in exact_pairs:
            a, s = rem_a[ai], rem_s[si]
            result.matched.append({"abr": a, "sot": s, "day_diff": signed_day_difference(a["Date"], s["Date"])})

        matched_a = {ai for ai, _ in exact_pairs}
        matched_s = {si for _, si in exact_pairs}
        rem_a = [a for idx, a in enumerate(rem_a) if idx not in matched_a]
        rem_s = [s for idx, s in enumerate(rem_s) if idx not in matched_s]

       # same amount, different service -> "Service Mismatch"       i = 0
        while i < len(rem_a):
            a = rem_a[i]
            found = False
            for j, s in enumerate(rem_s):
                if abs(a["Amount"] - s["Amount"]) < 0.01:
                    result.mismatched.append({
                        "Status": "Service Mismatch", "Abronal Entry": a, "SoT Entry": s,
                        "Difference": 0,
                    })
                    rem_s.pop(j)
                    rem_a.pop(i)
                    found = True
                    break
            if not found:
                i += 1

        while rem_a and rem_s:
            a, s = rem_a.pop(0), rem_s.pop(0)
            result.mismatched.append({
                "Status": "Amount Mismatch", "Abronal Entry": a, "SoT Entry": s,
                "Difference": a["Amount"] - s["Amount"],
            })

        if rem_a:
            result.remaining_abr_by_name[name] = rem_a
        if rem_s:
            result.remaining_sot_by_name[name] = rem_s

    log_fn(f"Primary reconciliation: {len(result.matched)} matched, {len(result.mismatched)} mismatched.")
    return result