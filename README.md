# Commission Reconciliation App

This repository combines Excel-based reconciliation, service category consolidation, commission summary generation, and persistent storage into one workflow.

## What it does

- Loads Abronal and SoT Excel files from folders
- Performs exact and fuzzy matching of patient names and services
- Splits results into:
  - Perfect matches
  - Mismatched rows
  - Remaining unique Abronal or SoT records
  - Nameless SoT records
- Uses a shared `configs/dictionary.json` file to map services into categories
- Condenses matched services by category per patient
- Produces output Excel workbooks for:
  - `Perfect Matches.xlsx`
  - `Unmatched_Analysis.xlsx`
  - `Blind_Matches.xlsx`
  - `Nameless_SoT_Records.xlsx`
  - `Service_Summary_Report.xlsx`
  - `Commission_Summary.xlsx`
- Persists perfect-match records into a local SQLite database at `database/commission.db`

## Key scripts

- `scripts/reconciliation_app_v5.py`
  - Main reconciliation GUI and workflow
  - Loads files, matches by name/service/date, reviews fuzzy matches, and writes output
  - Saves matched records to the database
- `scripts/service_analyzer.py`
  - UI for categorizing services and summarizing by patient/date
  - Includes `Condensor` for category-based service aggregation
- `configs/dictionary.json`
  - Shared service-to-category dictionary used by the reconciliation and analysis flow
- `server/app/main.py`
  - FastAPI backend for record storage and export jobs

## How to run

### Reconciliation GUI

From repository root:

```bash
python scripts/reconciliation_app_v5.py
```

Then choose:

- Abronal input folder
- SoT input folder
- Output folder

### Commission summary and database persistence

The reconciliation tool now writes both a commission summary workbook and persists perfect matched records into `database/commission.db`.

### Service analyzer UI

From repository root:

```bash
python scripts/service_analyzer.py
```

Use it to categorize services, generate a category-based pivot summary, and export a grand summary workbook.

## Database

- SQLite database: `database/commission.db`
- Table: `records`
- Columns: `id`, `doctor_name`, `service`, `amount`, `category`, `date`

## Notes

- `configs/config.json` stores exporter and scraper configurations for other scripts.
- `scripts/export_physician_performance.py` is a separate export automation tool and is not needed for reconciliation flow.
- The new flow is aligned with the build directions by using `configs/dictionary.json` for category mapping and producing consolidated commission results.
