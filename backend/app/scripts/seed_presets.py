"""scripts/seed_presets.py — Idempotently seed the 5-motor fleet preset.

Runnable as:
    python -m app.scripts.seed_presets
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.routes.motors import create_motor_row
from app.db.models import FaultInjected, Motor
from app.simulation.presets import PRESET_MOTORS

log = logging.getLogger(__name__)


def inject_preset_fault(db: Session, motor_id: int, fault_data: dict, created_by: str = "admin", rt: Any = None) -> FaultInjected:
    row = FaultInjected(
        motor_id=motor_id,
        fault_type=fault_data["fault_type"],
        severity=fault_data["severity"],
        params_json=fault_data.get("params", {}),
        created_by=created_by,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def seed_presets(db: Session, rt: Any = None) -> dict[str, list[str]]:
    """Seeds the 5 preset motors into the database.

    Idempotent: skips any motor whose exact name already exists.
    Returns:
        {"created": list[str], "skipped": list[str]}
    """
    created: list[str] = []
    skipped: list[str] = []

    for preset in PRESET_MOTORS:
        existing = db.scalar(select(Motor.id).where(Motor.name == preset["name"]))
        if existing is not None:
            skipped.append(preset["name"])
            continue

        motor = create_motor_row(db, preset["name"], preset["params"], preset["base_load_nm"])
        if preset.get("fault"):
            inject_preset_fault(db, motor.id, preset["fault"], rt=rt)

        if rt is not None and getattr(rt, "settings", None) and getattr(rt.settings, "run_simulation", False):
            if hasattr(rt, "manager") and hasattr(rt.manager, "start"):
                rt.manager.start(motor.id)

        created.append(preset["name"])
        log.info("Created preset motor: %s (id=%d)", motor.name, motor.id)

    return {"created": created, "skipped": skipped}


if __name__ == "__main__":
    from app.config import get_settings
    from app.db.session import init_engine, session_factory

    settings = get_settings()
    init_engine(settings.database_url)
    with session_factory()() as db_session:
        result = seed_presets(db_session)
        print(f"Seed complete: {len(result['created'])} created, {len(result['skipped'])} skipped.")
        if result["created"]:
            print(f"  Created: {', '.join(result['created'])}")
        if result["skipped"]:
            print(f"  Skipped: {', '.join(result['skipped'])}")
