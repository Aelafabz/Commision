from __future__ import annotations

import sys
from pathlib import Path

from fastapi import APIRouter, Query, Request

APP_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(APP_ROOT / "db"))
import db_manager as dbm  # noqa: E402

router = APIRouter()


@router.get("/list")
def list_tables():
    return {"tables": dbm.TABLES}


@router.get("/{table}/columns")
def columns(table: str):
    return {"columns": dbm.table_columns(table)}


@router.get("/{table}")
def get_table(table: str, request: Request, limit: int = Query(2000, le=20000)):
    # Any query param other than 'limit' is treated as a column filter,
    # e.g. GET /api/tables/matched_records?physician_id=3
    filters = {k: v for k, v in request.query_params.items() if k != "limit"}
    return {"rows": dbm.fetch_table(table, filters=filters or None, limit=limit)}


@router.post("/{table}/filter")
def filter_table(table: str, filters: dict, limit: int = 2000):
    return {"rows": dbm.fetch_table(table, filters=filters, limit=limit)}
