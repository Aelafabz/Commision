from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class RecordCreate(BaseModel):
    doctor_name: str
    service: str
    amount: float
    category: str


class RecordRead(RecordCreate):
    id: int
    date: datetime


class ExportRequest(BaseModel):
    from_date: str
    to_date: str
    physicians: list[str] = Field(default_factory=list)
    skip_analyzer: bool = True


class ExportResponse(BaseModel):
    status: str
    pid: int | None = None
    log_file: str


class LogResponse(BaseModel):
    log_file: str
    content: str


# ── Pipeline (primary_reconciliation -> secondary_name_matcher -> category_merger) ──

class PipelineRunRequest(BaseModel):
    abr_dir: str = Field(..., description="Folder of Abronal excel exports")
    sot_dir: str = Field(..., description="Folder of SoT excel files")
    dictionary_path: str | None = Field(
        None, description="Path to the service->category dictionary JSON. Defaults to configs/dictionary.json"
    )
    db_path: str | None = Field(
        None, description="Path to the sqlite database to append into. Defaults to database/commission.db"
    )
    date_label: str = Field("", description="e.g. 'July 20 to July 22'")
    commission_rate: float = Field(0.10, ge=0, le=1)
    name_match_confidence: float = Field(0.70, ge=0, le=1)
    date_window_days: int = Field(1, ge=0)
    on_conflict: str = Field('abort', description="Conflict policy: 'abort' | 'overwrite' | 'ignore'")


class PipelineRunResponse(BaseModel):
    run_id: str
    status: Literal["queued", "running", "done", "error"]


class PipelineStatusResponse(BaseModel):
    run_id: str
    status: Literal["queued", "running", "done", "error"]
    log: list[str]
    error: str | None = None


class PipelineResultsResponse(BaseModel):
    run_id: str
    commission_summary: list[dict[str, Any]]
    perfect_match_count: int
    mismatch_count: int
    db_path: str
    abr_dir: str | None = None
    sot_dir: str | None = None
    analyzed_dir: str | None = None