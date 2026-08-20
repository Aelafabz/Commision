from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

import pandas as pd
from fastapi import APIRouter, Body
from fastapi.responses import FileResponse

APP_ROOT = Path(__file__).resolve().parents[2]
EXPORT_DIR = APP_ROOT / "exports"
EXPORT_DIR.mkdir(parents=True, exist_ok=True)

sys.path.insert(0, str(APP_ROOT / "db"))
import db_manager as dbm  # noqa: E402

router = APIRouter()

DATE_COLUMNS = {
    "abronal_mirror": "payment_date",
    "sot_mirror": "transaction_date",
    "matched_records": "payment_date",
    "unmatched_records": "abronal_payment_date",
    "commission_per_physicians": "payment_date",
}


def _filtered_frame(table: str, filters: dict | None, start_date: str | None, end_date: str | None):
    rows = dbm.fetch_table(table, filters=filters, limit=200000)
    df = pd.DataFrame(rows)
    date_col = DATE_COLUMNS.get(table)
    if date_col and date_col in df.columns and (start_date or end_date):
        parsed = pd.to_datetime(df[date_col], errors="coerce")
        if start_date:
            df = df[parsed >= pd.to_datetime(start_date)]
            parsed = pd.to_datetime(df[date_col], errors="coerce")
        if end_date:
            df = df[parsed <= pd.to_datetime(end_date)]
    return df


@router.post("/table/{table}")
def export_table(table: str, payload: dict = Body(default={})):
    """Export one table to xlsx, optionally filtered by column values
    and/or a date range on that table's natural date column."""
    filters = payload.get("filters")
    start_date = payload.get("start_date")
    end_date = payload.get("end_date")

    df = _filtered_frame(table, filters, start_date, end_date)
    fname = f"{table}_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.xlsx"
    path = EXPORT_DIR / fname
    df.to_excel(path, index=False, sheet_name=table[:31])
    return FileResponse(path, filename=fname,
                         media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


@router.post("/all")
def export_all(payload: dict = Body(default={})):
    """Export the full database history: every table on its own sheet."""
    start_date = payload.get("start_date")
    end_date = payload.get("end_date")

    fname = f"database_history_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.xlsx"
    path = EXPORT_DIR / fname
    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        for table in dbm.TABLES:
            df = _filtered_frame(table, None, start_date, end_date)
            if df.empty:
                df = pd.DataFrame(columns=dbm.table_columns(table))
            df.to_excel(writer, index=False, sheet_name=table[:31])
    return FileResponse(path, filename=fname,
                         media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
