
from __future__ import annotations

import shutil
import subprocess
import zipfile
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Body, UploadFile, File

import auth  # noqa: E402
import db_manager as dbm  # noqa: E402

router = APIRouter(dependencies=[Depends(auth.require_dev)])


def _test_mode_active() -> bool:
    # Only enable the testmode APIs when running against a non-default DB
    default = Path(dbm.DB_DIR) / "commissions.db"
    try:
        return Path(dbm.DB_PATH).resolve() != default.resolve()
    except Exception:
        return True


@router.get("/status")
def status():
    data_dir = Path(__file__).resolve().parents[2] / "data"
    dlist = [str(p.name) for p in sorted(data_dir.glob('test_*')) if p.is_dir()]
    return {
        "active": _test_mode_active(),
        "db_path": str(dbm.DB_PATH),
        "data_test_folders": dlist,
    }


@router.get("/metrics")
def metrics():
    if not _test_mode_active():
        raise HTTPException(status_code=403, detail="Test mode only")
    names = ["abronal_mirror", "sot_mirror", "matched_records", "unmatched_records", "commission_per_physicians"]
    counts = {n: dbm.count_table(n) for n in names}
    return {"counts": counts}


@router.get("/tables")
def tables():
    if not _test_mode_active():
        raise HTTPException(status_code=403, detail="Test mode only")
    tables = []
    for t in dbm.TABLES:
        try:
            c = dbm.count_table(t)
        except Exception:
            c = None
        tables.append({"name": t, "count": c, "columns": dbm.table_columns(t)})
    return {"tables": tables}


@router.post("/clear_table")
def clear_table(payload: dict = Body(...)):
    table = payload.get("table")
    if not _test_mode_active():
        raise HTTPException(status_code=403, detail="Test mode only")
    if table not in dbm.TABLES and table not in dbm.EDITABLE_TABLES:
        raise HTTPException(status_code=400, detail="Unknown table")
    with dbm.get_conn() as conn:
        conn.execute(f"DELETE FROM {table}")
    return {"ok": True}


@router.post("/load_dataset")
def load_dataset(payload: dict = Body(...)):
    folder = payload.get("folder")
    if not _test_mode_active():
        raise HTTPException(status_code=403, detail="Test mode only")
    data_dir = Path(__file__).resolve().parents[2] / "data"
    src = data_dir / folder / "test.db"
    if not src.exists():
        raise HTTPException(status_code=404, detail="Dataset not found")
    # Overwrite current DB file with the test DB
    try:
        shutil.copyfile(str(src), str(dbm.DB_PATH))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e
    return {"ok": True, "db_path": str(dbm.DB_PATH)}


@router.post("/reset_db")
def reset_db():
    if not _test_mode_active():
        raise HTTPException(status_code=403, detail="Test mode only")
    # Reinitialize DB schema in place
    try:
        dbm.init_db()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e
    return {"ok": True}


@router.post("/upload_dataset")
def upload_dataset(name: str = Body(...), file: UploadFile = File(...)):
    """Upload a .db file or a .zip containing a test.db and place it in data/test_<name>/test.db"""
    if not _test_mode_active():
        raise HTTPException(status_code=403, detail="Test mode only")
    data_dir = Path(__file__).resolve().parents[2] / "data"
    dest_dir = data_dir / f"test_{name}"
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest_path = dest_dir / "test.db"
    try:
        content = file.file.read()
        if file.filename.endswith('.zip'):
            # write to temp zip and extract
            tmp = dest_dir / 'upload_tmp.zip'
            tmp.write_bytes(content)
            with zipfile.ZipFile(tmp, 'r') as z:
                z.extractall(dest_dir)
            tmp.unlink()
            # look for test.db inside dest_dir
            candidate = None
            for p in dest_dir.rglob('test.db'):
                candidate = p
                break
            if candidate:
                shutil.copyfile(str(candidate), str(dest_path))
        else:
            # assume sqlite db file
            dest_path.write_bytes(content)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e
    return {"ok": True, "dataset": str(dest_path)}


@router.post("/generate")
def generate_scenario(payload: dict = Body(...)):
    """Run the generator script to create a dataset for scenario e.g. '1.1'"""
    if not _test_mode_active():
        raise HTTPException(status_code=403, detail="Test mode only")
    scenario = payload.get('scenario')
    if not scenario:
        raise HTTPException(status_code=400, detail="scenario required")
    gen_script = Path(__file__).resolve().parents[2] / 'tests' / 'test file generator' / 'generate_test_data.py'
    if not gen_script.exists():
        raise HTTPException(status_code=500, detail="generator script not found")
    try:
        completed = subprocess.run(["python", str(gen_script), "--scenario", scenario], capture_output=True, text=True, check=True)
    except subprocess.CalledProcessError as e:
        raise HTTPException(status_code=500, detail=e.stderr or e.stdout or str(e)) from e
    return {"ok": True, "stdout": completed.stdout}


@router.post("/upload_csv")
def upload_csv(table: str = Body(...), name: str = Body(...), file: UploadFile = File(...)):
    """Upload a CSV for `table` and store it under data/csv_datasets/<name>/<table>.csv"""
    if not _test_mode_active():
        raise HTTPException(status_code=403, detail="Test mode only")
    data_dir = Path(__file__).resolve().parents[2] / "data" / "csv_datasets" / name
    data_dir.mkdir(parents=True, exist_ok=True)
    dest = data_dir / f"{table}.csv"
    try:
        content = file.file.read()
        dest.write_bytes(content)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e
    return {"ok": True, "path": str(dest)}


@router.post("/import_csv_dataset")
def import_csv_dataset(payload: dict = Body(...)):
    """Import CSV files from data/csv_datasets/<name>/ into the active DB.

    Payload: { name: 'dataset_name', clear_first: true }
    """
    if not _test_mode_active():
        raise HTTPException(status_code=403, detail="Test mode only")
    name = payload.get("name")
    clear_first = bool(payload.get("clear_first", True))
    if not name:
        raise HTTPException(status_code=400, detail="name required")
    base = Path(__file__).resolve().parents[2] / "data" / "csv_datasets" / name
    if not base.exists():
        raise HTTPException(status_code=404, detail="dataset not found")
    imported = {}
    try:
        with dbm.get_conn() as conn:
            for csv_path in sorted(base.glob('*.csv')):
                table = csv_path.stem
                cols = dbm.table_columns(table) if table in dbm.EDITABLE_TABLES else None
                if cols is None:
                    # skip unknown tables
                    imported[table] = "skipped: unknown table"
                    continue
                import csv
                rows = []
                with csv_path.open('r', encoding='utf-8') as fh:
                    reader = csv.DictReader(fh)
                    for r in reader:
                        # keep only known columns
                        filtered = {k: (v if v != '' else None) for k, v in r.items() if k in cols}
                        rows.append(filtered)
                if clear_first:
                    conn.execute(f"DELETE FROM {table}")
                if rows:
                    placeholders = ','.join('?' for _ in rows[0])
                    col_names = ','.join(f'"{c}"' for c in rows[0].keys())
                    sql = f'INSERT INTO "{table}" ({col_names}) VALUES ({placeholders})'
                    for row in rows:
                        conn.execute(sql, list(row.values()))
                imported[table] = len(rows)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e
    return {"ok": True, "imported": imported}
