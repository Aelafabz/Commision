"""
Secondary name matcher: resolve remaining name mismatches using confidence
rules (≥70% name similarity, matching amount, visit date within ±1 day).

Matched pairs are grafted back into the reconciled dataset; unresolved rows
remain in the unreconciled group.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import pandas as pd

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from common.io_utils import (
    load_intermediate_json,
    match_to_row,
    save_intermediate_json,
    write_matched_workbook,
)
from common.matching import secondary_name_confidence, signed_day_difference


def load_mismatched_data(state_path: str) -> dict:
    """Load primary reconciliation state including spelling pairs and leftovers."""
    state = load_intermediate_json(state_path)
    return {
        "spelling_pairs": state.get("spelling_pairs", []),
        "unique_abronal": state.get("unique_abronal", []),
        "unique_sot": state.get("unique_sot", []),
        "matched_rows": state.get("matched_rows", []),
        "date_label": state.get("date_label", ""),
        "matched_path": state.get("matched_path", ""),
    }


def _entry_from_serialized(data: dict) -> dict:
    return {
        "Row_ID": data.get("Row_ID", ""),
        "Norm_Name": data.get("Norm_Name", ""),
        "Original_Name": data.get("Original_Name", ""),
        "Norm_Service": data.get("Norm_Service", ""),
        "Original_Service": data.get("Original_Service", ""),
        "Amount": data.get("Amount", 0),
        "Date": pd.to_datetime(data.get("Date"), errors="coerce"),
        "Original_Timestamp": data.get("Original_Timestamp", data.get("Date", "")),
        "File": data.get("File", ""),
        "Source": data.get("Source", ""),
    }


def name_comparator(
    mismatched: dict,
    *,
    name_threshold: float = 0.70,
    date_tolerance_days: int = 1,
    log_fn=print,
) -> tuple[list[dict], list[dict], list[dict]]:
    """
    Attempt to pair Abronal and SoT rows from spelling candidates and leftovers.

    Returns (buffer, still_unreconciled_abr, still_unreconciled_sot).
    """
    buffer: list[dict] = []
    unreconciled_abr: list[dict] = []
    unreconciled_sot: list[dict] = []

    for pair in mismatched["spelling_pairs"]:
        abr_entries = [_entry_from_serialized(e) for e in pair.get("abr_entries", [])]
        sot_entries = [_entry_from_serialized(e) for e in pair.get("sot_entries", [])]
        consumed_sot: set[int] = set()

        for abr in abr_entries:
            matched = False
            for si, sot in enumerate(sot_entries):
                if si in consumed_sot:
                    continue
                ok, score = secondary_name_confidence(
                    abr,
                    sot,
                    name_threshold=name_threshold,
                    date_tolerance_days=date_tolerance_days,
                )
                if ok:
                    buffer.append({
                        "abr": abr,
                        "sot": sot,
                        "day_diff": signed_day_difference(abr["Date"], sot["Date"]),
                        "name_confidence": round(score * 100, 1),
                        "resolved_name": abr["Original_Name"],
                    })
                    consumed_sot.add(si)
                    matched = True
                    log_fn(
                        f"  Matched: {abr['Original_Name']} ↔ {sot['Original_Name']} "
                        f"({score * 100:.1f}%, amt={abr['Amount']})"
                    )
                    break
            if not matched:
                unreconciled_abr.append(abr)

        for si, sot in enumerate(sot_entries):
            if si not in consumed_sot:
                unreconciled_sot.append(sot)

    leftover_abr = [_entry_from_serialized(e) for e in mismatched.get("unique_abronal", [])]
    leftover_sot = [_entry_from_serialized(e) for e in mismatched.get("unique_sot", [])]

    consumed_leftover_sot: set[int] = set()
    for abr in leftover_abr:
        matched = False
        for si, sot in enumerate(leftover_sot):
            if si in consumed_leftover_sot:
                continue
            ok, score = secondary_name_confidence(
                abr,
                sot,
                name_threshold=name_threshold,
                date_tolerance_days=date_tolerance_days,
            )
            if ok:
                buffer.append({
                    "abr": abr,
                    "sot": sot,
                    "day_diff": signed_day_difference(abr["Date"], sot["Date"]),
                    "name_confidence": round(score * 100, 1),
                    "resolved_name": abr["Original_Name"],
                })
                consumed_leftover_sot.add(si)
                matched = True
                log_fn(
                    f"  Matched leftover: {abr['Original_Name']} ↔ {sot['Original_Name']} "
                    f"({score * 100:.1f}%)"
                )
                break
        if not matched:
            unreconciled_abr.append(abr)

    for si, sot in enumerate(leftover_sot):
        if si not in consumed_leftover_sot:
            unreconciled_sot.append(sot)

    log_fn(f"  Secondary buffer: {len(buffer)} pairs")
    log_fn(f"  Still unreconciled: {len(unreconciled_abr)} Abronal, {len(unreconciled_sot)} SoT")
    return buffer, unreconciled_abr, unreconciled_sot


def grafter(
    existing_matched_rows: list[dict],
    buffer: list[dict],
    *,
    output_path: str,
) -> list[dict]:
    """Merge secondary buffer into the reconciled list and write updated workbook."""
    new_rows = [match_to_row(p, "Secondary Name Match") for p in buffer]
    combined = existing_matched_rows + new_rows
    write_matched_workbook(combined, output_path)
    return combined


def run_secondary_matching(
    state_path: str,
    output_dir: str,
    *,
    name_threshold: float = 0.70,
    date_tolerance_days: int = 1,
    log_fn=print,
) -> dict:
    """Full secondary pass: load → compare → graft → save."""
    os.makedirs(output_dir, exist_ok=True)
    log_fn("── Loading mismatched data ──")
    mismatched = load_mismatched_data(state_path)

    log_fn("── Name comparison (secondary confidence rules) ──")
    buffer, unreconciled_abr, unreconciled_sot = name_comparator(
        mismatched,
        name_threshold=name_threshold,
        date_tolerance_days=date_tolerance_days,
        log_fn=log_fn,
    )

    matched_path = mismatched.get("matched_path") or os.path.join(output_dir, "Perfect Matches.xlsx")
    if not os.path.isabs(matched_path):
        matched_path = os.path.join(output_dir, os.path.basename(matched_path))

    log_fn("── Grafting buffer into reconciled list ──")
    combined = grafter(mismatched["matched_rows"], buffer, output_path=matched_path)

    unreconciled_path = os.path.join(output_dir, "Still_Unreconciled.xlsx")
    with pd.ExcelWriter(unreconciled_path, engine="openpyxl") as writer:
        pd.DataFrame([
            {
                "Row ID": e["Row_ID"],
                "Patient Name": e["Original_Name"],
                "Service": e["Original_Service"],
                "Amount": e["Amount"],
                "Date": e.get("Original_Timestamp", e.get("Date")),
                "File": e.get("File", ""),
            }
            for e in unreconciled_abr
        ]).to_excel(writer, sheet_name="Unique_Abronal", index=False)
        pd.DataFrame([
            {
                "Row ID": e["Row_ID"],
                "Patient Name": e["Original_Name"],
                "Service": e["Original_Service"],
                "Amount": e["Amount"],
                "Date": e.get("Date"),
                "Source": e.get("Source", ""),
            }
            for e in unreconciled_sot
        ]).to_excel(writer, sheet_name="SoT_Leftovers", index=False)

    secondary_state = {
        "matched_path": matched_path,
        "unreconciled_path": unreconciled_path,
        "matched_rows": combined,
        "unreconciled_abr": [
            {k: v for k, v in e.items() if k != "Raw"} for e in unreconciled_abr
        ],
        "unreconciled_sot": [
            {k: v for k, v in e.items() if k != "Raw"} for e in unreconciled_sot
        ],
        "secondary_resolved_count": len(buffer),
    }
    state_out = os.path.join(output_dir, "secondary_state.json")
    save_intermediate_json(secondary_state, state_out)

    log_fn("\n═══════════════════════════════════════")
    log_fn("  SECONDARY NAME MATCHING COMPLETE")
    log_fn("═══════════════════════════════════════")

    return {
        "matched_path": matched_path,
        "unreconciled_path": unreconciled_path,
        "state_path": state_out,
        "resolved_count": len(buffer),
        "unreconciled_count": len(unreconciled_abr) + len(unreconciled_sot),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Secondary name matcher for unreconciled rows")
    parser.add_argument(
        "--state",
        required=True,
        help="primary_state.json from primary reconciliation",
    )
    parser.add_argument("--out", required=True, help="Output folder (usually same as primary)")
    parser.add_argument(
        "--name-threshold",
        type=float,
        default=0.70,
        help="Minimum name similarity (default 0.70)",
    )
    parser.add_argument(
        "--date-tolerance",
        type=int,
        default=1,
        help="Maximum day difference between visits (default ±1)",
    )
    args = parser.parse_args()

    try:
        run_secondary_matching(
            args.state,
            args.out,
            name_threshold=args.name_threshold,
            date_tolerance_days=args.date_tolerance,
        )
        return 0
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
