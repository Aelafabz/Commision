from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response
from fastapi import Body

from .pipeline import _default_db_path

router = APIRouter(prefix="/db", tags=["database"])


def _connect_db() -> sqlite3.Connection:
    db = str(_default_db_path())
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    return conn


@router.get("/tables")
def list_tables() -> dict:
    try:
        conn = _connect_db()
        cur = conn.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
        tables = [r[0] for r in cur.fetchall()]
        counts = {}
        for t in tables:
            try:
                c = conn.execute(f"SELECT COUNT(*) as c FROM '{t}'").fetchone()[0]
            except Exception:
                c = None
            counts[t] = c
        return {"tables": tables, "counts": counts}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/tables/{table_name}")
def inspect_table(table_name: str, limit: int = 50) -> dict[str, Any]:
    try:
        conn = _connect_db()
        # columns
        cur = conn.execute(f"PRAGMA table_info('{table_name}')")
        cols = [dict(r) for r in cur.fetchall()]
        # sample rows
        cur = conn.execute(f"SELECT * FROM '{table_name}' LIMIT ?", (limit,))
        rows = [dict(r) for r in cur.fetchall()]
        return {"columns": cols, "rows": rows}
    except sqlite3.OperationalError as oe:
        raise HTTPException(status_code=404, detail=str(oe))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.get('/export/table/{table_name}')
def export_table_csv(table_name: str):
    """Export entire table as CSV."""
    try:
        conn = sqlite3.connect(str(_default_db_path()))
        cur = conn.execute(f"SELECT * FROM '{table_name}'")
        rows = cur.fetchall()
        cols = [d[0] for d in cur.description]
        import io, csv
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(cols)
        for r in rows:
            writer.writerow([r[c] for c in cols])
            return Response(content=buf.getvalue(), media_type='text/csv')
    except sqlite3.OperationalError as oe:
        raise HTTPException(status_code=404, detail=str(oe))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.get('/export/doctor')
def export_doctor_csv(doctor: str, from_date: str | None = None, to_date: str | None = None):
    """Export records for a doctor in a date range as CSV."""
    try:
        conn = sqlite3.connect(str(_default_db_path()))
        params = [doctor]
        q = "SELECT * FROM records WHERE doctor_name = ?"
        if from_date and to_date:
            q = "SELECT * FROM records WHERE doctor_name = ? AND DATE(date) BETWEEN DATE(?) AND DATE(?)"
            params = [doctor, from_date, to_date]
        elif from_date:
            q = "SELECT * FROM records WHERE doctor_name = ? AND DATE(date) >= DATE(?)"
            params = [doctor, from_date]
        cur = conn.execute(q, params)
        rows = cur.fetchall()
        cols = [d[0] for d in cur.description]
        import io, csv
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(cols)
        for r in rows:
            writer.writerow([r[c] for c in cols])
        return Response(content=buf.getvalue(), media_type='text/csv')
    except sqlite3.OperationalError as oe:
        raise HTTPException(status_code=404, detail=str(oe))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.post('/import/records')
def import_records(records: list[dict] = Body(...), overwrite: bool = False) -> dict:
    """Import a list of records (JSON) into the `records` table.

    Each record should be a dict with keys: doctor_name, service, amount, category, date
    """
    try:
        conn = _connect_db()
        cur = conn.cursor()
        inserted = 0
        # detect overlaps: group incoming records by doctor and date range
        grouped = {}
        for r in records:
            doctor = r.get('doctor_name') or r.get('doctor') or ''
            date = r.get('date') or None
            if doctor not in grouped:
                grouped[doctor] = {'min': None, 'max': None, 'rows': []}
            grouped[doctor]['rows'].append(r)
            try:
                d = date
                if d is not None:
                    # normalize via sqlite date handling — string compare OK for ISO
                    if grouped[doctor]['min'] is None or str(d) < str(grouped[doctor]['min']):
                        grouped[doctor]['min'] = d
                    if grouped[doctor]['max'] is None or str(d) > str(grouped[doctor]['max']):
                        grouped[doctor]['max'] = d
            except Exception:
                pass

        overlaps = []
        for doctor, info in grouped.items():
            if info['min'] is None or info['max'] is None:
                continue
            cur = conn.execute("SELECT COUNT(*) as c, MIN(date) as min_date, MAX(date) as max_date FROM records WHERE doctor_name = ? AND DATE(date) BETWEEN DATE(?) AND DATE(?)",
                               (doctor, str(info['min']), str(info['max'])))
            row = cur.fetchone()
            try:
                c = row[0]
            except Exception:
                c = 0
            if c and int(c) > 0:
                overlaps.append({'doctor': doctor, 'existing_count': int(c), 'existing_min_date': row[1], 'existing_max_date': row[2], 'incoming_min_date': str(info['min']), 'incoming_max_date': str(info['max'])})

        if overlaps and not overwrite:
            # inform caller about overlaps and do not perform insertion
            raise HTTPException(status_code=409, detail={'type': 'overlap', 'overlaps': overlaps})

        # if overwrite is requested, delete overlapping rows
        if overlaps and overwrite:
            for o in overlaps:
                conn.execute("DELETE FROM records WHERE doctor_name = ? AND DATE(date) BETWEEN DATE(?) AND DATE(?)",
                             (o['doctor'], o['incoming_min_date'], o['incoming_max_date']))
            conn.commit()

        # insert records
        for r in records:
            doctor = r.get('doctor_name') or r.get('doctor') or ''
            service = r.get('service') or ''
            amount = r.get('amount') or 0
            category = r.get('category') or ''
            date = r.get('date') or None
            # avoid inserting exact duplicates
            cur = conn.execute("SELECT COUNT(*) FROM records WHERE doctor_name = ? AND service = ? AND amount = ? AND category = ? AND DATE(date)=DATE(?)",
                               (doctor, service, amount, category, date))
            if cur.fetchone()[0] > 0:
                continue
            cur = conn.execute("INSERT INTO records (doctor_name, service, amount, category, date) VALUES (?,?,?,?,?)",
                        (doctor, service, amount, category, date))
            inserted += 1
        conn.commit()
        return {'inserted': inserted, 'overlaps': overlaps}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/doctor_summary")
def doctor_summary() -> dict:
    """Return latest-date summary aggregated by doctor, including commission amounts.

    Commission rates are read from configs/commisions.json as a mapping
    { "Doctor Name": 0.10, ... }. Missing entries use a default rate.
    """
    import json
    from pathlib import Path

    DEFAULT_RATE = 0.10
    db_path = str(_default_db_path())
    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.execute("SELECT MAX(date) as latest FROM records")
        row = cur.fetchone()
        if not row or row[0] is None:
            return {"date": None, "summary": []}
        latest = row[0]

        # aggregate totals per doctor for the latest date (same calendar day)
        q = """
        SELECT doctor_name, SUM(amount) AS total, COUNT(*) AS count
        FROM records
        WHERE DATE(date) = DATE(?)
        GROUP BY doctor_name
        ORDER BY total DESC
        """
        cur = conn.execute(q, (latest,))
        doctors = [dict(r) for r in cur.fetchall()]

        # load commission mapping
        repo_root = Path(__file__).resolve().parents[3]
        comm_path = repo_root / "configs" / "commisions.json"
        commissions = {}
        try:
            with comm_path.open('r', encoding='utf-8') as cf:
                commissions = json.load(cf) or {}
        except Exception:
            commissions = {}

        summary = []
        for d in doctors:
            name = d['doctor_name']
            rate = commissions.get(name) or commissions.get(name.lower()) or DEFAULT_RATE
            try:
                rate = float(rate)
            except Exception:
                rate = DEFAULT_RATE

            # category breakdown
            cur = conn.execute(
                "SELECT category, SUM(amount) AS total FROM records WHERE DATE(date)=DATE(?) AND doctor_name=? GROUP BY category",
                (latest, name),
            )
            categories = [dict(r) for r in cur.fetchall()]

            commission_amount = d['total'] * rate
            summary.append({
                'doctor_name': name,
                'total': d['total'],
                'count': d['count'],
                'commission_rate': rate,
                'commission_amount': commission_amount,
                'categories': categories,
            })

        return {"date": latest, "summary": summary}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
