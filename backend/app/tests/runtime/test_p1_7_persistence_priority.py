"""tests/runtime/test_p1_7_persistence_priority.py — P1-7 High-priority persistence queue regression tests."""

from __future__ import annotations

import asyncio
from pathlib import Path

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db.models import Alert, Base, Motor, SupervisoryAction
from app.runtime.writer import DBWriter


def test_p1_7_priority_queue_survives_telemetry_backpressure(tmp_path: Path):
    """P1-7: High-priority queue accepts audit records even when standard queue is completely full."""
    dead_letter_file = tmp_path / "dead_letter.jsonl"
    writer = DBWriter(max_queue=2, max_priority_queue=10, dead_letter_path=str(dead_letter_file))

    # Fill up the normal queue
    writer.put("normal_telemetry_1", priority=False)
    writer.put("normal_telemetry_2", priority=False)
    # Next normal item should drop due to queue full
    writer.put("normal_telemetry_3", priority=False)
    assert writer.dropped == 1

    # But priority audit records must NOT be dropped!
    action = SupervisoryAction(motor_id=1, state="TRIP", load_cmd=0.0, reason_code="TRIP_I_INSTANTANEOUS", trip=True)
    alert = Alert(motor_id=1, severity="critical", message="Instantaneous overcurrent trip")

    writer.put(action)  # Auto-detected as priority
    writer.put_priority(alert)

    assert writer.priority_dropped == 0
    assert writer.priority_queue.qsize() == 2


def test_p1_7_forced_db_failure_recovers_and_persists_trip(tmp_path: Path, monkeypatch):
    """P1-7: Trip events survive simulated DB outage, log to dead letter, and write to DB upon recovery."""
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)

    # Seed motor 1
    with Session(engine) as db:
        motor = Motor(id=1, name="Test Motor", rated_power=1500.0, rated_speed=1420.0, rated_torque=10.0, params_json={})
        db.add(motor)
        db.commit()

    dead_letter_file = tmp_path / "dead_letter.jsonl"
    writer = DBWriter(dead_letter_path=str(dead_letter_file))

    # Mock session_factory to simulate DB outage initially
    db_failing = True

    def mock_session_factory():
        def factory():
            if db_failing:
                raise RuntimeError("Simulated MySQL/DB connection dropped!")
            return Session(engine)
        return factory

    monkeypatch.setattr("app.runtime.writer.session_factory", mock_session_factory)

    async def run_scenario():
        writer.start()

        # Enqueue critical trip action
        action = SupervisoryAction(
            motor_id=1,
            state="TRIP",
            load_cmd=0.0,
            reason_code="TRIP_THERMAL_OVERHEAT",
            trip=True,
            smoothed_severity=1.0,
        )
        writer.put(action, priority=True)

        # Allow writer loop to attempt writes during failure
        await asyncio.sleep(0.4)

        # Verify dead letter file was created and written to during failure
        assert dead_letter_file.exists()
        dead_letter_content = dead_letter_file.read_text(encoding="utf-8")
        assert "supervisory_actions" in dead_letter_content
        assert "TRIP_THERMAL_OVERHEAT" in dead_letter_content

        # DB is still failing, so nothing in database yet
        with Session(engine) as db:
            rows = db.scalars(select(SupervisoryAction)).all()
            assert len(rows) == 0

        # Now DB recovers!
        nonlocal db_failing
        db_failing = False

        # Allow writer loop to retry and drain
        await asyncio.sleep(0.3)
        await writer.flush(timeout=2.0)

        # Verify trip event survived and is now successfully committed to the database!
        with Session(engine) as db:
            persisted = db.scalars(select(SupervisoryAction).where(SupervisoryAction.motor_id == 1)).all()
            assert len(persisted) == 1
            assert persisted[0].state == "TRIP"
            assert persisted[0].reason_code == "TRIP_THERMAL_OVERHEAT"
            assert persisted[0].trip is True

    asyncio.run(run_scenario())
