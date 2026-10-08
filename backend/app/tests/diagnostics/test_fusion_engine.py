"""Phase 6: fusion output schema + channel isolation."""

import pytest

from app.diagnostics.fusion import fuse
from app.diagnostics.schema import SCHEMA_VERSION, ChannelVerdict, DiagFault, DiagSource


def v(source, fault, conf=0.9, sev=0.5, available=True):
    return ChannelVerdict(source, fault, conf, sev, available)


def test_fused_schema_is_frozen():
    d = fuse(1.0, [v(DiagSource.THERMAL, DiagFault.HEALTHY)]).to_dict()
    assert set(d) == {"t", "fault_type", "confidence", "severity", "per_sensor_scores", "secondary", "source",
                      "schema_version"}
    assert d["schema_version"] == SCHEMA_VERSION == "1.0"


def test_domain_weighting_prefers_authoritative_channel():
    d = fuse(0.0, [
        v(DiagSource.ELECTRICAL_RESIDUAL, DiagFault.BROKEN_ROTOR_BAR, 0.8),
        v(DiagSource.ML_CLASSIFIER, DiagFault.UNBALANCE, 0.5),
        v(DiagSource.THERMAL, DiagFault.HEALTHY),
    ])
    assert d.fault_type == DiagFault.BROKEN_ROTOR_BAR
    assert d.secondary[0]["fault_type"] == "unbalance"


def test_all_healthy_and_all_unavailable():
    assert fuse(0, [v(DiagSource.THERMAL, DiagFault.HEALTHY)]).fault_type == DiagFault.HEALTHY
    assert fuse(0, [v(DiagSource.THERMAL, DiagFault.UNKNOWN, available=False)]).fault_type == DiagFault.UNKNOWN


def test_bearing_fault_detected_through_full_pipeline(pipeline):
    diag, *_ = pipeline("bearing_inner", 0.7, use_ml=False)
    assert diag.fault_type == DiagFault.BEARING_INNER


def test_ml_channel_crash_does_not_block_electrical(pipeline, monkeypatch):
    from app.diagnostics.engine import DiagnosticEngine

    def crash(self, frames, dt):
        raise RuntimeError("ml down")

    monkeypatch.setattr(DiagnosticEngine, "_run_mechanical", crash)
    diag, *_ = pipeline("interturn_short", 0.5, {"phase": "a"})
    assert diag.fault_type == DiagFault.INTERTURN_SHORT
    ml = diag.per_sensor_scores[DiagSource.ML_CLASSIFIER.value]
    assert ml["available"] is False and "error" in ml["details"]["reason"]


@pytest.mark.slow
def test_ml_backend_end_to_end(pipeline):
    diag, *_ = pipeline("misalignment", 0.7, use_ml=True)
    assert diag.fault_type == DiagFault.MISALIGNMENT


class TestIndeterminateDuringTrip:
    """Post-trip diagnoses must be INDETERMINATE, not HEALTHY.

    When SADA trips and de-energises the motor, fault-sensitive channels
    (electrical, ML) mark themselves unavailable.  Only the thermal
    channel remains, reporting HEALTHY.  The fusion engine sees a single
    available channel saying healthy → returns HEALTHY.  The worker's
    override logic must catch this and emit INDETERMINATE instead.
    """

    @staticmethod
    def _run_to_trip_and_beyond(
        fault: str = "bearing_outer",
        severity: float = 0.9,
        pre_trip_chunks: int = 80,
        post_trip_chunks: int = 10,
    ):
        """Run the simulation until SADA trips, then continue and collect
        post-trip diagnoses with the worker-style override applied."""
        import asyncio

        from app.diagnostics.engine import DiagnosticEngine
        from app.diagnostics.ml.classifier import MechanicalClassifier
        from app.diagnostics.schema import FusedDiagnosis
        from app.sensors import SensorRegistry
        from app.simulation import faults as F
        from app.simulation.twin_state import MotorSimulator
        from app.supervisory.sada import SadaSupervisor

        sim = MotorSimulator(base_load_nm=8.0)
        reg = SensorRegistry(sim.state)
        eng = DiagnosticEngine(sim.state.params, sim.fs, classifier=MechanicalClassifier(use_ml=False))
        sada = SadaSupervisor()

        F.inject(sim.faults, fault, severity, {})

        # Phase 1: run until SADA trips (or exhaust pre_trip_chunks)
        tripped_at = None
        for i in range(pre_trip_chunks):
            st = sim.step()
            frames = asyncio.run(reg.read_all())
            diag = eng.process(st.t, frames, sim.chunk_s)
            out = sada.update(diag)
            sim.state.load_cmd, sim.state.tripped = out.load_cmd, out.trip
            if out.trip:
                tripped_at = i
                break

        assert tripped_at is not None, (
            f"SADA did not trip within {pre_trip_chunks} chunks; "
            f"final state={sada.state.value}"
        )

        # Phase 2: continue after trip — collect post-trip diagnoses
        # Apply the same override logic as worker.py tick()
        post_trip_diags: list[FusedDiagnosis] = []
        for _ in range(post_trip_chunks):
            st = sim.step()
            frames = asyncio.run(reg.read_all())
            diag = eng.process(st.t, frames, sim.chunk_s)
            out = sada.update(diag)

            # --- the worker's own SADA-trip override (single source of truth) ---
            from app.runtime.worker import apply_trip_override

            diag = apply_trip_override(diag, out, sada.latched_fault)

            sim.state.load_cmd, sim.state.tripped = out.load_cmd, out.trip
            post_trip_diags.append(diag)

        return sada, post_trip_diags

    def test_post_trip_diagnoses_are_indeterminate(self):
        """Post-trip diagnoses must have fault_type INDETERMINATE, not HEALTHY."""
        sada, diags = self._run_to_trip_and_beyond()

        assert sada.state.value == "TRIP"

        # Every post-trip diagnosis should be INDETERMINATE (not HEALTHY)
        for i, d in enumerate(diags):
            assert d.fault_type != DiagFault.HEALTHY, (
                f"post-trip diagnosis {i} was HEALTHY — "
                f"should be INDETERMINATE when SADA is tripped"
            )
            # It should be either INDETERMINATE or the actual fault
            # (the fault might still be detected on first tick after trip
            # before channels go unavailable)
            assert d.fault_type in (
                DiagFault.INDETERMINATE,
                DiagFault.BEARING_OUTER,
                DiagFault.UNKNOWN,
            ), f"unexpected fault_type {d.fault_type!r} at post-trip tick {i}"

    def test_sada_latched_fault_in_metadata(self):
        """The SADA-latched fault type must be recoverable from per_sensor_scores."""
        sada, diags = self._run_to_trip_and_beyond()

        # Find the first INDETERMINATE diagnosis
        indet = [d for d in diags if d.fault_type == DiagFault.INDETERMINATE]
        assert len(indet) > 0, "no INDETERMINATE diagnoses found after trip"

        for d in indet:
            # Check per_sensor_scores for sada_override metadata
            assert "sada_override" in d.per_sensor_scores, (
                "INDETERMINATE diagnosis missing sada_override in per_sensor_scores"
            )
            meta = d.per_sensor_scores["sada_override"]
            assert meta["sada_latched_fault"] == "bearing_outer"
            assert meta["reason"] == "channels_starved_during_trip"

            # Also check secondary
            assert len(d.secondary) > 0
            assert d.secondary[0]["sada_latched_fault"] == "bearing_outer"

    def test_normal_healthy_motor_still_reports_healthy(self, pipeline):
        """A genuinely healthy motor must still report HEALTHY (no false INDETERMINATE)."""
        from app.supervisory.sada import SadaSupervisor

        sada = SadaSupervisor()
        diag, out, *_ = pipeline(fault=None, severity=0.0, chunks=40, sada=sada)
        assert diag.fault_type == DiagFault.HEALTHY
        assert sada.state.value == "NORMAL"
