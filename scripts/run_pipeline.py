#!/usr/bin/env python3
"""
End-to-end commission reconciliation pipeline.

Stages:
  1. Primary reconciliation  (Abronal vs SoT exact + fuzzy split)
  2. Secondary name matching   (70% name + amount + date ±1)
  3. Category merger           (condense services into category totals)
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from category_merger import run_category_merger
from common.io_utils import infer_date_label
from primary_reconciliation import run_primary_reconciliation
from secondary_name_matcher import run_secondary_matching


def run_pipeline(
    abr_dir: str,
    sot_dir: str,
    output_dir: str,
    *,
    date_label: str | None = None,
    skip_secondary: bool = False,
    skip_category: bool = False,
    dictionary_path: str | None = None,
    name_threshold: float = 0.70,
    date_tolerance: int = 1,
    log_fn=print,
) -> dict:
    date_label = (date_label or "").strip() or infer_date_label(output_dir, abr_dir, sot_dir)

    log_fn("=" * 50)
    log_fn("STAGE 1: Primary Reconciliation")
    log_fn("=" * 50)
    primary = run_primary_reconciliation(
        abr_dir, sot_dir, output_dir, log_fn=log_fn, date_label=date_label
    )

    secondary = None
    if not skip_secondary:
        log_fn("")
        log_fn("=" * 50)
        log_fn("STAGE 2: Secondary Name Matching")
        log_fn("=" * 50)
        secondary = run_secondary_matching(
            primary["state_path"],
            output_dir,
            name_threshold=name_threshold,
            date_tolerance_days=date_tolerance,
            log_fn=log_fn,
        )
    else:
        log_fn("Skipping secondary name matching.")

    category_path = None
    if not skip_category:
        log_fn("")
        log_fn("=" * 50)
        log_fn("STAGE 3: Category Merger")
        log_fn("=" * 50)
        matched_input = (
            secondary["matched_path"] if secondary else primary["matched_path"]
        )
        unreconciled = (
            secondary["unreconciled_path"] if secondary else None
        )
        summary_name = f"{date_label} Category Summary.xlsx" if date_label else "Category_Summary.xlsx"
        category_path = str(Path(output_dir) / summary_name)
        dict_path = dictionary_path or str(PROJECT_ROOT / "configs" / "dictionary.json")

        run_category_merger(
            matched_input,
            category_path,
            dictionary_path=dict_path,
            unreconciled_path=unreconciled,
            log_fn=log_fn,
        )

        if unreconciled:
            buffer_summary = str(
                Path(output_dir)
                / (f"{date_label} Unreconciled Summary.xlsx" if date_label else "Unreconciled_Summary.xlsx")
            )
            run_category_merger(
                unreconciled,
                buffer_summary,
                dictionary_path=dict_path,
                log_fn=log_fn,
            )
            log_fn(f"  Unreconciled summary: {buffer_summary}")
    else:
        log_fn("Skipping category merger.")

    log_fn("")
    log_fn("=" * 50)
    log_fn("PIPELINE COMPLETE")
    log_fn("=" * 50)

    return {
        "primary": primary,
        "secondary": secondary,
        "category_summary": category_path,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Run full commission reconciliation pipeline")
    parser.add_argument("--abr", required=True, help="Abronal Excel folder")
    parser.add_argument("--sot", required=True, help="SoT Excel folder")
    parser.add_argument("--out", required=True, help="Output / analysis folder")
    parser.add_argument("--date-label", help='Date range label, e.g. "July 20 to July 22"')
    parser.add_argument("--skip-secondary", action="store_true")
    parser.add_argument("--skip-category", action="store_true")
    parser.add_argument("--dictionary", help="Path to dictionary.json")
    parser.add_argument("--name-threshold", type=float, default=0.70)
    parser.add_argument("--date-tolerance", type=int, default=1)
    args = parser.parse_args()

    try:
        run_pipeline(
            args.abr,
            args.sot,
            args.out,
            date_label=args.date_label,
            skip_secondary=args.skip_secondary,
            skip_category=args.skip_category,
            dictionary_path=args.dictionary,
            name_threshold=args.name_threshold,
            date_tolerance=args.date_tolerance,
        )
        return 0
    except Exception as exc:
        print(f"PIPELINE ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
