from __future__ import annotations

import sys
import threading
import uuid
from datetime import datetime
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, BackgroundTasks, HTTPException

from ..schemas import (
    PipelineResultsResponse,
    PipelineRunRequest,
    PipelineRunResponse,
    PipelineStatusResponse,
)

router = APIRouter(prefix="/pipeline", tags=["pipeline"])


def _repo_root() -> Path:
    # server/app/routes/pipeline.py -> routes -> app -> server -> repo root
    return Path(__file__).resolve().parents[3]


def _scripts_dir() -> Path:
    return _repo_root() / "scripts"


def _default_db_path() -> Path:
    return _repo_root() / "database" / "commission.db"


def _default_dictionary_path() -> Path:
    return _repo_root() / "configs" / "dictionary.json"


# In-memory job store. Fine for a single-worker deployment; if you ever run
# uvicorn with --workers > 1, move this to the database or a shared cache
# (e.g. redis) since each worker process would otherwise have its own copy.
_jobs: dict[str, dict] = {}
_jobs_lock = threading.Lock()

JobStatus = Literal["queued", "running", "done", "error"]


def _set_job(run_id: str, **fields) -> None:
    with _jobs_lock:
        _jobs[run_id].update(fields)


def _append_log(run_id: str, message: str) -> None:
    with _jobs_lock:
        _jobs[run_id]["log"].append(message)


def _execute_pipeline(run_id: str, payload: PipelineRunRequest) -> None:
    scripts_dir = str(_scripts_dir())
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)

    _set_job(run_id, status="running", started_at=datetime.utcnow().isoformat())
    try:
        from pipeline import run_pipeline  # imported lazily so sys.path is set first

        db_path = payload.db_path or str(_default_db_path())
        dictionary_path = payload.dictionary_path or str(_default_dictionary_path())

        tables = run_pipeline(
            abr_dir=payload.abr_dir,
            sot_dir=payload.sot_dir,
            dictionary_path=dictionary_path,
            db_path=db_path,
            date_label=payload.date_label or "",
            commission_rate=payload.commission_rate,
            name_match_confidence=payload.name_match_confidence,
            date_window_days=payload.date_window_days,
            log_fn=lambda msg: _append_log(run_id, msg),
        )

        summary_df = tables["commission_summary"]
        perfect_df """0..1 similarity: character similarity, boosted by word-subset overlap.""" = tables["perfect_matches"]
        mismatch_df = tables["unmatched"]

        _set_job(
            run_id,
            status="done",
            finished_at=datetime.utcnow().isoformat(),
            db_path=db_path,
            commission_summary=summary_df.to_dict(orient="records"),
            perfect_match_count=int(len(perfect_df)),
            mismatch_count=int(len(mismatch_df)),
        )
    except Exception as exc:  # noqa: BLE001
        _append_log(run_id, f"ERROR: {exc}")
        _set_job(run_id, status="error", finished_at=datetime.utcnow().isoformat(), error=str(exc))


@router.post("/run", response_model=PipelineRunResponse)
def start_pipeline(payload: PipelineRunRequest, background_tasks: BackgroundTasks) -> PipelineRunResponse:
    if not Path(payload.abr_dir).is_dir():
        raise HTTPException(status_code=400, detail=f"Abronal folder not found: {payload.abr_dir}")
    if not Path(payload.sot_dir).is_dir():
        raise HTTPException(status_code=400, detail=f"SoT folder not found: {payload.sot_dir}")

    run_id = uuid.uuid4().hex
    with _jobs_lock:
        _jobs[run_id] = {
            "status": "queued",
            "log": [],
            "created_at": datetime.utcnow().isoformat(),
        }

    background_tasks.add_task(_execute_pipeline, run_id, payload)
    return PipelineRunResponse(run_id=run_id, status="queued")


@router.get("/status/{run_id}", response_model=PipelineStatusResponse)
def get_status(run_id: str) -> PipelineStatusResponse:
    with _jobs_lock:
        job = _jobs.get(run_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Unknown run_id")
    return PipelineStatusResponse(
        run_id=run_id,
        status=job["status"],
        log=job["log"],
        error=job.get("error"),
    )


@router.get("/results/{run_id}", response_model=PipelineResultsResponse)
def get_results(run_id: str) -> PipelineResultsResponse:
    with _jobs_lock:
        job = _jobs.get(run_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Unknown run_id")
    if job["status"] != "done":
        raise HTTPException(status_code=409, detail=f"Run is not finished yet (status: {job['status']})")

    return PipelineResultsResponse(
        run_id=run_id,
        commission_summary=job["commission_summary"],
        perfect_match_count=job["perfect_match_count"],
        mismatch_count=job["mismatch_count"],
        db_path=job["db_path"],
    )