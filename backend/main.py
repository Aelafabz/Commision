from __future__ import annotations

import sys
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

APP_ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(APP_ROOT / "db"))
sys.path.insert(0, str(APP_ROOT / "scripts" / "new"))
sys.path.insert(0, str(BACKEND_DIR))

import db_manager as dbm  # noqa: E402

from routers import pipeline, tables, export, scraper  # noqa: E402

app = FastAPI(title="Reconciliation Console")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(pipeline.router, prefix="/api/pipeline", tags=["pipeline"])
app.include_router(scraper.router, prefix="/api/scraper", tags=["scraper"])
app.include_router(tables.router, prefix="/api/tables", tags=["tables"])
app.include_router(export.router, prefix="/api/export", tags=["export"])


@app.on_event("startup")
def on_startup():
    if not dbm.DB_PATH.exists():
        dbm.init_db()
        dbm.seed_dictionary(APP_ROOT / "dictionary.json")


FRONTEND_DIR = APP_ROOT / "frontend"
app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")


@app.get("/")
def index():
    return FileResponse(FRONTEND_DIR / "index.html")


@app.get("/evaluation")
def evaluation():
    return FileResponse(FRONTEND_DIR / "evaluation.html")
