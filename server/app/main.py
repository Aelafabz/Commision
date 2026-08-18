from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from .database import Base, engine
from .routes.export import router as export_router
from .routes.pipeline import router as pipeline_router
from .routes.records import router as records_router
from .routes.fs import router as fs_router
from .routes.db_inspect import router as db_inspect_router
from .routes.info import router as info_router

Base.metadata.create_all(bind=engine)

app = FastAPI(title="Commission Records API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,  # wildcard origins + credentials is invalid per spec
    allow_methods=["*"],
    allow_headers=["*"],
)

# IMPORTANT: API routers must be registered BEFORE the catch-all static mount.
# Starlette matches routes in registration order, and Mount("/") matches every
# path -- including /api/*. Mounting it first was silently swallowing every
# API request and returning 404 "file not found" instead of hitting the API.
app.include_router(records_router, prefix="/api")
app.include_router(export_router, prefix="/api")
app.include_router(pipeline_router, prefix="/api")
app.include_router(fs_router, prefix="/api")
app.include_router(db_inspect_router, prefix="/api")
app.include_router(info_router, prefix="/api")


@app.get("/health")
def health_check() -> dict[str, str]:
    return {"status": "ok"}


FRONTEND_DIR = Path(__file__).resolve().parents[2] / "Frontend"
if FRONTEND_DIR.exists():
    app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")