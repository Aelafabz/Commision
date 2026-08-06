"""Shared I/O helpers for pipeline modules."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

import pandas as pd


def infer_date_label(*paths: str | None) -> str:
    """Infer 'July 20 to July 22' from folder names."""
    for path in paths:
        if not path:
            continue
        name = os.path.basename(os.path.normpath(path))
        for suffix in (" abronal", " sot", " analysis"):
            if name.lower().endswith(suffix):
                return name[: -len(suffix)].strip()
        parent = os.path.basename(os.path.dirname(os.path.normpath(path)))
        if parent and parent not in (".", "", "Desktop") and " to " in parent:
            return parent
    return ""


def perfect_matches_filename(date_label: str | None = None) -> str:
    label = (date_label or "").strip()
    if label:
        return f"{label} Perfect Matches.xlsx"
    return "Perfect Matches.xlsx"


def match_to_row(pair: dict, match_type: str = "Perfect Match") -> dict:
    """Flatten a matched abr/sot pair into a report row."""
    abr = pair["abr"]
    sot = pair["sot"]
    return {
        "Match Type": match_type,
        "Abronal Row ID": abr["Row_ID"],
        "SoT Row ID": sot["Row_ID"],
        "Patient Name": abr["Original_Name"],
        "Service": abr["Original_Service"],
        "Amount": abr["Amount"],
        "Abronal Date": abr.get("Original_Timestamp", abr.get("Date")),
        "SoT Date": sot["Date"],
        "Day Difference": pair.get("day_diff", ""),
        "Abronal File": abr.get("File", ""),
        "SoT Source": sot.get("Source", ""),
        "Name Confidence (%)": pair.get("name_confidence", ""),
    }


def write_matched_workbook(matched_rows: list[dict], output_path: str, group_by_file: bool = True) -> None:
    """Write matched records to Excel, optionally one sheet per Abronal file."""
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    if not matched_rows:
        pd.DataFrame(columns=[
            "Match Type", "Abronal Row ID", "SoT Row ID", "Patient Name",
            "Service", "Amount", "Abronal Date", "SoT Date",
        ]).to_excel(output_path, index=False)
        return

    df = pd.DataFrame(matched_rows)
    if not group_by_file or "Abronal File" not in df.columns:
        df.to_excel(output_path, index=False)
        return

    with pd.ExcelWriter(output_path, engine="openpyxl") as writer:
        used_sheet_names: set[str] = set()
        for filename in sorted(df["Abronal File"].dropna().unique()):
            subset = df[df["Abronal File"] == filename]
            base = os.path.splitext(str(filename))[0]
            if " Dr. " in base:
                base = "Dr. " + base.split(" Dr. ", 1)[1]
            base = re.sub(r'[\\/*?:\[\]]', "-", base).strip() or "Sheet"
            sheet = base[:31]
            n = 2
            while sheet in used_sheet_names:
                suffix = f"_{n}"
                sheet = base[: 31 - len(suffix)] + suffix
                n += 1
            used_sheet_names.add(sheet)
            subset.to_excel(writer, sheet_name=sheet, index=False)


def save_intermediate_json(data: dict, path: str | Path) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, default=str)


def load_intermediate_json(path: str | Path) -> dict:
    with Path(path).open(encoding="utf-8") as f:
        return json.load(f)
