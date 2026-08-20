# Changelog

## v0.3 — Column adapter for real-world Abronal/SoT formats

**Added**
- `db/column_adapter.py` — new module sitting between raw uploaded sheets
  and the fixed columns `commissions.db` expects.
  - `ABRONAL_SCHEMA` / `SOT_SCHEMA`: each canonical DB field (e.g.
    `patient_full_name`, `sub_total`, `commission_percent`) lists the
    header spellings it should recognize.
  - `adapt_sheet(path, schema, log=...)`: reads a sheet with no assumed
    header row, scans the first ~20 rows to find the one that actually
    looks like a header (scoring how many cells match a known alias),
    and returns a DataFrame renamed to canonical column names. Built
    specifically around the real files: Abronal exports carry one title
    row (`"Physician Performance - Abronal eHealth"`) above the header;
    SoT exports carry three (clinic title, criteria line, blank row).
    Header matching is case/punctuation/underscore-insensitive, so
    `"Tin_no"`, `"TIN No."`, and `"tin number"` all resolve the same way.
    Unrecognized columns are kept (not dropped) and logged, so nothing
    silently disappears.
  - `get_str` / `get_float` / `get_int`: typed row getters that tolerate a
    canonical column being entirely absent from a given file, defaulting
    instead of raising.
  - Raises `ColumnAdapterError` (not a generic exception) when no header
    row can be found with confidence, so a malformed upload fails with a
    clear log line naming the file instead of silently importing 0 rows
    or garbage.

**Changed**
- `scripts/new/primary_reconciliation.py`
  - `parse_abronal_dir()` / `parse_sot_dir()` rewritten to call
    `column_adapter.adapt_sheet()` instead of the old manual "guess a
    column name" lookup helper — this is the fix for headers/rows not
    lining up with what the previous version assumed.
  - `physician_from_filename()` rewritten to be naming-order agnostic. It
    now locates the `Dr`/`Dr.` token and reads name words outward from
    there, stopping at the first date-like token (month name, day, day
    range like `"1-9"`, year, or slash/dash date). Verified against both
    the real-world convention (`"dr bart jacobs july 1-9.xlsx"` -> `Dr.
    Bart Jacobs`) and the older date-first convention the original
    `export_physician_performance.py` used (`"July 20 to July 22 Dr.
    Ahmed Reja.xlsx"` -> `Dr. Ahmed Reja`), so old and new files can sit in
    the same upload folder without special-casing.
- `scripts/new/abronal_scraper.py` — `export_one()` now names its
  downloads physician-first (`"Dr. Name <date label>.xlsx"`) to match how
  Abronal names these exports in practice, instead of the old tool's
  date-first convention.
- `README.md` — new "Column adapter" section explaining header-row
  detection, alias matching, and how to add support for a new header
  spelling or source format; pipeline-order section's example filenames
  updated to match the real naming convention.

**Verified**
- Ran `column_adapter.adapt_sheet()` directly against the real
  `abronal-example.xlsx` (12/12 canonical columns matched, header
  correctly found at row 1 under the title row) and `sot-example.xlsx`
  (14/14 matched, header correctly found at row 3 under three leading
  rows).
- Built populated versions of both templates with realistic data and a
  physician-first filename (`"dr bart jacobs july 1-9.xlsx"`), then ran
  the full pipeline (primary reconciliation -> secondary name matcher ->
  category merger) both standalone and through the live FastAPI
  endpoints. Physician was correctly recorded as `Dr. Bart Jacobs`
  (extracted from the filename), 2 exact matches and 1 fuzzy-name match
  were found, and `commission_per_physicians` came out with 3 correctly
  condensed rows.
- Spot-checked `physician_from_filename()` against six filename variants
  (physician-first, date-first, different date formats, different casing)
  — all five filesystem-realistic cases resolved to the correct name.

## v0.2 — Abronal scraper integrated into the web app

**Added**
- `scripts/new/abronal_scraper.py` — new neo-script (step 0 of the
  pipeline). Ports the Playwright login/report/export flow out of the old
  standalone `export_physician_performance.py` (its `AbronalSession`,
  `DateRange`, and `Physician` classes) and adapts it to run headlessly
  from the web app: no Tk date picker, no subprocess hand-off to a
  reconciliation app, no SoT-folder wait dialog — it just logs in, exports
  each requested physician's report for a given date range, and drops the
  files straight into `data/uploads/abronal/` using the same
  `"<date label> Dr. Name.xlsx"` naming `primary_reconciliation.py` already
  parses. Raises a clean `ScraperError` (not a stack trace) for missing
  config, bad dates, or an unknown physician name.
- `backend/routers/scraper.py` — new FastAPI router: `POST
  /api/scraper/run` (kicks off a scrape in a background thread), `GET
  /api/scraper/status/{batch_id}`, `GET /api/scraper/log/{batch_id}`, `WS
  /api/scraper/ws/{batch_id}` for live progress, and `GET
  /api/scraper/config-check` so the UI can tell the person whether `.env`
  credentials are present without ever exposing them. Mirrors the existing
  `pipeline.py` router's log-buffer/websocket pattern for consistency.
- **Intake page** — new "01 · Fetch from Abronal" panel above the upload
  zones: From/To date pickers, an optional comma-separated physician-name
  filter, a "Fetch from Abronal" button, its own progress bar, status
  banner, and log window (reusing the same websocket-driven UI pattern as
  the reconciliation run). On success it auto-refreshes the Abronal
  upload-file list so the newly scraped files are visible immediately.
  Section numbers on the rest of the page were bumped (SoT upload is now
  "02", Abronal upload "03", Run Pipeline "04", System Log "05").
- `config.json` (new, at the project root) — non-secret scraper settings:
  `headless`, `patient_type`, `skip_physicians` (same shape as the old
  desktop tool's config, credentials removed).
- `.env.example` — template for `BASE_URL` / `USERNAME` / `PASSWORD` /
  `ROLE`, loaded via `python-dotenv`. Real `.env` is git-ignored/never
  bundled; credentials are read server-side only and never sent to the
  browser.

**Changed**
- `requirements.txt` — added `playwright` and `python-dotenv`.
- `backend/main.py` — registers the new `scraper` router at
  `/api/scraper`.
- `README.md` — documents the scraper as pipeline step 0, adds the
  one-time `playwright install chromium` setup step and `.env` setup
  instructions, updated project layout tree and CLI examples.

**Not changed**
- The reconciliation pipeline itself (`primary_reconciliation.py`,
  `secondary_name_matcher.py`, `category_merger.py`), the database schema,
  and the Evaluation page are untouched. Manually uploading Abronal
  `.xlsx` files still works exactly as before — the scraper is an optional
  shortcut that populates the same upload folder, not a replacement for
  the upload endpoint.

## v0.1 — Initial release

- Mended SQLite schema (`physicians`, `service_prices` reference tables
  with foreign keys into `abronal_mirror`, `sot_mirror`, `matched_records`,
  `unmatched_records`, `commission_per_physicians`) plus `db_manager.py` as
  the sole database access point.
- Neo-scripts: `primary_reconciliation.py`, `secondary_name_matcher.py`,
  `category_merger.py` (`Condensor`).
- FastAPI backend (`pipeline`, `tables`, `export` routers) and a two-page
  frontend: Intake & Run (upload, run, progress bar, log window) and
  Evaluation (table browser with per-column/date filters, export current
  table or full database history to Excel).
