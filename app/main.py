from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pathlib import Path

from app.routers import reconciliation, evaluation

APP_DIR = Path(__file__).resolve().parent
STATIC_DIR = APP_DIR / "static"

app = FastAPI(
    title="Commission Reconciliation API",
    version="1.0.0",
    description="Medical commission reconciliation and evaluation system",
)

# Include API routers
app.include_router(reconciliation.router, prefix="/api/reconciliation", tags=["Reconciliation"])
app.include_router(evaluation.router, prefix="/api/evaluation", tags=["Evaluation"])

# Serve static files
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/", include_in_schema=False)
async def serve_index():
    return FileResponse(str(STATIC_DIR / "index.html"))


@app.get("/evaluation", include_in_schema=False)
async def serve_evaluation():
    return FileResponse(str(STATIC_DIR / "evaluation.html"))


@app.get("/health")
async def health():
    return {"status": "ok"}
