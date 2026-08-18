# Commission Reconciliation App

A toolkit for reconciling physician commission data between Abronal exports and Source-of-Truth (SoT) Excel files. The project supports two independent run modes: a **legacy Tkinter GUI** and a **modern web-based interface** powered by FastAPI.

---

## Data Flow

```
Abronal Excel exports
        │
        ▼
  Primary Reconciliation  ──────────────────────────────┐
  (exact name + service match)                          │
        │                                               │
   ┌────┴────┐                                          │
   │Matched  │  Unmatched                               │
   │Records  │──► Secondary Name Matcher                │
   │         │    (fuzzy name + date ± 1 day)           │
   └────┬────┘          │                               │
        │         Grafted matches                       │
        ▼               │                               │
  Category Merger ◄─────┘                              │
  (collapse services → Laboratory, Ultrasound, etc.)   │
        │                                               │
        ▼                                               │
  Commission Summary → SQLite DB ◄────────────────────-┘
```

---

## Output Files

| File | Description |
|---|---|
| `Perfect Matches.xlsx` | Exact-match rows |
| `Unmatched_Analysis.xlsx` | Rows that could not be reconciled |
| `Blind_Matches.xlsx` | Fuzzy secondary matches |
| `Nameless_SoT_Records.xlsx` | SoT rows with no patient name |
| `Service_Summary_Report.xlsx` | Per-patient service pivot |
| `Commission_Summary.xlsx` | Final physician totals + commission |

---

## Key Scripts

### Legacy (Tkinter GUI)

| Script | Purpose |
|---|---|
| `scripts/reconciliation_app_v5.py` | All-in-one Tkinter GUI: loads files, runs matching, fuzzy review, and writes all output workbooks |
| `scripts/service_analyzer.py` | Tkinter UI for service categorisation and category-based pivot summaries |
| `scripts/category_merger.py` | `Condensor` class — collapses services into dictionary categories |
| `scripts/export_physician_performance.py` | Standalone export automation (not required for reconciliation) |

### New (Web / API)

| Script | Purpose |
|---|---|
| `scripts/pipeline.py` | Headless pipeline: primary recon → secondary matcher → category merger |
| `scripts/primary_recon.py` | Primary reconciliation logic (imported by pipeline) |
| `scripts/secondary_recon.py` | Fuzzy name-matching logic (imported by pipeline) |
| `server/app/main.py` | FastAPI backend — serves the web UI and exposes the REST API |
| `server/app/routes/pipeline.py` | `POST /api/pipeline/run` — triggers the headless pipeline as a background job |
| `server/app/routes/export.py` | `POST /api/export/run` — triggers the physician-performance export |
| `server/app/routes/records.py` | `GET/POST /api/records` — stored commission records |
| `Frontend/index.html` | Single-page web UI |

---

## How to Run

### Prerequisites

Install dependencies with [uv](https://github.com/astral-sh/uv) (recommended) or pip:

```bash
# uv (recommended)
uv sync

# pip
pip install -r server/requirements.txt
```

---

### Pathway 1 — Legacy Tkinter GUI

Run the all-in-one reconciliation desktop app:

```bash
python scripts/reconciliation_app_v5.py
```

Then, inside the GUI:
1. Choose the **Abronal input folder**
2. Choose the **SoT input folder**
3. Choose an **Output folder**

Run the standalone service analyser:

```bash
python scripts/service_analyzer.py
```

---

### Pathway 2 — Web Interface (FastAPI + Browser)

Start the backend server:

```bash
uvicorn server.app.main:app --reload --port 8000
```

Then open [http://localhost:8000](http://localhost:8000) in your browser.

The web UI allows you to:
- **Run the reconciliation pipeline** by entering the Abronal folder, SoT folder, and a date label
- **Trigger physician-performance exports** with a date range and physician filter
- **Browse stored commission records** from the database
- **Stream pipeline logs** in real time

Or use the Makefile shortcuts:

```bash
make help         # show all available commands
make server       # start FastAPI server (dev, port 8000)
make server-prod  # start FastAPI server (no reload)
make legacy       # launch Tkinter reconciliation GUI
make analyzer     # launch Tkinter service analyser
make install      # install dependencies via uv
make install-pip  # install dependencies via pip
make db-init      # ensure database/ directory exists
make clean        # remove __pycache__ directories
```

---

## Database

- **Path**: `database/commission.db` (SQLite)
- **Table**: `records`
- **Columns**: `id`, `doctor_name`, `service`, `amount`, `category`, `date`

The database is created automatically on first server start, and records are appended after each successful pipeline run.

---

## Configuration

| File | Purpose |
|---|---|
| `configs/dictionary.json` | Maps service names → categories (Laboratory, Ultrasound, X-ray, Nursing & Procedures, Consultation) |
| `configs/config.json` | Exporter and scraper configuration |
| `.env` | Environment secrets (API keys, credentials) |

---

## Notes

- Run either pathway independently — they share the same `database/commission.db` and `configs/dictionary.json`.
- `scripts/export_physician_performance.py` is a separate automation script and is not required for the core reconciliation flow.
- For multi-worker deployments, the in-memory job store in `server/app/routes/pipeline.py` should be replaced with a Redis-backed queue.
