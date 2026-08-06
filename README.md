Commission Reconciliation Pipeline

Overview
- This repository contains scripts to reconcile Abronal exports against SoT (Source of Truth) data, perform secondary fuzzy name matching, and condense service-level rows into category summaries.

Primary scripts
- scripts/run_pipeline.py: Orchestrates the full pipeline (primary, secondary, category merge).
- scripts/primary_reconciliation.py: Exact and fuzzy primary matching, produces primary_state.json and matched workbooks.
- scripts/secondary_name_matcher.py: Attempts secondary name matching for leftovers and grafts matches back into the matched workbook.
- scripts/category_merger.py: Condenses services into category totals using configs/dictionary.json.

Usage (command-line)

1) Run full pipeline

python3 scripts/run_pipeline.py --abr /path/to/abronal_folder --sot /path/to/sot_folder --out /path/to/output_folder

Options:
--date-label: Custom date label used in summary filenames
--skip-secondary: Skip the secondary name matching stage
--skip-category: Skip the category merger stage
--dictionary: Path to configs/dictionary.json
--name-threshold: Secondary name similarity threshold (default 0.70)
--date-tolerance: Date tolerance in days for secondary matching (default 1)

2) Run modules individually

python3 scripts/primary_reconciliation.py --abr /path/to/abr --sot /path/to/sot --out /path/to/out
python3 scripts/secondary_name_matcher.py --state /path/to/primary_state.json --out /path/to/out
python3 scripts/category_merger.py --input /path/to/matched.xlsx --out /path/to/summary.xlsx --dictionary configs/dictionary.json

Notes & Recommendations
- Python 3.9+ recommended. Install required packages from requirements.txt.
- Input Excel files should follow the expected column conventions; the data loader normalizes many common column name variants.
- Review `configs/dictionary.json` to adjust service → category mappings before running the category merger.
- If you encounter errors, run modules individually to isolate the failing stage and inspect intermediate JSON state files (`primary_state.json`, `secondary_state.json`).

Contact
- For changes or issues, update scripts in the `scripts/` folder and add tests if possible.
