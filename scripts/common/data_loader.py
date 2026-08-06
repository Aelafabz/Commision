"""Load Abronal and SoT Excel exports into normalized row records."""

from __future__ import annotations

import os

import pandas as pd

from .matching import normalize_string, parse_abronal_date


def load_sot(sot_dir: str, log_fn=print) -> tuple[list[dict], list[dict]]:
    """Load all named and nameless SoT rows from *.xlsx files in *sot_dir*."""
    all_sot: list[dict] = []
    nameless_sot: list[dict] = []
    named_counter = 1
    nameless_counter = 1

    for filename in os.listdir(sot_dir):
        if not filename.endswith(".xlsx"):
            continue
        log_fn(f"Loading SoT: {filename}")
        path = os.path.join(sot_dir, filename)
        df = pd.read_excel(path, header=None)
        h_idx = None
        for i in range(min(50, len(df))):
            row_str = [str(x).lower() for x in df.iloc[i]]
            if "customer" in row_str and ("mrc" in row_str or "reference" in row_str):
                h_idx = i
                break
        headers = (
            df.iloc[h_idx].tolist()
            if h_idx is not None
            else [f"Col_{j}" for j in range(len(df.columns))]
        )
        start_row = h_idx + 1 if h_idx is not None else 0
        for i in range(start_row, len(df)):
            row = df.iloc[i]
            try:
                name_raw = row[0]
                name_str = str(name_raw).strip()
                amt = float(row[7])
                service = str(row[2]) if pd.notna(row[2]) else "N/A"
                date_val = pd.to_datetime(row[11], errors="coerce")
                if amt > 0 and amt < 1_000_000:
                    row_raw = {str(headers[j]): row[j] for j in range(len(row))}
                    if pd.isna(name_raw) or name_str.lower() in ("", "nan", "none", "row labels"):
                        row_id = f"SOT-NAMELESS-{nameless_counter:06d}"
                        nameless_counter += 1
                        nameless_sot.append(
                            {
                                "Row_ID": row_id,
                                "Amt": amt,
                                "Date": date_val,
                                "Service": service,
                                "Source": filename.replace(".xlsx", ""),
                                "Raw": row_raw,
                            }
                        )
                    else:
                        row_id = f"SOT-{named_counter:06d}"
                        named_counter += 1
                        all_sot.append(
                            {
                                "Row_ID": row_id,
                                "Norm_Name": normalize_string(name_str),
                                "Original_Name": name_str,
                                "Norm_Service": normalize_string(service),
                                "Original_Service": service,
                                "Amount": amt,
                                "Date": date_val,
                                "Source": filename.replace(".xlsx", ""),
                                "Raw": row_raw,
                            }
                        )
            except Exception:
                continue
    return all_sot, nameless_sot


def load_abr(abr_dir: str, log_fn=print) -> list[dict]:
    """Load Abronal physician-performance rows from *.xlsx files in *abr_dir*."""
    all_abr: list[dict] = []
    row_counter = 1

    for filename in os.listdir(abr_dir):
        if not filename.endswith(".xlsx"):
            continue
        log_fn(f"Loading Abronal: {filename}")
        path = os.path.join(abr_dir, filename)
        df = pd.read_excel(path, header=None)
        h_idx = None
        for i in range(min(20, len(df))):
            if "customer" in str(df.iloc[i]).lower() or "patient" in str(df.iloc[i]).lower():
                h_idx = i
                break
        headers = (
            df.iloc[h_idx].tolist()
            if h_idx is not None
            else [f"Col_{i}" for i in range(len(df.columns))]
        )
        start_row = h_idx + 1 if h_idx is not None else 0
        for i in range(start_row, len(df)):
            row = df.iloc[i]
            try:
                name = str(row[3])
                amt = float(row[6])
                service = str(row[5]) if pd.notna(row[5]) else "N/A"
                date_str = str(row[10])
                date_val = parse_abronal_date(date_str)
                if amt > 0 and len(name) > 3 and name.lower() not in ("nan", "customer", "row labels"):
                    row_dict = {str(headers[j]): row[j] for j in range(len(row))}
                    row_dict["Source_File"] = filename
                    row_id = f"ABR-{row_counter:06d}"
                    row_counter += 1
                    all_abr.append(
                        {
                            "Row_ID": row_id,
                            "Norm_Name": normalize_string(name),
                            "Original_Name": name,
                            "Norm_Service": normalize_string(service),
                            "Original_Service": service,
                            "Amount": amt,
                            "Date": date_val,
                            "Original_Timestamp": date_str,
                            "File": filename,
                            "Raw": row_dict,
                        }
                    )
            except Exception:
                continue
    return all_abr
