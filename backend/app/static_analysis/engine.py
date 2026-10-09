"""app/static_analysis/engine.py — Orchestrates static-value snapshot diagnosis.

Executes steady-state physics evaluation, invokes applicable diagnostic channels,
fuses verdicts via diagnostics.fusion.fuse(), computes MHI and error code, and
formats a comprehensive advisory diagnostic report.
"""

from __future__ import annotations

import time

from sqlalchemy.orm import Session

from app.db.models import Motor
from app.diagnostics.fusion import fuse
from app.diagnostics.health_index import compute_mhi, error_code
from app.diagnostics.recommendations import get_recommendation
from app.diagnostics.schema import DiagFault, DiagSource
from app.simulation.params import DEFAULT_MOTOR, MotorParams
from app.static_analysis.channels import (
    static_electrical,
    static_mechanical,
    static_protection,
    static_supply,
    static_thermal,
)
from app.static_analysis.schemas import (
    DerivedMetrics,
    StaticDiagnosisOut,
    StaticMeasurement,
)
from app.static_analysis.steady_state import solve_steady_state


class StaticDiagnosticEngine:
    """Offline static snapshot diagnostic engine."""

    def __init__(self, default_params: MotorParams = DEFAULT_MOTOR):
        self.default_params = default_params

    def resolve_motor_params(
        self,
        measurement: StaticMeasurement,
        db: Session | None = None,
    ) -> tuple[MotorParams, int | None]:
        """Resolves MotorParams from inline nameplate or database motor record."""
        if measurement.nameplate is not None:
            return measurement.nameplate.to_motor_params(), measurement.motor_id

        if measurement.motor_id is not None:
            if db is not None:
                m = db.get(Motor, measurement.motor_id)
                if m is not None and m.params_json:
                    p = MotorParams(**m.params_json)
                    return p, m.id
            # Fallback for testing or standalone runs
            return self.default_params, measurement.motor_id

        return self.default_params, None

    def diagnose(
        self,
        measurement: StaticMeasurement,
        db: Session | None = None,
        timestamp: float | None = None,
    ) -> StaticDiagnosisOut:
        """Executes full diagnostic pipeline on static measurement snapshot."""
        t_diag = timestamp if timestamp is not None else time.time()
        params, motor_id = self.resolve_motor_params(measurement, db=db)

        # 1. Steady-state equivalent circuit solution
        va_ph, vb_ph, vc_ph = measurement.to_phase_rms_voltages()
        v_ph_mean = (va_ph + vb_ph + vc_ph) / 3.0
        eq_res = solve_steady_state(
            params=params,
            v_phase_rms=v_ph_mean,
            supply_freq=measurement.supply_freq_hz,
            speed_rpm=measurement.speed_rpm,
        )

        # 2. Run diagnostic channels
        v_sup = static_supply(measurement, params)
        v_prot = static_protection(measurement, params)
        v_therm = static_thermal(measurement, params)
        v_elec = static_electrical(measurement, params, eq_res)
        v_mech = static_mechanical(measurement, params)

        all_verdicts = [v_sup, v_prot, v_therm, v_elec, v_mech]

        # 3. Categorize assessed vs unassessable channels
        channels_run: list[str] = []
        channels_skipped: dict[str, str] = {}
        channel_names = {
            DiagSource.SUPPLY: "supply",
            DiagSource.PROTECTION: "protection",
            DiagSource.THERMAL: "thermal",
            DiagSource.ELECTRICAL_RESIDUAL: "electrical_residual",
            DiagSource.ML_CLASSIFIER: "mechanical_vibration",
        }

        for v in all_verdicts:
            c_name = channel_names.get(v.source, v.source.value)
            if v.available and v.fault_type != DiagFault.UNKNOWN:
                channels_run.append(c_name)
            else:
                reason = v.details.get("reason", "not assessable: insufficient sensor data")
                channels_skipped[c_name] = str(reason)

        # 4. Fuse available verdicts
        fused = fuse(t=t_diag, verdicts=all_verdicts)

        # 5. Compute MHI, condition zone, error code, and recommendations
        # SADA is fixed to NORMAL for static snapshots (snapshots cannot command drives)
        mhi, zone = compute_mhi(fused.severity, sada_state="NORMAL")
        err_code = error_code(source=fused.source, fault_type=fused.fault_type, zone=zone)
        rec = get_recommendation(
            motor_id=motor_id or 1,
            fault_type=fused.fault_type,
            zone=zone,
            mhi=mhi,
        )

        # 6. Compute derived metrics
        ia, ib, ic = measurement.i_a, measurement.i_b, measurement.i_c
        i_mean = (ia + ib + ic) / 3.0
        i_imb_pct = ((max(ia, ib, ic) - min(ia, ib, ic)) / max(1e-3, i_mean)) * 100.0
        v_imb_pct = ((max(va_ph, vb_ph, vc_ph) - min(va_ph, vb_ph, vc_ph)) / max(1e-3, v_ph_mean)) * 100.0
        load_pu = i_mean / max(1e-3, params.rated_current)
        residual_a = abs(i_mean - eq_res.stator_current_mag)

        derived = DerivedMetrics(
            slip=round(eq_res.slip, 5),
            expected_current_a=round(eq_res.stator_current_mag, 3),
            current_imbalance_pct=round(i_imb_pct, 2),
            voltage_unbalance_pct=round(v_imb_pct, 2),
            loading_pu=round(load_pu, 3),
            stator_current_residual_a=round(residual_a, 3),
            real_power_w=round(eq_res.real_power_w, 1),
            power_factor=round(eq_res.power_factor, 3),
        )

        warnings: list[str] = []
        if channels_skipped:
            missing_names = ", ".join(channels_skipped.keys())
            warnings.append(
                f"Diagnostic based on partial telemetry. Skipped channels: {missing_names}."
            )

        return StaticDiagnosisOut(
            t=t_diag,
            fault_type=fused.fault_type.value,
            confidence=round(float(fused.confidence), 4),
            severity=round(float(fused.severity), 4),
            per_sensor_scores=fused.per_sensor_scores,
            secondary=fused.secondary,
            source=fused.source.value,
            schema_version=fused.schema_version,
            health_index=mhi,
            zone=zone,
            error_code=err_code,
            recommendation=rec,
            channels_run=channels_run,
            channels_skipped=channels_skipped,
            derived=derived,
            warnings=warnings,
            advisory_notice="Advisory only, no control action taken.",
        )
