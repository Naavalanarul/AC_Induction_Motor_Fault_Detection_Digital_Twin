"""tests/simulation/test_presets.py — Unit tests for Phase 19 fleet presets."""

from __future__ import annotations

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.api.schemas import MotorParamsIn
from app.db.models import Base, Motor
from app.scripts.seed_presets import seed_presets
from app.simulation.presets import PRESET_MOTORS


def test_preset_parameters_validate():
    """Assert all 5 preset motor parameters satisfy MotorParamsIn validation."""
    assert len(PRESET_MOTORS) == 5
    for p in PRESET_MOTORS:
        assert "name" in p
        assert "base_load_nm" in p
        assert "params" in p
        # Validates physical constraints including Lm < min(Ls, Lr)
        validated = MotorParamsIn(**p["params"])
        assert validated.rated_power > 0
        assert validated.Lm < min(validated.Ls, validated.Lr)


def test_seed_presets_idempotency():
    """Assert seed_presets() creates all 5 motors once, and subsequent runs skip them."""
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)

    with Session(engine) as db:
        res1 = seed_presets(db)
        assert len(res1["created"]) == 5
        assert len(res1["skipped"]) == 0

        # Running again produces no new motors
        res2 = seed_presets(db)
        assert len(res2["created"]) == 0
        assert len(res2["skipped"]) == 5

        total_motors = db.scalars(select(Motor)).all()
        assert len(total_motors) == 5
