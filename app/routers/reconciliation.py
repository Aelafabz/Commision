from __future__ import annotations

import asyncio
import json
import shutil
import uuid
from pathlib import Path
from typing import AsyncGenerator

from fastapi import APIRouter, BackgroundTasks, File, HTTPException, UploadFile
from fastapi.responses import JSONResponse, StreamingResponse

from app.services.pipeline_service import PipelineService

router = APIRouter()

BASE_DIR = Path(__file__).resolve().parent.parent.parent
UPLOAD_DIR = BASE_DIR / "uploads"
UPLOAD_DIR.mkdir(exist_ok=True)
(UPLOAD_DIR / "sot").mkdir(exist_ok=True)
(UPLOAD_DIR / "abronal").mkdir(exist_ok=True)

# In-memory job store: {job_id: {"logs": [], "progress": int, "status": str}}
_jobs: dict[str, dict] = {}


def _get_job(job_id: str) -> dict:
    if job_id not in _jobs:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")
    return _jobs[job_id]


def _make_progress_cb(job_id: str):
    """Returns a progress callback that updates the in-memory job store."""
    def cb(step: str, pct: int, msg: str):
        if job_id in _jobs:
            _jobs[job_id]["logs"].append(f"[{step.upper()}] {msg}")
            if pct >= 0:
                _jobs[job_id]["progress"] = pct
    return cb


# ── Upload endpoints ──────────────────────────────────────────────────

@router.post("/upload/sot", summary="Upload SOT Excel files")
async def upload_sot(files: list[UploadFile] = File(...)):
    """Upload one or more SOT (Source of Truth) Excel files."""
    saved = []
    # Clear previous uploads
    sot_dir = UPLOAD_DIR / "sot"
    for old_file in sot_dir.glob("*.xlsx"):
        old_file.unlink()
    for file in files:
        if not file.filename.endswith(".xlsx"):
            raise HTTPException(status_code=400, detail=f"Only .xlsx files accepted: {file.filename}")
        dest = sot_dir / file.filename
        with open(dest, "wb") as f:
            shutil.copyfileobj(file.file, f)
        saved.append(file.filename)
    return {"uploaded": saved, "count": len(saved)}


@router.post("/upload/abronal", summary="Upload Abronal Excel files")
async def upload_abronal(files: list[UploadFile] = File(...)):
    """Upload one or more Abronal export Excel files."""
    saved = []
    abr_dir = UPLOAD_DIR / "abronal"
    for old_file in abr_dir.glob("*.xlsx"):
        old_file.unlink()
    for file in files:
        if not file.filename.endswith(".xlsx"):
            raise HTTPException(status_code=400, detail=f"Only .xlsx files accepted: {file.filename}")
        dest = abr_dir / file.filename
        with open(dest, "wb") as f:
            shutil.copyfileobj(file.file, f)
        saved.append(file.filename)
    return {"uploaded": saved, "count": len(saved)}


@router.get("/uploads", summary="List uploaded files")
async def list_uploads():
    sot = [f.name for f in (UPLOAD_DIR / "sot").glob("*.xlsx")]
    abr = [f.name for f in (UPLOAD_DIR / "abronal").glob("*.xlsx")]
    return {"sot": sot, "abronal": abr}


# ── Pipeline run endpoints ────────────────────────────────────────────

@router.post("/run/primary", summary="Run primary reconciliation")
async def run_primary(background_tasks: BackgroundTasks):
    """Trigger the primary reconciliation pipeline. Returns a job_id for SSE monitoring."""
    abr_dir = UPLOAD_DIR / "abronal"
    sot_dir = UPLOAD_DIR / "sot"
    abr_files = list(abr_dir.glob("*.xlsx"))
    sot_files = list(sot_dir.glob("*.xlsx"))

    if not abr_files:
        raise HTTPException(status_code=400, detail="No Abronal files uploaded. Upload files first.")
    if not sot_files:
        raise HTTPException(status_code=400, detail="No SOT files uploaded. Upload files first.")

    job_id = str(uuid.uuid4())
    _jobs[job_id] = {"logs": [], "progress": 0, "status": "running", "result": None}

    def run_in_bg():
        import sys
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
        from scripts.new.primary_reconciliation import run_reconciliation
        cb = _make_progress_cb(job_id)
        try:
            result = run_reconciliation(abr_dir, sot_dir, cb)
            _jobs[job_id]["status"] = "done"
            _jobs[job_id]["result"] = result
        except Exception as e:
            _jobs[job_id]["status"] = "error"
            _jobs[job_id]["logs"].append(f"[ERROR] {e}")

    background_tasks.add_task(run_in_bg)
    return {"job_id": job_id, "status": "started"}


@router.post("/run/secondary", summary="Run secondary name matcher")
async def run_secondary(
    background_tasks: BackgroundTasks,
    confidence: float = 0.70,
    amount_tolerance: float = 1.0,
    date_tolerance_days: int = 1,
):
    """Trigger secondary name matching. Returns a job_id."""
    job_id = str(uuid.uuid4())
    _jobs[job_id] = {"logs": [], "progress": 0, "status": "running", "result": None}

    def run_in_bg():
        import sys
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
        from scripts.new.secondary_name_matcher import run_secondary_matching
        cb = _make_progress_cb(job_id)
        try:
            result = run_secondary_matching(cb, confidence, amount_tolerance, date_tolerance_days)
            _jobs[job_id]["status"] = "done"
            _jobs[job_id]["result"] = result
        except Exception as e:
            _jobs[job_id]["status"] = "error"
            _jobs[job_id]["logs"].append(f"[ERROR] {e}")

    background_tasks.add_task(run_in_bg)
    return {"job_id": job_id, "status": "started"}


@router.post("/run/category-merge", summary="Run category merger")
async def run_category_merge(
    background_tasks: BackgroundTasks,
    period_start: str | None = None,
    period_end: str | None = None,
):
    """Trigger the category merger. Returns a job_id."""
    job_id = str(uuid.uuid4())
    _jobs[job_id] = {"logs": [], "progress": 0, "status": "running", "result": None}

    def run_in_bg():
        import sys
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
        from scripts.new.category_merger import run_category_merge
        cb = _make_progress_cb(job_id)
        try:
            result = run_category_merge(cb, period_start, period_end)
            _jobs[job_id]["status"] = "done"
            _jobs[job_id]["result"] = result
        except Exception as e:
            _jobs[job_id]["status"] = "error"
            _jobs[job_id]["logs"].append(f"[ERROR] {e}")

    background_tasks.add_task(run_in_bg)
    return {"job_id": job_id, "status": "started"}


# ── SSE progress stream ─────────────────────────────────────────────────

@router.get("/status/{job_id}", summary="SSE stream for job progress")
async def job_status_stream(job_id: str):
    """
    Server-Sent Events stream. Yields progress events until job is done or errored.
    """
    async def event_generator() -> AsyncGenerator[str, None]:
        last_log_idx = 0
        while True:
            if job_id not in _jobs:
                yield f"data: {json.dumps({'error': 'Job not found'})}\n\n"
                break

            job = _jobs[job_id]
            new_logs = job["logs"][last_log_idx:]
            last_log_idx = len(job["logs"])

            payload = {
                "progress": job["progress"],
                "status": job["status"],
                "logs": new_logs,
                "result": job.get("result"),
            }
            yield f"data: {json.dumps(payload)}\n\n"

            if job["status"] in ("done", "error"):
                break

            await asyncio.sleep(0.5)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/status-poll/{job_id}", summary="Poll job status (non-SSE)")
async def poll_status(job_id: str):
    """Simple poll endpoint for environments where SSE is not available."""
    job = _get_job(job_id)
    return {
        "progress": job["progress"],
        "status": job["status"],
        "logs": job["logs"],
        "result": job.get("result"),
    }
