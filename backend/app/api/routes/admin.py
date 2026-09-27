"""api/routes/admin.py — Admin-only management endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import Principal, require, runtime
from app.db.session import get_db
from app.scripts.seed_presets import seed_presets

router = APIRouter(prefix="/admin", tags=["admin"])


class SeedPresetsOut(BaseModel):
    created: list[str]
    skipped: list[str]


@router.post("/seed-presets", response_model=SeedPresetsOut)
async def seed_fleet_presets(
    _: Principal = Depends(require("admin")),
    db: Session = Depends(get_db),
    rt=Depends(runtime),
):
    """Idempotently seeds the 5 preset industrial motors and their initial faults."""
    return seed_presets(db, rt=rt)
