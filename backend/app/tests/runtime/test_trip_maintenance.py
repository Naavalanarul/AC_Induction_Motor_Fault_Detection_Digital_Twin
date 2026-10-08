"""Regressions for bug 2 (Maintenance tab empty/wrong after a trip) and the bearing severity
calibration from bug 3. Worker-level, no HTTP: these are exactly the values /prognosis,
/recommendation and the live frame serve."""

import asyncio

import numpy as np
import pytest

from app.runtime.broker import InMemoryBroker
from app.runtime.worker import MotorWorker, WorkerConfig
from app.simulation.params import DEFAULT_MOTOR


def run_worker(fault: str, severity: float, ticks: int, inject_at: int = 30, stop_after_trip: int | None = None):
    w = MotorWorker(WorkerConfig(1, "m", DEFAULT_MOTOR, 8.0, {}, use_ml=False), InMemoryBroker(), None)
    frames = []

    async def go():
        trip_seen = None
        for i in range(ticks):
            if i == inject_at:
                w._apply({"cmd": "inject", "id": 1, "fault_type": fault, "severity": severity, "params": {}})
            frames.append(await w.tick())
            if frames[-1]["supervisory"]["trip"] and trip_seen is None:
                trip_seen = i
            if stop_after_trip is not None and trip_seen is not None and i - trip_seen >= stop_after_trip:
                break

    asyncio.run(go())
    return w, frames


@pytest.fixture(scope="module")
def tripped():
    w, frames = run_worker("bearing_outer", 0.9, ticks=300, stop_after_trip=60)
    assert frames[-1]["supervisory"]["trip"], "bearing_outer 0.9 must trip the motor"
    return w, frames


def test_prognosis_uses_latched_severity_while_tripped(tripped):
    w, frames = tripped
    latched = frames[-1]["supervisory"]["latched_severity"]
    assert frames[-1]["supervisory"]["smoothed_severity"] < 0.3 < latched  # smoothed decays during the trip
    p = w.get_prognosis()
    assert p["current_severity"] == pytest.approx(latched, abs=1e-3)
    assert p["trend"] != "decreasing"


def test_recommendation_uses_latched_fault_while_tripped(tripped):
    w, _ = tripped
    assert w.current_fault() == "bearing_outer"
    assert w.get_recommendation()["fault_type"] == "bearing_outer"


def test_post_trip_diagnoses_carry_the_latched_fault(tripped):
    _, frames = tripped
    post = [f["diagnosis"] for f in frames if f["supervisory"]["trip"]][2:]
    assert post
    for d in post:
        if d["fault_type"] == "bearing_outer":
            continue
        # healthy/indeterminate/stale misclassifications are all overridden while tripped
        assert d["fault_type"] == "indeterminate", d["fault_type"]
        override = d["per_sensor_scores"]["sada_override"]
        assert override["sada_latched_fault"] == "bearing_outer"
        assert override["sada_latched_severity"] > 0.7


@pytest.mark.parametrize("fault", ["bearing_outer", "interturn_short", "unbalance"])
def test_recommendation_tracks_diagnosis_without_db_writer(fault):
    # _last_fault used to be updated only inside _record(), which returns early without a writer.
    w, frames = run_worker(fault, 0.35, ticks=200)
    assert frames[-1]["diagnosis"]["fault_type"] == fault
    assert w.get_recommendation()["fault_type"] == fault


@pytest.mark.parametrize("fault", ["bearing_outer", "bearing_inner", "bearing_ball"])
def test_bearing_diagnosed_severity_tracks_injected_severity(fault):
    from app.diagnostics.features import window_features
    from app.diagnostics.ml.classifier import severity_from_features
    from app.simulation import faults as F
    from app.simulation.twin_state import MotorSimulator

    for injected in (0.1, 0.35, 0.6):
        sim = MotorSimulator(base_load_nm=8.0)
        sim.plant.warm_start(8.0, 1.0)
        F.inject(sim.faults, fault, injected)
        vs, acs = [], []
        for _ in range(8):
            st = sim.step()
            vs.append(st.vibration)
            acs.append(st.acoustic)
        feats = window_features(np.hstack(vs)[:, -6400:], np.hstack(acs)[-6400:], st.vib_fs, st.acoustic_fs,
                                st.electrical.omega_m.mean() / (2 * np.pi))
        assert severity_from_features(fault, feats) == pytest.approx(injected, abs=0.08)


def test_manager_db_fallback_skips_indeterminate_rows(tmp_path, monkeypatch):
    from app.config import Settings, get_settings
    from app.db import session
    from app.db.models import Base, Diagnosis, Motor
    from app.runtime.manager import WorkerManager

    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path}/m.db")
    get_settings.cache_clear()
    Base.metadata.create_all(session.init_engine())
    try:
        with session.session_factory()() as db:
            db.add(Motor(id=1, name="m", rated_power=1, rated_speed=1, rated_torque=1, params_json={}))
            db.commit()
            # oldest -> newest: a stale misclassification, then post-trip indeterminate rows
            db.add(Diagnosis(motor_id=1, fault_type="eccentricity", confidence=0.6, severity_score=0.4,
                             per_sensor_scores_json={}, health_index=60.0))
            db.add(Diagnosis(motor_id=1, fault_type="indeterminate", confidence=0.3, severity_score=0.85,
                             per_sensor_scores_json={"sada_override": {"sada_latched_fault": "bearing_outer"}},
                             health_index=0.0))
            db.add(Diagnosis(motor_id=1, fault_type="indeterminate", confidence=0.3, severity_score=0.85,
                             per_sensor_scores_json={}, health_index=0.0))
            db.commit()
            rec = WorkerManager(Settings(), InMemoryBroker(), None).get_recommendation(1, db=db)
        assert rec["fault_type"] == "bearing_outer"
    finally:
        get_settings.cache_clear()


def test_seed_default_faults_is_off_by_default(monkeypatch):
    from app.config import Settings

    monkeypatch.delenv("SEED_DEFAULT_FAULTS", raising=False)
    assert Settings(_env_file=None).seed_default_faults is False


