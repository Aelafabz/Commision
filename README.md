# Commission Reconciliation System

A medical-commission reconciliation pipeline that matches **SOT** (Source of Truth) export files against **Abronal** eHealth export files, fuzzy-matches remaining records, and rolls up the results into per-physician commission amounts.

---

## Table of Contents

1. [Overview](#overview)
2. [Architecture](#architecture)
3. [Quickstart](#quickstart)
4. [Workflow](#workflow)
5. [Configuration](#configuration)
6. [API Endpoints](#api-endpoints)
7. [User Guide](#user-guide)
   1. [1. Upload Files](#1-upload-files)
   2. [2. Run Primary Reconciliation](#2-run-primary-reconciliation)
   3. [3. Run Secondary Name Matcher](#3-run-secondary-name-matcher)
   4. [4. Run Category Merger](#4-run-category-merger)
   5. [5. Monitor Progress & Logs](#5-monitor-progress--logs)
8. [Exporting & Evaluation](#exporting--evaluation)
9. [Database Schema](#database-schema)
10. [Troubleshooting](#troubleshooting)

---

## Overview

The system reconciles physician service records from two sources:

| Source | Files | Content |
|--------|---------------|---------|
| **SOT** (Source of Truth) | `.xlsx` | Customer invoices (name, amount, date, service type) |
| **Abronal** | `.xlsx` | eHealth export - contains physician name within the **filename** |

Three headless Python scripts drive the pipeline:

| Script | Purpose |
|--------|----------|
| `scripts/new/primary_reconciliation.py` | Exact-match reconciliation (name+amount+date) |
| `scripts/new/secondary_name_matcher` | Fuzzy name matching for unmatched records |
| `scripts/new/category_merger.py` | Summarizes matched records into commission rows |

All file/directory references are relative to the project root.

---

## [1. Overview] Architecture

```
┌──────────────────┐        ┌──────────────────┐
│   SOT Uploads      │        │  Abronal Uploads  │
│   (uploads/sot/*.xlsx) │        │ (uploads/abronal/*.xlsx) │
└─────────┬────────┘        └─────────┬──────────┘
          │                              │
          ▼                              ▼
┌──────────────────────────────────────────────────────┐
│       scripts/new/primary_reconciliation.py       │
│  · Extract physician name from Abronal filename   │
│  · Exact match on (normalized name, amount, date) │
└──────────────────────────────────────────────────────────┘
                          │
                          │ unmatched
                          ▼
          ┌──────────────────────────────────────────────┐
          │   scripts/new/secondary_name_matcher       │
          │  · Fuzzy name match (threshold, amount, date)│
          └──────────────────────────────────────────┘
                          │
                          ▼
          ┌──────────────────────────────────────────┐
          │  scripts/new/category_merger        │
          │  · Group by (patient, physician)     │
          │  · Sum commission amount by category   │
          │  → commission_per_physicians table     │
          └──────────────────────────────────────────┘
```

---

## [1] Project Structure

```
├── app/
│   ├── main.py                 # FastAPI entry point                          ── 
│   ├── routers/
│   │   ├── reconciliation.py    # Upload + run endpoints      ── 
│   │   └── evaluation.py      # Table browsing / export      ── 
│   ├── services/
│   │   └── pipeline_service.py   # Orchestrates scripts      ── 
│   └── static/
│       ├── index.html               # Reconciliation page      ── 
│       ├── evaluation.html           # Evaluation page      ── 
│       ├── css/style.css
│       └── js/
│           ├── main.js            # Reconciliation page logic      ── 
│           └── evaluation.js        # Evaluation page logic      ── 
├── db/
│   ├── schema.sql                # Full DB schema      ── 
│   ├── init_db.py               # Init/reset DB      ── 
│   └── seed_service_prices.py # Seed from dictionary      ── 
├── configs/
│   └── dictionary.json        # Service → category mapping      ── 
├── uploads/
│   ├── sot/                    # SOT .xlsx files      ── 
│   └── abronal/               # Abronal .xlsx files      ── 
├── scripts/
│   ├── new/
│   │   ├── primary_reconciliation.py
│   │   ├── secondary_name_matcher
│   │   └── category_merger.py
│   └── ...
├── requirements.txt
├── buildplan.txt                 # build guide      ── 
└── README.md                   ← this manual
```

---

## [2] Quickstart

```bash
pip install -r requirements.txt
python -m uvicorn app.main:app --reload
```

Open <http://localhost:8000/> for the reconciliation UI and <http://localhost:8000/evaluation> for the evaluation UI.

---

## [3] Workflow

Run the three scripts in order:

```bash
# 1. Primary reconciliation
python scripts/new/primary_reconciliation.py uploads/sot uploads/abronal
python scripts/new/category_merger.py
```

Each phase reads from and writes to the same `commissions.db` SQLite file.

---

## [4] Configuration

All tunable settings live in `configs/dictionary.json`:

```json
{
  "2 hour post prandial": "Laboratory",
  "service_type": "Other"
}
```

| Key | Purpose |
|-----|---------|
| `physician_skip_list` | Physician names that should never be matched |
| `lookback_days` | Reconciliation window in days |
| `amount_tolerance` | Amount match tolerance (primary) |
| `date_tolerance_days` | Date match tolerance (primary) |
| `confidence_threshold` | Fuzzy-name threshold (secondary) |

---

## [5] API Endpoints

### Reconciliation Router (`/api/reconciliation`)

| Method | Endpoint | Description |
|--------|-----------|-------------|
| POST | `/upload/sot` | Upload one or more SOT `.xlsx` files |
| POST | `/upload/abronal` | Upload one or more Abronal `.xlsx` files |
| GET | `/uploads` | List names of uploaded files |
| POST | `/run/primary` | Start primary reconciliation -> returns `job_id` |
| POST | `/run/secondary` | Start secondary name matching |
| POST | `/run/category-merge` | Start category merger |
| GET | `/status/{job_id}` | SSE stream: progress + logs |
| GET | `/status-poll/{job_id}` | JSON polling endpoint |

### Evaluation Router (`/api/evaluation`)

| Method | Endpoint | Description |
|--------|-----------|-------------|
| GET | `/tables` | List available tables |
| GET | `/data/{table}` | Paginated/filterable table data |
| GET | `/columns/{table}` | Distinct values per column for filter dropdowns |
| GET | `/export/{table}` | Export one table to Excel |
| GET | `/export-all` | Export all tables to one Excel workbook |

---

## [6] User Guide

### [6].1 Upload Reconciliation

Preferences -> Reconciliation:
1. Click **Upload/Upload SOT** and select one-or-more `.xlsx` SOT files.
2. Click **Upload Abronal** and select one-or-more Abronal files.
3. Files will be uploaded to `uploads/sot/` and `uploads/abronal/` and appear as file tags.
4. Click **Run Primary Reconciliation** once both file sets are present.

> Uploaded files are validated by extension (`.xlsx`). File names for Abronal exports MUST contain the physician's name (e.g., `July 20 to July 22 Dr. Ahmed Reja.xlsx`).

### 6.2 Run Primary Reconciliation

- Does exact matching of `std` and `abronal` records:
  - Normalized doctor's full name (from Abronal filename + SOT)
  - Amount
  - Payment date (within tolerance)
- Writes **matched_records** and **unmatched_records**
- Result summary (numbers) is shown on the main page

### 6.3 Run Secondary Name Matcher

For records still unimpaired after primary:

- Fuzzy name comparison (`Threshold = 70 %`, adjustable)
- Additionally checks:
  - Amount tolerance (±)
  - Payment-date proximity (days)
- Writes confirmed matches back into `matched_records`

### 6.4 Run Category Merger

- Steps from `unmatched_records`, groups by `(patient_name, physician_id)`
- Sums per category for each group → writes to **`commission_per_physicians`**

### 6.5 Monitor progress / logs

- The **live log** panel streams progress events from the backend scripts
- **Status badges** display the final result and row count
- **Export page** lets you filter, sort, paginate and export table data

---

## [7] Evaluation & Export Page

Open the **Evaluation** page via the link in the top navigation:

1. Choose a DB table
2. Use **date range** and **column filters**
3. Export to Excel:
   - **Export this table** — current filtered dataset
   - **Export all tables** — all tables into one workbook

---

## [8] Database Schema Summary

| Table | Purpose |
|-------|----------|
| `physicians` | Master physician directory |
| `service_prices` | Catalog service → price/category |
| `sot_mirror` | Raw SOT data |
| `abronal_mirror` | Raw Abronal data |
| `matched_records` | Successful reconciliation |
| `unmatched_records` | Still unmatched / mismatched |
| `commission_per_physicians` | Final aggregated rollup per physician |
| `run_log` | Pipeline execution history |

Key relationships:
- `abronal_mirror.physician_id` → `physicians.id`
- `matched_records.physician_id` → `physicians.id`
- `unmatched_records.physician_id` → `physicians.id`

---

## [9] Troubleshooting

| Symptom | Likely fix |
|----------|-------------|
| `ModuleNotFoundError: No module named 'fastapi'` | `pip install -r requirements.txt` into your virtualenv |
| No tables on evaluation page | Run the app once (creates DB + tables) |
| Driver name won't match | Make sure Abronal export engine driver is in the filename (`Dr. ...`) |
| Secondary threshold ignores params | Ensure configs/dictionary.json is valid JSON + no stray chars |
| Port 8000 already in use | Stop the old server, or run `uvicorn app.main:app --host 0.0.0.0 --port 8001` |
| Uploaded files vanish on server restart | Files are saved to the advanced `uploads/*` - no cleanup in this version |

---

For maintenance notes, API JSON examples, or further development, refer to the source docstrings in the `scripts/new/` module.