READMEDAVE - Developer Test Mode Operations
=========================================

Overview
--------
This project includes a "test mode" to make reconciliation testing easier. When you run the app against a separate database (not the repository default `db/commissions.db`), an interactive Test Mode UI is available at `/testmode`.

Quick start
-----------
1. Create or generate a test dataset. The repo includes a generator:

```bash
python "tests/test file generator/generate_test_data.py" --scenario 1.1
```

This will create `data/test_1_1/test.db` and print a `dev` user password for that test DB.

2. Start the app against that test DB:

```bash
COMMISSIONS_DB=./data/test_1_1 python backend/main.py
```

3. Log in with the `dev` user (password printed by the generator), then open:

- Test UI: http://localhost:8000/testmode

Start with `start.sh` (interactive)
---------------------------------
Instead of manually running the generator and `backend/main.py`, you can use the repository `start.sh` helper which offers an interactive dev flow:

- Run `./start.sh` from the project root. If no `data/test_<scenario>/test.db` exists the script will offer to create one using the built-in generator and will print the created `dev` credentials.
- On success `start.sh` exports `COMMISSIONS_DB` pointed at `data/test_<scenario>/test.db`, launches the server, and attempts to open the app URL in your browser.

Non-interactive / advanced
--------------------------
- To choose a scenario before running `start.sh`, set the `SCENARIO` environment variable, for example:

```bash
SCENARIO=1.2 ./start.sh
```

- Or run the generator and app manually if you prefer:

```bash
python "tests/test file generator/generate_test_data.py" --scenario 1.1
COMMISSIONS_DB=./data/test_1_1 python backend/main.py
```

What the Test UI provides
-------------------------
- A visible TEST MODE banner showing the active DB path.
- Dataset management: load existing `data/test_*` datasets, upload new datasets (SQLite `.db` or `.zip` containing a `test.db`), or generate datasets using the included generator.
- Metrics: quick row counts for important tables.
- Table operations: mass-clear a table (DELETE all rows) and reset DB schema (re-run `init_db()`).

Important safety notes
----------------------
- Test Mode only activates when `COMMISSIONS_DB` does not point to the repository default `db/commissions.db` to reduce the risk of accidental operations on production data.
- Loading a dataset will overwrite the active DB file. Do not point `COMMISSIONS_DB` at production data when using Test Mode.

Advanced
--------
- You can upload zipped exports produced externally, as long as the zip contains `test.db`.
- The generator supports scenarios described in `tests/tests.txt` (1.1, 1.1.1, 1.2, 1.2.1).

CSV-based datasets
-------------------
You can now store test datasets as CSV files under `data/csv_datasets/<name>/` instead of separate SQLite test DBs. The Test Mode UI supports:

- Uploading a single CSV for a specific table (`abronal_mirror`, `sot_mirror`, `matched_records`, `unmatched_records`, `service_prices`, `physicians`).
- Importing all CSV files in a named dataset directory into the active DB (optionally clearing tables first).

Workflow example

1. Prepare CSVs:

```
data/csv_datasets/mycase/abronal_mirror.csv
data/csv_datasets/mycase/sot_mirror.csv
```

2. Start the app against your central test DB:

```bash
COMMISSIONS_DB=./data/commissions_test.db python backend/main.py
```

3. In the Test UI (`/testmode`) upload CSVs or click `Import CSV dataset into DB` for `mycase`.

Notes
- CSV column headers must match the target table's column names (see Admin → Database for exact columns).
- Importing the dataset can clear tables first — use with caution.

Questions or improvements
-------------------------
If you'd like additional test tooling (CSV import UI, scheduled test dataset rotation, or automated scenario-based tests), I can add them next.
