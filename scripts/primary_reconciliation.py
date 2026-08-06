"""
Primary reconciliation: compare Abronal exports against SoT files and split
results into matched and mismatched datasets.

This module extracts the core matching logic from reconciliation_app_v5.py into
a headless, pipeline-friendly form. The GUI app remains available for manual
review and service-category confirmation.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import pandas as pd

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))
PROJECT_ROOT = SCRIPT_DIR.parent

from common.data_loader import load_abr, load_sot
from common.io_utils import (
    infer_date_label,
    match_to_row,
    perfect_matches_filename,
    save_intermediate_json,
    write_matched_workbook,
)
from common.matching import (
    advanced_name_match,
    best_date_pairs,
    date_distance_days,
    signed_day_difference,
)


def raw_with_row_id(entry: dict) -> dict:
    row = {"Row ID": entry.get("Row_ID", "")}
    row.update(entry.get("Raw", {}))
    return row


def run_primary_reconciliation(
    abr_dir: str,
    sot_dir: str,
    output_dir: str,
    *,
    log_fn=print,
    date_label: str | None = None,
    fuzzy_threshold: float = 0.80,
) -> dict:
    """
    Run phases 1–5 of reconciliation and write matched / mismatched outputs.

    Returns a result dict with counts and output paths for downstream modules.
    """
    date_label = (date_label or "").strip() or infer_date_label(output_dir, abr_dir, sot_dir)

    # If the user supplied paths don't exist, try the workspace-local
    # `raw files/<date label>/<date label> abronal|sot` layout.
    try:
        raw_root = PROJECT_ROOT / "raw files"
    except Exception:
        raw_root = Path("raw files")

    if not Path(abr_dir).exists() and date_label:
        candidate = raw_root / date_label / f"{date_label} abronal"
        if candidate.exists():
            log_fn(f"Using inferred Abronal folder: {candidate}")
            abr_dir = str(candidate)

    if not Path(sot_dir).exists() and date_label:
        candidate = raw_root / date_label / f"{date_label} sot"
        if candidate.exists():
            log_fn(f"Using inferred SoT folder: {candidate}")
            sot_dir = str(candidate)

    os.makedirs(output_dir, exist_ok=True)

    log_fn("── Loading Files ──")
    all_sot, nameless_sot_pool = load_sot(sot_dir, log_fn)
    all_abr = load_abr(abr_dir, log_fn)
    log_fn(f"Loaded {len(all_abr)} Abronal, {len(all_sot)} SoT, {len(nameless_sot_pool)} nameless SoT.")

    abr_by_name: dict[str, list] = {}
    sot_by_name: dict[str, list] = {}
    for e in all_abr:
        abr_by_name.setdefault(e["Norm_Name"], []).append(e)
    for e in all_sot:
        sot_by_name.setdefault(e["Norm_Name"], []).append(e)

    perfect: list[dict] = []
    mismatch: list[dict] = []
    remaining_abr_by_name: dict[str, list] = {}
    remaining_sot_by_name: dict[str, list] = {}

    log_fn("── Phases 1-3: Exact Name Matching ──")
    unique_names = set(abr_by_name.keys()) | set(sot_by_name.keys())
    for name in unique_names:
        a_list = abr_by_name.get(name, [])
        s_list = sot_by_name.get(name, [])
        rem_a = a_list[:]
        rem_s = s_list[:]

        exact_pairs = best_date_pairs(rem_a, rem_s, same_service_required=True)
        for ai, si in exact_pairs:
            a, s = rem_a[ai], rem_s[si]
            perfect.append({
                "abr": a,
                "sot": s,
                "day_diff": signed_day_difference(a["Date"], s["Date"]),
            })

        matched_a = {ai for ai, _ in exact_pairs}
        matched_s = {si for _, si in exact_pairs}
        rem_a = [a for idx, a in enumerate(rem_a) if idx not in matched_a]
        rem_s = [s for idx, s in enumerate(rem_s) if idx not in matched_s]

        i = 0
        while i < len(rem_a):
            a = rem_a[i]
            found = False
            for j, s in enumerate(rem_s):
                if abs(a["Amount"] - s["Amount"]) < 0.01:
                    mismatch.append(_mismatch_row(a, s, "Service Mismatch", 0))
                    rem_s.pop(j)
                    rem_a.pop(i)
                    found = True
                    break
            if not found:
                i += 1

        while rem_a and rem_s:
            a = rem_a.pop(0)
            s = rem_s.pop(0)
            mismatch.append(_mismatch_row(a, s, "Amount Mismatch", a["Amount"] - s["Amount"]))

        if rem_a:
            remaining_abr_by_name[name] = rem_a
        if rem_s:
            remaining_sot_by_name[name] = rem_s

    log_fn(f"  Perfect: {len(perfect)}, Mismatches: {len(mismatch)}")

    log_fn("── Phase 4: Fuzzy Name-Level Linkage ──")
    spelling_pairs = _find_fuzzy_name_pairs(
        remaining_abr_by_name,
        remaining_sot_by_name,
        fuzzy_threshold=fuzzy_threshold,
    )
    log_fn(f"  Found {len(spelling_pairs)} fuzzy name pairs for secondary review.")

    consumed_abr = {p["abr_norm"] for p in spelling_pairs}
    consumed_sot = {p["sot_norm"] for p in spelling_pairs}

    final_unique_abr = [
        e for name, entries in remaining_abr_by_name.items()
        if name not in consumed_abr for e in entries
    ]
    final_unique_sot = [
        e for name, entries in remaining_sot_by_name.items()
        if name not in consumed_sot for e in entries
    ]

    log_fn("── Phase 5: Blind Match (Nameless SoT) ──")
    blind_matches: list[dict] = []
    remaining_nameless: list[dict] = []
    consumed_blind: set[int] = set()
    for ns in nameless_sot_pool:
        found = False
        for j, al in enumerate(final_unique_abr):
            if j in consumed_blind:
                continue
            if (
                pd.notna(ns["Date"])
                and pd.notna(al["Date"])
                and ns["Date"] == al["Date"].normalize()
                and abs(ns["Amt"] - al["Amount"]) < 0.01
            ):
                blind_matches.append({
                    "abr": al,
                    "sot": {
                        "Row_ID": ns["Row_ID"],
                        "Original_Name": "",
                        "Original_Service": ns["Service"],
                        "Amount": ns["Amt"],
                        "Date": ns["Date"],
                        "Source": ns["Source"],
                        "Raw": ns["Raw"],
                    },
                    "day_diff": 0,
                })
                consumed_blind.add(j)
                found = True
                break
        if not found:
            remaining_nameless.append(ns)

    final_unique_abr = [al for j, al in enumerate(final_unique_abr) if j not in consumed_blind]

    matched_rows = [match_to_row(p, "Perfect Match") for p in perfect]
    matched_rows.extend(match_to_row(b, "Blind Match") for b in blind_matches)

    pm_path = os.path.join(output_dir, perfect_matches_filename(date_label))
    write_matched_workbook(matched_rows, pm_path)
    log_fn(f"  Wrote matched records: {pm_path}")

    mismatch_output = [{k: v for k, v in row.items() if not k.endswith(" Entry")} for row in mismatch]
    spelling_reports = _build_spelling_reports(spelling_pairs)

    unmatched_path = os.path.join(output_dir, "Unmatched_Analysis.xlsx")
    with pd.ExcelWriter(unmatched_path, engine="openpyxl") as writer:
        pd.DataFrame(mismatch_output).to_excel(writer, sheet_name="Mismatches", index=False)
        pd.DataFrame(spelling_reports).to_excel(writer, sheet_name="Possible_Spelling_Matches", index=False)
        pd.DataFrame([raw_with_row_id(a) for a in final_unique_abr]).to_excel(
            writer, sheet_name="Unique_Abronal", index=False
        )
        pd.DataFrame([raw_with_row_id(s) for s in final_unique_sot]).to_excel(
            writer, sheet_name="SoT_Leftovers", index=False
        )

    intermediate = {
        "date_label": date_label,
        "matched_path": pm_path,
        "unmatched_path": unmatched_path,
        "counts": {
            "perfect": len(perfect),
            "blind": len(blind_matches),
            "mismatch": len(mismatch),
            "spelling_pairs": len(spelling_pairs),
            "unique_abronal": len(final_unique_abr),
            "sot_leftovers": len(final_unique_sot),
            "nameless_sot": len(remaining_nameless),
        },
        "spelling_pairs": [
            {
                "abr_norm": p["abr_norm"],
                "sot_norm": p["sot_norm"],
                "similarity_pct": p["similarity_pct"],
                "abr_entries": [_serialize_entry(e) for e in p["abr_entries"]],
                "sot_entries": [_serialize_entry(e) for e in p["sot_entries"]],
            }
            for p in spelling_pairs
        ],
        "unique_abronal": [_serialize_entry(e) for e in final_unique_abr],
        "unique_sot": [_serialize_entry(e) for e in final_unique_sot],
        "matched_rows": matched_rows,
    }
    state_path = os.path.join(output_dir, "primary_state.json")
    save_intermediate_json(intermediate, state_path)
    log_fn(f"  Wrote pipeline state: {state_path}")

    log_fn("\n═══════════════════════════════════════")
    log_fn("  PRIMARY RECONCILIATION COMPLETE")
    log_fn("═══════════════════════════════════════")

    return {
        "date_label": date_label,
        "matched_path": pm_path,
        "unmatched_path": unmatched_path,
        "state_path": state_path,
        "matched_count": len(matched_rows),
        "mismatched_count": len(mismatch) + len(spelling_pairs) + len(final_unique_abr) + len(final_unique_sot),
    }


def _mismatch_row(a, s, status, difference):
    return {
        "Status": status,
        "Abronal Row ID": a["Row_ID"],
        "SoT Row ID": s["Row_ID"],
        "Abronal Name": a["Original_Name"],
        "Abronal Service": a["Original_Service"],
        "Abronal Amount": a["Amount"],
        "SoT Name": s["Original_Name"],
        "SoT Service": s["Original_Service"],
        "SoT Amount": s["Amount"],
        "Source": s["Source"],
        "File": a["File"],
        "Difference": difference,
    }


def _find_fuzzy_name_pairs(remaining_abr, remaining_sot, *, fuzzy_threshold=0.80):
    abr_names = list(remaining_abr.keys())
    sot_names = list(remaining_sot.keys())
    sot_by_letter: dict[str, list[str]] = {}
    for sn in sot_names:
        letter = sn[0] if sn else ""
        sot_by_letter.setdefault(letter, []).append(sn)

    pairs = []
    consumed_sot: set[str] = set()
    for an in abr_names:
        letter = an[0] if an else ""
        candidates = [c for c in sot_by_letter.get(letter, []) if c not in consumed_sot]
        if not candidates:
            continue
        best_score = 0.0
        best_match = None
        for cand in candidates:
            score = advanced_name_match(an, cand)
            if score > best_score:
                best_score = score
                best_match = cand
        if best_match and best_score >= fuzzy_threshold:
            pairs.append({
                "abr_norm": an,
                "sot_norm": best_match,
                "similarity_pct": round(best_score * 100, 1),
                "abr_entries": remaining_abr.get(an, []),
                "sot_entries": remaining_sot.get(best_match, []),
            })
            consumed_sot.add(best_match)
    return pairs


def _build_spelling_reports(spelling_pairs):
    reports = []
    for pair in spelling_pairs:
        abr_entries = pair["abr_entries"]
        sot_entries = pair["sot_entries"]
        abr_sample = abr_entries[0] if abr_entries else None
        sot_sample = sot_entries[0] if sot_entries else None
        max_rows = max(len(abr_entries), len(sot_entries), 1)
        for idx in range(max_rows):
            row = {
                "Abronal Name": abr_sample["Original_Name"] if abr_sample else "",
                "SoT Name": sot_sample["Original_Name"] if sot_sample else "",
                "Similarity (%)": pair["similarity_pct"],
            }
            if idx < len(abr_entries):
                ae = abr_entries[idx]
                row.update({
                    "Abronal Row ID": ae["Row_ID"],
                    "Abronal Service": ae["Original_Service"],
                    "Abronal Amount": ae["Amount"],
                    "Abronal Date": ae.get("Original_Timestamp", ae.get("Date")),
                    "Abronal File": ae.get("File", ""),
                })
            if idx < len(sot_entries):
                se = sot_entries[idx]
                row.update({
                    "SoT Row ID": se["Row_ID"],
                    "SoT Service": se["Original_Service"],
                    "SoT Amount": se["Amount"],
                    "SoT Date": se["Date"],
                    "SoT Source": se.get("Source", ""),
                })
            reports.append(row)
        if reports:
            reports.append({k: "" for k in reports[-1]})
    return reports


def _serialize_entry(entry: dict) -> dict:
    out = {k: v for k, v in entry.items() if k != "Raw"}
    out["Date"] = str(entry.get("Date", ""))
    if "Original_Timestamp" in entry:
        out["Original_Timestamp"] = str(entry["Original_Timestamp"])
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description="Primary Abronal vs SoT reconciliation")
    parser.add_argument("--abr", required=True, help="Abronal Excel folder")
    parser.add_argument("--sot", required=True, help="SoT Excel folder")
    parser.add_argument("--out", required=True, help="Output folder")
    parser.add_argument("--date-label", help='Date range label, e.g. "July 20 to July 22"')
    parser.add_argument(
        "--fuzzy-threshold",
        type=float,
        default=0.80,
        help="Name similarity threshold for spelling-match candidates (default 0.80)",
    )
    args = parser.parse_args()

    try:
        run_primary_reconciliation(
            args.abr,
            args.sot,
            args.out,
            date_label=args.date_label,
            fuzzy_threshold=args.fuzzy_threshold,
        )
        return 0
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
