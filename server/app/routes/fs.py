from __future__ import annotations

from pathlib import Path
from typing import List

from fastapi import APIRouter, HTTPException, Query

router = APIRouter(prefix="/fs", tags=["fs"])


@router.get("/browse")
def browse(path: str = Query("/")) -> dict:
    p = Path(path)
    if not p.exists():
        raise HTTPException(status_code=404, detail=f"Path not found: {path}")
    if not p.is_dir():
        raise HTTPException(status_code=400, detail=f"Not a directory: {path}")

    parent = str(p.parent) if p.parent != p else None

    entries: List[dict] = []
    try:
        for child in sorted(p.iterdir(), key=lambda x: x.name.lower()):
            if child.is_dir():
                entries.append({"name": child.name, "path": str(child)})
    except PermissionError:
        raise HTTPException(status_code=403, detail=f"Permission denied: {path}")

    return {"current": str(p), "parent": parent, "entries": entries}
