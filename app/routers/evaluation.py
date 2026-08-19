from __future__ import annotations

import io
import sqlite3
from pathlib import Path
from typing import Any

import pandas as pd
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse

router = APIRouter()

DB_PATH = Path(__file__).resolve().parent.parent.parent / "database" / "commissions.db"

# Tables available for evaluation (order matters for display)
AVAILABLE_TABLES = [
    "commission_per_physicians",
    "matched_records",
    "unmatched_records",
    "physicians",
    "service_prices",
    "sot_mirror",
    "abronal_mirror",
]


def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


@router.get("/tables", summary="List available DB tables")
async def list_tables():
    """Returns the list of tables available for evaluation."""
    return {"tables": AVAILABLE_TABLES}


@router.get("/data/{table}", summary="Get table data with optional filters")
async def get_table_data(
    table: str,
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(100, ge=1, le=1000, description="Rows per page"),
    date_start: str | None = Query(None, description="Filter by date >= (YYYY-MM-DD)"),
    date_end: str | None = Query(None, description="Filter by date <= (YYYY-MM-DD)"),
    filters: str | None = Query(None, description='JSON string of {column: value} filters'),
):
    """
    Fetch paginated data from a DB table.
    Supports column-value filters and date range filters.
    """
    if table not in AVAILABLE_TABLES:
        raise HTTPException(status_code=400, detail=f"Table '{table}' is not available")

    conn = get_conn()
    try:
        # Get column names first
        cur = conn.execute(f"SELECT * FROM {table} LIMIT 1")
        cols = [desc[0] for desc in cur.description] if cur.description else []

        # Build query with filters
        conditions = []
        params: list[Any] = []

        # Date range: find date-like column
        date_col = next(
            (c for c in cols if 'date' in c.lower() or 'period' in c.lower()),
            None
        )
        if date_col and date_start:
            conditions.append(f"{date_col} >= ?")
            params.append(date_start)
        if date_col and date_end:
            conditions.append(f"{date_col} <= ?")
            params.append(date_end)

        # Column value filters
        if filters:
            import json
            try:
                filter_dict = json.loads(filters)
                for col, val in filter_dict.items():
                    if col in cols and val:
                        conditions.append(f"{col} LIKE ?")
                        params.append(f"%{val}%")
            except json.JSONDecodeError:
                pass

        where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        offset = (page - 1) * page_size

        # Count total rows
        count_sql = f"SELECT COUNT(*) FROM {table} {where_clause}"
        total = conn.execute(count_sql, params).fetchone()[0]

        # Fetch page
        data_sql = f"SELECT * FROM {table} {where_clause} LIMIT ? OFFSET ?"
        rows = conn.execute(data_sql, params + [page_size, offset]).fetchall()
        data = [dict(row) for row in rows]

    finally:
        conn.close()

    return {
        "table": table,
        "columns": cols,
        "data": data,
        "page": page,
        "page_size": page_size,
        "total": total,
        "total_pages": (total + page_size - 1) // page_size,
    }


@router.get("/columns/{table}", summary="Get distinct values per column for filter dropdowns")
async def get_column_values(table: str):
    """
    Returns distinct values for each column in the table.
    Used to populate filter dropdowns in the UI.
    """
    if table not in AVAILABLE_TABLES:
        raise HTTPException(status_code=400, detail=f"Table '{table}' is not available")

    conn = get_conn()
    try:
        cur = conn.execute(f"SELECT * FROM {table} LIMIT 1")
        if not cur.description:
            return {"table": table, "columns": {}}
        cols = [desc[0] for desc in cur.description]
        result = {}
        for col in cols:
            try:
                vals = conn.execute(
                    f"SELECT DISTINCT {col} FROM {table} WHERE {col} IS NOT NULL ORDER BY {col} LIMIT 200").fetchall()
                result[col] = [row[0] for row in vals]
            except Exception:
                result[col] = []
    finally:
        conn.close()

    return {"table": table, "columns": result}


@router.get("/export/{table}", summary="Export a table to Excel")
async def export_table(
    table: str,
    date_start: str | None = Query(None),
    date_end: str | None = Query(None),
    filters: str | None = Query(None),
):
    """Export the selected table (with optional filters) as an Excel file."""
    if table not in AVAILABLE_TABLES:
        raise HTTPException(status_code=400, detail=f"Table '{table}' is not available")

    conn = get_conn()
    try:
        cur = conn.execute(f"SELECT * FROM {table} LIMIT 1")
        cols = [desc[0] for desc in cur.description] if cur.description else []

        conditions, params = [], []
        date_col = next((c for c in cols if 'date' in c.lower()), None)
        if date_col and date_start:
            conditions.append(f"{date_col} >= ?")
            params.append(date_start)
        if date_col and date_end:
            conditions.append(f"{date_col} <= ?")
            params.append(date_end)
        if filters:
            import json
            try:
                for col, val in json.loads(filters).items():
                    if col in cols and val:
                        conditions.append(f"{col} LIKE ?")
                        params.append(f"%{val}%")
            except Exception:
                pass

        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        df = pd.read_sql_query(f"SELECT * FROM {table} {where}", conn, params=params)
    finally:
        conn.close()

    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine='openpyxl') as writer:
        df.to_excel(writer, sheet_name=table[:31], index=False)
    buffer.seek(0)

    return StreamingResponse(
        buffer,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename={table}_export.xlsx"},
    )


@router.get("/export-all", summary="Export all tables to a single Excel workbook")
async def export_all(
    date_start: str | None = Query(None),
    date_end: str | None = Query(None),
):
    """Export all available tables into a single multi-sheet Excel workbook."""
    conn = get_conn()
    buffer = io.BytesIO()

    try:
        with pd.ExcelWriter(buffer, engine='openpyxl') as writer:
            for table in AVAILABLE_TABLES:
                try:
                    cur = conn.execute(f"SELECT * FROM {table} LIMIT 1")
                    if not cur.description:
                        continue
                    cols = [desc[0] for desc in cur.description]
                    conditions, params = [], []
                    date_col = next((c for c in cols if 'date' in c.lower()), None)
                    if date_col and date_start:
                        conditions.append(f"{date_col} >= ?")
                        params.append(date_start)
                    if date_col and date_end:
                        conditions.append(f"{date_col} <= ?")
                        params.append(date_end)
                    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
                    df = pd.read_sql_query(f"SELECT * FROM {table} {where}", conn, params=params)
                    df.to_excel(writer, sheet_name=table[:31], index=False)
                except Exception:
                    pass
    finally:
        conn.close()

    buffer.seek(0)
    return StreamingResponse(
        buffer,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename=all_tables_export.xlsx"},
    )
