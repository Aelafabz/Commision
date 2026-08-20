from __future__ import annotations

import asyncio
import sys
import traceback
from pathlib import Path
from typing import Dict, List, Optional

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

APP_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(APP_ROOT / "db"))
sys.path.insert(0, str(APP_ROOT / "scripts" / "new"))
import db_manager as dbm  # noqa: E402
import abronal_scraper  # noqa: E402

router = APIRouter()

RUN_LOGS: Dict[str, List[str]] = {}
RUN_LISTENERS: Dict[str, List[asyncio.Queue]] = {}


def _emit(batch_id: str, message: str):
    RUN_LOGS.setdefault(batch_id, []).append(message)
    for q in RUN_LISTENERS.get(batch_id, []):
        q.put_nowait(message)


class ScrapeRequest(BaseModel):
    from_date: str          # YYYY-MM-DD
    to_date: str             # YYYY-MM-DD
    physicians: Optional[List[str]] = None   # None/omitted = all (minus config skip list)


@router.get("/config-check")
def config_check():
    """Tells the UI whether .env credentials are present, without
    ever exposing the values themselves."""
    return {"configured": abronal_scraper.ScraperConfig.has_credentials()}


def _run_scrape_sync(batch_id: str, req: ScrapeRequest):
    try:
        dbm.start_run(batch_id, "abronal_scraper")
        _emit(batch_id, f"Starting Abronal export run {batch_id}")
        result = abronal_scraper.run(
            req.from_date, req.to_date, req.physicians, log=lambda m: _emit(batch_id, m)
        )
        summary = f"saved={len(result.saved)} failed={len(result.failed)}"
        status = "success" if result.saved and not result.failed else (
            "success" if result.saved else "failed"
        )
        dbm.finish_run(batch_id, status, summary)
        _emit(batch_id, f"SCRAPE_DONE::{status}")
    except abronal_scraper.ScraperError as e:
        _emit(batch_id, f"ERROR: {e}")
        dbm.finish_run(batch_id, "failed", str(e))
        _emit(batch_id, "SCRAPE_DONE::failed")
    except Exception as e:  # noqa: BLE001
        tb = traceback.format_exc()
        _emit(batch_id, f"ERROR: {e}\n{tb}")
        dbm.finish_run(batch_id, "failed", str(e))
        _emit(batch_id, "SCRAPE_DONE::failed")


@router.post("/run")
async def run_scrape(req: ScrapeRequest):
    batch_id = dbm.new_batch_id()
    RUN_LOGS[batch_id] = []
    RUN_LISTENERS[batch_id] = []
    asyncio.get_event_loop().run_in_executor(None, _run_scrape_sync, batch_id, req)
    return {"batch_id": batch_id}


@router.get("/status/{batch_id}")
def status(batch_id: str):
    with dbm.get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM pipeline_runs WHERE batch_id = ?", (batch_id,)
        ).fetchone()
    return dict(row) if row else {"error": "unknown batch_id"}


@router.get("/log/{batch_id}")
def get_log(batch_id: str):
    return {"lines": RUN_LOGS.get(batch_id, [])}


@router.websocket("/ws/{batch_id}")
async def ws_log(websocket: WebSocket, batch_id: str):
    await websocket.accept()
    q: asyncio.Queue = asyncio.Queue()
    RUN_LISTENERS.setdefault(batch_id, []).append(q)
    try:
        for line in RUN_LOGS.get(batch_id, []):
            await websocket.send_text(line)
        while True:
            line = await q.get()
            await websocket.send_text(line)
            if line.startswith("SCRAPE_DONE::"):
                break
    except WebSocketDisconnect:
        pass
    finally:
        RUN_LISTENERS.get(batch_id, []).remove(q)
