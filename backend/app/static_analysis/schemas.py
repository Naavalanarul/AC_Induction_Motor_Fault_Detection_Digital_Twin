"""app/static_analysis/schemas.py — Pydantic schemas for static-value diagnosis.

Validates manual nameplate and scalar operating measurements (RMS voltages/currents,
speed, frequency, thermal, vibration, and spectral entries).
"""

from __future__ import annotations

import math
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

from app.diagnostics.schema import SCHEMA_VERSION, DiagSource
from app.simulation.params import MotorParams, validate_motor_params


class VoltageBasis(str, Enum):
    LINE_LINE = "line_line"
    LINE_NEUTRAL = "line_neutral"


class ValueBasis(str, Enum):
    RMS = "rms"
    PEAK = "peak"


class NameplateBlock(BaseModel):
    """Nameplate specification for an induction motor."""

    rated_power_w: float = Field(gt=0, description="Rated mechanical power in Watts")
    rated_voltage_v: float = Field(ge=50.0, le=15000.0, description="Rated line-to-line voltage in Volts")
    rated_current_a: float = Field(gt=0, description="Rated phase/line current in Amperes")
    rated_speed_rpm: float = Field(gt=0, description="Rated mechanical speed in RPM")
    rated_torque_nm: float = Field(gt=0, description="Rated torque in Newton-meters")
    pole_pairs: int = Field(ge=1, le=12, default=2, description="Pole pairs (e.g. 2 for 4-pole motor)")
    supply_freq_hz: float = Field(ge=40.0, le=70.0, default=50.0, description="Rated supply frequency in Hz")
    insulation_class: Literal["B", "F", "H"] = Field(default="F", description="NEMA/IEC insulation thermal class")

    # Optional explicit equivalent-circuit parameters
    Rs: float | None = Field(default=None, gt=0, description="Stator resistance [Ohms]")
    Rr: float | None = Field(default=None, gt=0, description="Rotor resistance [Ohms]")
    Ls: float | None = Field(default=None, gt=0, description="Stator total self-inductance [H]")
    Lr: float | None = Field(default=None, gt=0, description="Rotor total self-inductance [H]")
    Lm: float | None = Field(default=None, gt=0, description="Mutual/magnetizing inductance [H]")
    J: float | None = Field(default=None, ge=1e-4, description="Rotor moment of inertia [kg*m^2]")

    def to_motor_params(self) -> MotorParams:
        """Converts nameplate to app.simulation.params.MotorParams, estimating equivalent circuit if omitted."""
        has_eq = all(
            x is not None for x in (self.Rs, self.Rr, self.Ls, self.Lr, self.Lm, self.J)
        )
        if has_eq:
            p = MotorParams(
                Rs=float(self.Rs),  # type: ignore[arg-type]
                Rr=float(self.Rr),  # type: ignore[arg-type]
                Ls=float(self.Ls),  # type: ignore[arg-type]
                Lr=float(self.Lr),  # type: ignore[arg-type]
                Lm=float(self.Lm),  # type: ignore[arg-type]
                J=float(self.J),    # type: ignore[arg-type]
                pole_pairs=self.pole_pairs,
                rated_power=self.rated_power_w,
                rated_voltage=self.rated_voltage_v,
                rated_current=self.rated_current_a,
                rated_speed=self.rated_speed_rpm,
                rated_torque=self.rated_torque_nm,
                insulation_class=self.insulation_class,
            )
            ok, msg = validate_motor_params(p, supply_freq=self.supply_freq_hz)
            if not ok:
                raise ValueError(f"Explicit motor parameters fail physical validation: {msg}")
            return p

        # Synthesize equivalent-circuit parameters based on standard industrial induction motor design heuristics
        v_phase = self.rated_voltage_v / math.sqrt(3.0)
        z_base = v_phase / self.rated_current_a
        w_e = 2.0 * math.pi * self.supply_freq_hz

        # Standard pu estimates for industrial standard squirrel-cage induction motors
        rs = 0.030 * z_base
        rr = 0.030 * z_base
        # Leakage inductances (split symmetrically between stator and rotor)
        x_leak = 0.039 * z_base
        l_leak = x_leak / w_e
        # Magnetizing branch
        x_m = 1.16 * z_base
        lm = x_m / w_e
        ls = lm + l_leak
        lr = lm + l_leak
        j = max(1e-4, 0.0131 * ((self.rated_power_w / 1500.0) ** 1.5))

        p = MotorParams(
            Rs=rs,
            Rr=rr,
            Ls=ls,
            Lr=lr,
            Lm=lm,
            J=j,
            pole_pairs=self.pole_pairs,
            rated_power=self.rated_power_w,
            rated_voltage=self.rated_voltage_v,
            rated_current=self.rated_current_a,
            rated_speed=self.rated_speed_rpm,
            rated_torque=self.rated_torque_nm,
            insulation_class=self.insulation_class,
        )
        return p


class VibrationAmplitudes(BaseModel):
    overall_rms_mm_s: float | None = Field(default=None, ge=0, description="Overall vibration velocity RMS [mm/s]")
    peak_1x_mm_s: float | None = Field(default=None, ge=0, description="1X running speed spectral peak [mm/s]")
    peak_2x_mm_s: float | None = Field(default=None, ge=0, description="2X running speed spectral peak [mm/s]")
    bearing_defect_mm_s: float | None = Field(default=None, ge=0, description="Peak bearing defect envelope / BPFO/BPFI [mm/s]")


class SpectralAmplitudes(BaseModel):
    brb_sideband_db: float | None = Field(
        default=None,
        description="Broken rotor bar MCSA sideband f_s*(1 - 2s) amplitude relative to carrier in dB (e.g. -45 dB)",
    )
    eccentricity_sideband_db: float | None = Field(
        default=None,
        description="Eccentricity sideband f_s +/- f_r amplitude relative to carrier in dB",
    )


class PhaseAngles(BaseModel):
    va_deg: float = 0.0
    vb_deg: float = -120.0
    vc_deg: float = 120.0
    ia_deg: float | None = None
    ib_deg: float | None = None
    ic_deg: float | None = None


class StaticMeasurement(BaseModel):
    """Input payload for static snapshot diagnosis."""

    motor_id: int | None = Field(default=None, description="Database motor ID to load reference params from")
    nameplate: NameplateBlock | None = Field(default=None, description="Inline nameplate ratings")

    # Required 3-phase voltages
    v_a: float = Field(gt=0, description="Phase A voltage magnitude")
    v_b: float = Field(gt=0, description="Phase B voltage magnitude")
    v_c: float = Field(gt=0, description="Phase C voltage magnitude")
    voltage_basis: VoltageBasis = Field(default=VoltageBasis.LINE_LINE, description="Line-to-line vs Line-to-neutral")
    value_basis: ValueBasis = Field(default=ValueBasis.RMS, description="RMS vs Peak values")

    # Required 3-phase currents
    i_a: float = Field(gt=0, description="Phase A current RMS [A]")
    i_b: float = Field(gt=0, description="Phase B current RMS [A]")
    i_c: float = Field(gt=0, description="Phase C current RMS [A]")

    # Required operating frequency and speed
    speed_rpm: float = Field(gt=0, description="Measured shaft rotational speed in RPM")
    supply_freq_hz: float = Field(ge=40.0, le=70.0, default=50.0, description="Supply frequency in Hz [40.0, 70.0]")

    # Optional measurements
    winding_temp_c: float | None = Field(default=None, ge=-40.0, le=250.0, description="Measured winding temperature [C]")
    ambient_temp_c: float = Field(default=25.0, ge=-20.0, le=80.0, description="Ambient temperature [C]")
    power_kw: float | None = Field(default=None, ge=0, description="Measured 3-phase real power in kW")
    power_factor: float | None = Field(default=None, ge=-1.0, le=1.0, description="Measured power factor cos(phi)")
    vibration: VibrationAmplitudes | None = Field(default=None, description="Optional mechanical vibration levels")
    spectral: SpectralAmplitudes | None = Field(default=None, description="Optional MCSA sideband amplitudes")
    v_thd_pct: float | None = Field(default=None, ge=0, le=100.0, description="Voltage total harmonic distortion [%]")
    phase_angles: PhaseAngles | None = Field(default=None, description="Optional phase angle measurements")

    @model_validator(mode="after")
    def _validate_inputs(self) -> StaticMeasurement:
        if self.motor_id is None and self.nameplate is None:
            raise ValueError("Either motor_id or nameplate must be provided for static diagnosis.")

        if self.nameplate is not None:
            # Check speed strictly below synchronous speed for motoring
            n_sync = 60.0 * self.supply_freq_hz / self.nameplate.pole_pairs
            if self.speed_rpm >= n_sync:
                raise ValueError(
                    f"Measured speed ({self.speed_rpm:.1f} RPM) must be strictly below synchronous speed "
                    f"({n_sync:.1f} RPM) for motoring operation."
                )

            # Plausibility check on voltage: phase RMS in 10% to 200% of rated phase RMS
            v_rated_ph = self.nameplate.rated_voltage_v / math.sqrt(3.0)
            v_a_ph, v_b_ph, v_c_ph = self.to_phase_rms_voltages()
            for name, val in [("v_a", v_a_ph), ("v_b", v_b_ph), ("v_c", v_c_ph)]:
                if not (0.1 * v_rated_ph <= val <= 2.0 * v_rated_ph):
                    raise ValueError(
                        f"Voltage {name} ({val:.1f} V phase RMS) deviates excessively from rated "
                        f"({v_rated_ph:.1f} V phase RMS). Acceptable operational range: [10%, 200%]."
                    )

            # Plausibility check on current: maximum phase RMS in 5% to 1000% of rated current
            i_rated = self.nameplate.rated_current_a
            i_max = max(self.i_a, self.i_b, self.i_c)
            if not (0.05 * i_rated <= i_max <= 10.0 * i_rated):
                raise ValueError(
                    f"Maximum current ({i_max:.2f} A) deviates excessively from rated ({i_rated:.2f} A). "
                    "Acceptable range: [5%, 1000%]."
                )

        return self

    def to_phase_rms_voltages(self) -> tuple[float, float, float]:
        """Converts the three voltage readings to line-to-neutral (phase) RMS in Volts."""
        va, vb, vc = self.v_a, self.v_b, self.v_c
        if self.value_basis == ValueBasis.PEAK:
            va /= math.sqrt(2.0)
            vb /= math.sqrt(2.0)
            vc /= math.sqrt(2.0)
        if self.voltage_basis == VoltageBasis.LINE_LINE:
            va /= math.sqrt(3.0)
            vb /= math.sqrt(3.0)
            vc /= math.sqrt(3.0)
        return va, vb, vc


class DerivedMetrics(BaseModel):
    """Calculated engineering parameters derived from the snapshot inputs."""

    slip: float
    expected_current_a: float
    current_imbalance_pct: float
    voltage_unbalance_pct: float
    loading_pu: float
    stator_current_residual_a: float
    real_power_w: float | None = None
    power_factor: float | None = None


class StaticDiagnosisOut(BaseModel):
    """Output payload for static snapshot diagnosis.

    Reuses frozen FusedDiagnosis fields and provides comprehensive advisory assessment.
    """

    t: float = Field(description="Timestamp of diagnosis")
    fault_type: str = Field(description="Fused diagnostic fault classification")
    confidence: float = Field(ge=0, le=1.0, description="Fusion confidence [0, 1]")
    severity: float = Field(ge=0, le=1.0, description="Severity score [0, 1]")
    per_sensor_scores: dict[str, dict[str, Any]] = Field(description="Individual channel verdicts")
    secondary: list[dict[str, Any]] = Field(default_factory=list, description="Secondary fault candidates")
    source: str = Field(default=DiagSource.FUSED.value, description="Diagnostic source")
    schema_version: str = Field(default=SCHEMA_VERSION, description="Diagnostic schema version")

    health_index: float = Field(ge=0, le=100.0, description="Motor Health Index (MHI) [0, 100]")
    zone: str = Field(description="MHI condition zone (A, B, C, D)")
    error_code: str = Field(description="Industrial diagnostic error code <SOURCE>-<FAULT>-<ZONE>")
    recommendation: dict[str, Any] = Field(description="Prescriptive maintenance recommendation")
    channels_run: list[str] = Field(description="List of diagnostic channels successfully evaluated")
    channels_skipped: dict[str, str] = Field(description="Mapping of unassessed channels to explicit reason")
    derived: DerivedMetrics = Field(description="Derived electrical parameters")
    warnings: list[str] = Field(default_factory=list, description="Advisory validation warnings")
    advisory_notice: str = Field(
        default="Advisory only, no control action taken.",
        description="Explicit notice confirming snapshot cannot drive real-time control",
    )
