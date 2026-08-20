# Reconciliation Console

A FastAPI web app that replaces the Tk desktop tools (`service_analyzer.py`,
`reconciliation_app_v5.py`, `export_physician_performance.py`) with a
browser UI backed by `commissions.db` (SQLite), managed exclusively through
Python scripts (never edited by hand).

## Layout

```
app/
  db/
    schema.sql        mended schema: physicians / service_prices tables,
                       FKs from abronal_mirror, sot_mirror, matched_records,
                       unmatched_records, commission_per_physicians
    db_manager.py      the ONLY module that opens sqlite3 connections
    column_adapter.py   maps real Abronal/SoT header spellings to the
                         canonical field names the rest of the pipeline
                         uses, and auto-detects the real header row under
                         any title/criteria rows a source file has above it
  scripts/new/          the "neo-scripts" pipeline
    abronal_scraper.py           STEP 0 — logs into Abronal (Playwright)
                                  and downloads each physician's export
                                  straight into data/uploads/abronal/
    primary_reconciliation.py    parse Abronal (physician name = filename)
                                  + SoT, exact-match, split matched/unmatched
    secondary_name_matcher.py    load_mismatched_data / name_comparator
                                  (>=70% similarity + amount + ±1 day) / grafter
    category_merger.py           Condensor: read_dictionary / load_data /
                                  list_condensor -> commission_per_physicians
  backend/
    main.py             FastAPI app, serves the frontend + mounts routers
    routers/
      scraper.py          trigger an Abronal fetch, websocket log/progress
      pipeline.py          file upload, run pipeline, websocket log/progress
      tables.py             browse/filter any table
      export.py               export one table or the whole DB to .xlsx
  frontend/
    index.html           Intake & Run page (fetch, upload, run, progress, log)
    evaluation.html       Evaluation page (table browser, filters, export)
    style.css
  dictionary.json         service -> category rules (seeds service_prices)
  examples/                real Abronal/SoT export templates (headers only)
                            used to validate the column adapter — handy for
                            testing header-matching changes without needing
                            a live Abronal login
  config.json               scraper settings: headless mode, patient type,
                             physician skip-list (same shape as the old
                             config.json's non-secret fields)
  .env.example               template for Abronal login credentials
  exports/                 generated .xlsx exports land here
  data/uploads/{sot,abronal}/   uploaded / scraped source files land here
```

## Setup

```bash
cd app
pip install -r requirements.txt
playwright install chromium        # one-time browser download for the scraper

cp .env.example .env               # then fill in real values:
#   BASE_URL, USERNAME, PASSWORD, ROLE

python db/db_manager.py --init
python db/db_manager.py --seed-dictionary dictionary.json

uvicorn backend.main:app --reload --port 8000
```

Then open `http://localhost:8000` (Intake & Run) and
`http://localhost:8000/evaluation` (Evaluation).

`.env` holds real login credentials — never commit it. If `.env` is missing
or incomplete, the "Fetch from Abronal" panel will say so and any fetch
attempt fails cleanly with a message like `BASE_URL is not set`, without a
stack trace. You can skip it entirely and just drag Abronal `.xlsx` files
into the upload zone instead, as before.

## Column adapter

Real Abronal and SoT exports don't start with a clean header row, and
header text isn't perfectly consistent between exports. `db/column_adapter.py`
handles both problems so `primary_reconciliation.py` never has to guess:

- **Header row detection.** Abronal exports carry one title row above the
  real header (`"Physician Performance - Abronal eHealth"`); SoT exports
  carry three (a clinic title, a criteria line, and a blank row). The
  adapter scans the first ~20 rows of each sheet and picks the one whose
  cells best match a known column name — it doesn't assume row 0.
- **Header spelling.** Each canonical DB field (`patient_full_name`,
  `sub_total`, `commission_percent`, ...) lists the header text variants it
  should recognize (`ABRONAL_SCHEMA` / `SOT_SCHEMA` in that file), matched
  case/punctuation/underscore-insensitively — `"Tin_no"`, `"TIN No."`, and
  `"tin number"` all resolve to `tin_number`. Matched columns are renamed to
  their canonical name; anything unrecognized is kept as-is (never silently
  dropped) and logged so it's visible in the run log.
- **To support a new header spelling or a whole new source format**, add
  the alias to the relevant schema dict — nothing else in the pipeline
  needs to change.
- **Physician-name extraction** (`primary_reconciliation.py`,
  `physician_from_filename()`) is naming-order agnostic: it locates the
  `Dr`/`Dr.` token and reads name words from there, stopping at the first
  date-like token (month name, day, day-range, year, or slash/dash date).
  This handles both the real-world convention (`"dr bart jacobs july
  1-9.xlsx"` -> `Dr. Bart Jacobs`) and the older date-first convention the
  original export tool used (`"July 20 to July 22 Dr. Ahmed Reja.xlsx"` ->
  `Dr. Ahmed Reja`). The scraper (`abronal_scraper.py`) now names its own
  downloads physician-first to match the real-world convention.

## Pipeline order

0. **abronal_scraper.py** *(optional, triggered by the "Fetch from Abronal"
   panel on the Intake page)* — logs into Abronal with Playwright, opens the
   Physician Performance report, and downloads one `.xlsx` per physician for
   the date range you pick, naming each file physician-first, matching how
   Abronal names these exports in practice: `"Dr. Name <date label>.xlsx"`.
   Files land directly in `data/uploads/abronal/`, so step 1 below picks
   them up with no manual download/upload step. You can restrict it to
   specific physicians (comma-separated names) or leave it blank to export
   everyone not on the `skip_physicians` list in `config.json`.
1. **primary_reconciliation.py** — parses every Abronal `.xlsx` (columns
   resolved through `column_adapter.py`; physician name taken from the
   filename via `physician_from_filename()`, e.g. `"dr bart jacobs july
   1-9.xlsx"` -> `Dr. Bart Jacobs`) and every SoT `.xlsx`, mirrors both into
   `abronal_mirror` / `sot_mirror`, exact-matches on name+amount, and writes
   `matched_records` / `unmatched_records`.
2. **secondary_name_matcher.py** — for the leftovers, tries to fix spelling
   mismatches: candidate pairs need >=70% character similarity, matching
   amount, and visit dates within 1 day. Matches are renamed to the Abronal
   name, buffered, then grafted into `matched_records` (removed from
   `unmatched_records`).
3. **category_merger.py** — `Condensor` reads `dictionary.json`, loads all
   matched rows for the batch, and condenses them into one row per
   physician/patient/date in `commission_per_physicians`, with one summed
   total per category (Laboratory, X-ray, Ultrasound, Nursing & Procedures,
   Consultation, ECG/Echocardiography/Supplies folded into an `other` column
   for now — extend `CATEGORY_COLUMN_MAP` in `db_manager.py` if you want
   dedicated columns for those too).

All four scripts can also be run standalone from the CLI (see each file's
`__main__` block) for debugging outside the web app, e.g.:

```bash
python scripts/new/abronal_scraper.py --from-date 2026-08-10 --to-date 2026-08-11
python scripts/new/primary_reconciliation.py --abr data/uploads/abronal --sot data/uploads/sot
python scripts/new/secondary_name_matcher.py --batch <batch_id>
python scripts/new/category_merger.py --batch <batch_id>
```

See `CHANGELOG.md` for what changed since the previous version.
