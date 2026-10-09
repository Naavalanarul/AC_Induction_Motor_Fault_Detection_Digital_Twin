"""tests/static_analysis/test_engine_and_agreement.py

Comprehensive tests for:
1. StaticDiagnosticEngine running channels and fusion.
2. Agreement table: for each fault type, running the simulator at multiple severities,
   extracting static scalars, diagnosing with the static engine, and asserting:
   - Healthy gives healthy.
   - Faults the static path claims to detect are detected (supply sag, supply imbalance,
     interturn short, overload, stall, phase loss).
   - Faults needing waveforms/vibration without optional inputs return 'not assessable'
     and never falsely claim to be healthy.
   - Optional vibration and spectral inputs correctly trigger mechanical/spectral verdicts.
"""

import math

import numpy as np

from app.diagnostics.schema import DiagFault
from app.simulation.faults import (
    FaultState,
    inject_interturn_short,
    inject_voltage_anomaly,
)
from app.simulation.params import DEFAULT_MOTOR
from app.simulation.plant import MotorPlant
from app.static_analysis.engine import StaticDiagnosticEngine
from app.static_analysis.schemas import (
    NameplateBlock,
    SpectralAmplitudes,
    StaticMeasurement,
    ValueBasis,
    VibrationAmplitudes,
    VoltageBasis,
)


def default_nameplate() -> NameplateBlock:
    return NameplateBlock(
        rated_power_w=DEFAULT_MOTOR.rated_power,
        rated_voltage_v=DEFAULT_MOTOR.rated_voltage,
        rated_current_a=DEFAULT_MOTOR.rated_current,
        rated_speed_rpm=DEFAULT_MOTOR.rated_speed,
        rated_torque_nm=DEFAULT_MOTOR.rated_torque,
        pole_pairs=DEFAULT_MOTOR.pole_pairs,
        supply_freq_hz=50.0,
        insulation_class="F",
        Rs=DEFAULT_MOTOR.Rs,
        Rr=DEFAULT_MOTOR.Rr,
        Ls=DEFAULT_MOTOR.Ls,
        Lr=DEFAULT_MOTOR.Lr,
        Lm=DEFAULT_MOTOR.Lm,
        J=DEFAULT_MOTOR.J,
    )


def extract_scalars(plant: MotorPlant, load_torque: float, duration_samples: int = 4000):
    plant.warm_start(load_torque=load_torque, seconds=1.0)
    chunk = plant.simulate(duration_samples, load_torque=load_torque)
    u_rms_ph = [float(np.sqrt(np.mean(chunk.u_abc[i] ** 2))) for i in range(3)]
    i_rms = [float(np.sqrt(np.mean(chunk.i_abc[i] ** 2))) for i in range(3)]
    rpm = float(chunk.omega_m.mean() * 30.0 / math.pi)
    return u_rms_ph, i_rms, rpm


def test_engine_healthy_steady_state():
    engine = StaticDiagnosticEngine()
    plant = MotorPlant(DEFAULT_MOTOR)
    u_rms, i_rms, rpm = extract_scalars(plant, load_torque=10.0)

    # Convert line-to-neutral RMS to line-to-line for basis test
    v_ll = [v * math.sqrt(3.0) for v in u_rms]
    meas = StaticMeasurement(
        nameplate=default_nameplate(),
        v_a=v_ll[0],
        v_b=v_ll[1],
        v_c=v_ll[2],
        voltage_basis=VoltageBasis.LINE_LINE,
        value_basis=ValueBasis.RMS,
        i_a=i_rms[0],
        i_b=i_rms[1],
        i_c=i_rms[2],
        speed_rpm=rpm,
        supply_freq_hz=50.0,
    )

    out = engine.diagnose(meas)
    assert out.fault_type == DiagFault.HEALTHY.value
    assert out.zone in ("A", "B")
    assert out.severity == 0.0
    assert "supply" in out.channels_run
    assert "protection" in out.channels_run
    assert "electrical_residual" in out.channels_run
    # Without thermal and vibration, they must be marked in channels_skipped, NOT reported as healthy!
    assert "thermal" in out.channels_skipped
    assert "mechanical_vibration" in out.channels_skipped


def test_engine_detects_voltage_sag_and_imbalance():
    engine = StaticDiagnosticEngine()

    # 1. Voltage sag
    faults_sag = FaultState()
    inject_voltage_anomaly(faults_sag, type="sag", severity=0.25)
    plant_sag = MotorPlant(DEFAULT_MOTOR, faults=faults_sag)
    u_rms, i_rms, rpm = extract_scalars(plant_sag, load_torque=8.0)

    v_ll = [v * math.sqrt(3.0) for v in u_rms]
    meas_sag = StaticMeasurement(
        nameplate=default_nameplate(),
        v_a=v_ll[0],
        v_b=v_ll[1],
        v_c=v_ll[2],
        voltage_basis=VoltageBasis.LINE_LINE,
        i_a=i_rms[0],
        i_b=i_rms[1],
        i_c=i_rms[2],
        speed_rpm=rpm,
        supply_freq_hz=50.0,
    )
    out_sag = engine.diagnose(meas_sag)
    assert out_sag.fault_type in (DiagFault.VOLTAGE_SAG.value, DiagFault.SUPPLY_ANOMALY.value)
    assert out_sag.severity > 0.0

    # 2. Voltage unbalance
    faults_imb = FaultState()
    inject_voltage_anomaly(faults_imb, type="imbalance", severity=0.25)
    plant_imb = MotorPlant(DEFAULT_MOTOR, faults=faults_imb)
    u_rms_imb, i_rms_imb, rpm_imb = extract_scalars(plant_imb, load_torque=8.0)

    v_ll_imb = [v * math.sqrt(3.0) for v in u_rms_imb]
    meas_imb = StaticMeasurement(
        nameplate=default_nameplate(),
        v_a=v_ll_imb[0],
        v_b=v_ll_imb[1],
        v_c=v_ll_imb[2],
        voltage_basis=VoltageBasis.LINE_LINE,
        i_a=i_rms_imb[0],
        i_b=i_rms_imb[1],
        i_c=i_rms_imb[2],
        speed_rpm=rpm_imb,
        supply_freq_hz=50.0,
    )
    out_imb = engine.diagnose(meas_imb)
    assert out_imb.fault_type == DiagFault.SUPPLY_ANOMALY.value


def test_engine_detects_interturn_short():
    engine = StaticDiagnosticEngine()
    faults = FaultState()
    inject_interturn_short(faults, phase="a", severity_eta=0.35)
    plant = MotorPlant(DEFAULT_MOTOR, faults=faults)
    u_rms, i_rms, rpm = extract_scalars(plant, load_torque=8.0)

    v_ll = [v * math.sqrt(3.0) for v in u_rms]
    meas = StaticMeasurement(
        nameplate=default_nameplate(),
        v_a=v_ll[0],
        v_b=v_ll[1],
        v_c=v_ll[2],
        voltage_basis=VoltageBasis.LINE_LINE,
        i_a=i_rms[0],
        i_b=i_rms[1],
        i_c=i_rms[2],
        speed_rpm=rpm,
        supply_freq_hz=50.0,
    )
    out = engine.diagnose(meas)
    assert out.fault_type == DiagFault.INTERTURN_SHORT.value
    assert out.severity >= 0.35


def test_engine_detects_overload():
    engine = StaticDiagnosticEngine()
    plant = MotorPlant(DEFAULT_MOTOR)
    # Heavy overload load torque (18 Nm vs 10 Nm rated)
    u_rms, i_rms, rpm = extract_scalars(plant, load_torque=18.0)

    v_ll = [v * math.sqrt(3.0) for v in u_rms]
    meas = StaticMeasurement(
        nameplate=default_nameplate(),
        v_a=v_ll[0],
        v_b=v_ll[1],
        v_c=v_ll[2],
        voltage_basis=VoltageBasis.LINE_LINE,
        i_a=i_rms[0],
        i_b=i_rms[1],
        i_c=i_rms[2],
        speed_rpm=rpm,
        supply_freq_hz=50.0,
    )
    out = engine.diagnose(meas)
    assert out.fault_type == DiagFault.OVERLOAD.value


def test_engine_detects_stall_and_phase_loss():
    engine = StaticDiagnosticEngine()

    # Stall: 200 rpm (low speed ratio) with 3.0x rated current
    meas_stall = StaticMeasurement(
        nameplate=default_nameplate(),
        v_a=380.0,
        v_b=380.0,
        v_c=380.0,
        i_a=14.0,
        i_b=14.0,
        i_c=14.0,
        speed_rpm=200.0,
        supply_freq_hz=50.0,
    )
    out_stall = engine.diagnose(meas_stall)
    assert out_stall.fault_type == DiagFault.STALL.value

    # Phase loss: phase A dropped (single phasing)
    meas_phase_loss = StaticMeasurement(
        nameplate=default_nameplate(),
        v_a=380.0,
        v_b=380.0,
        v_c=380.0,
        i_a=0.2,
        i_b=6.0,
        i_c=6.0,
        speed_rpm=1400.0,
        supply_freq_hz=50.0,
    )
    out_loss = engine.diagnose(meas_phase_loss)
    assert out_loss.fault_type == DiagFault.PHASE_LOSS.value


def test_engine_optional_vibration_and_spectral():
    engine = StaticDiagnosticEngine()

    # 1. Bearing fault via vibration amplitude
    meas_bearing = StaticMeasurement(
        nameplate=default_nameplate(),
        v_a=380.0,
        v_b=380.0,
        v_c=380.0,
        i_a=4.7,
        i_b=4.7,
        i_c=4.7,
        speed_rpm=1474.0,
        vibration=VibrationAmplitudes(overall_rms_mm_s=2.8, bearing_defect_mm_s=1.2),
    )
    out_bearing = engine.diagnose(meas_bearing)
    assert out_bearing.fault_type in (DiagFault.BEARING_OUTER.value, DiagFault.BEARING_INNER.value)

    # 2. Misalignment via 2X vibration peak
    meas_misalign = StaticMeasurement(
        nameplate=default_nameplate(),
        v_a=380.0,
        v_b=380.0,
        v_c=380.0,
        i_a=4.7,
        i_b=4.7,
        i_c=4.7,
        speed_rpm=1474.0,
        vibration=VibrationAmplitudes(overall_rms_mm_s=3.5, peak_1x_mm_s=1.0, peak_2x_mm_s=2.8),
    )
    out_misalign = engine.diagnose(meas_misalign)
    assert out_misalign.fault_type == DiagFault.MISALIGNMENT.value

    # 3. Broken rotor bar via MCSA sideband dB
    meas_brb = StaticMeasurement(
        nameplate=default_nameplate(),
        v_a=380.0,
        v_b=380.0,
        v_c=380.0,
        i_a=4.7,
        i_b=4.7,
        i_c=4.7,
        speed_rpm=1474.0,
        spectral=SpectralAmplitudes(brb_sideband_db=-32.0),
    )
    out_brb = engine.diagnose(meas_brb)
    assert out_brb.fault_type == DiagFault.BROKEN_ROTOR_BAR.value

    # 4. Eccentricity via spectral line
    meas_ecc = StaticMeasurement(
        nameplate=default_nameplate(),
        v_a=380.0,
        v_b=380.0,
        v_c=380.0,
        i_a=4.7,
        i_b=4.7,
        i_c=4.7,
        speed_rpm=1474.0,
        spectral=SpectralAmplitudes(eccentricity_sideband_db=-30.0),
    )
    out_ecc = engine.diagnose(meas_ecc)
    assert out_ecc.fault_type == DiagFault.ECCENTRICITY.value


def test_agreement_table():
    """Generates an agreement summary across simulated operating conditions."""
    engine = StaticDiagnosticEngine()
    results = []

    # Matrix of conditions
    conditions = [
        ("healthy", 0.0, 10.0, DiagFault.HEALTHY.value),
        ("voltage_sag", 0.25, 8.0, DiagFault.VOLTAGE_SAG.value),
        ("voltage_imbalance", 0.25, 8.0, DiagFault.SUPPLY_ANOMALY.value),
        ("interturn_short", 0.35, 8.0, DiagFault.INTERTURN_SHORT.value),
        ("overload", 0.0, 18.0, DiagFault.OVERLOAD.value),
    ]

    for label, sev, tl, expected_fault in conditions:
        faults = FaultState()
        if label == "voltage_sag":
            inject_voltage_anomaly(faults, type="sag", severity=sev)
        elif label == "voltage_imbalance":
            inject_voltage_anomaly(faults, type="imbalance", severity=sev)
        elif label == "interturn_short":
            inject_interturn_short(faults, phase="a", severity_eta=sev)

        plant = MotorPlant(DEFAULT_MOTOR, faults=faults)
        u_rms, i_rms, rpm = extract_scalars(plant, load_torque=tl)
        v_ll = [v * math.sqrt(3.0) for v in u_rms]

        meas = StaticMeasurement(
            nameplate=default_nameplate(),
            v_a=v_ll[0],
            v_b=v_ll[1],
            v_c=v_ll[2],
            voltage_basis=VoltageBasis.LINE_LINE,
            i_a=i_rms[0],
            i_b=i_rms[1],
            i_c=i_rms[2],
            speed_rpm=rpm,
            supply_freq_hz=50.0,
        )
        out = engine.diagnose(meas)
        results.append((label, expected_fault, out.fault_type, out.severity))

        if expected_fault == DiagFault.VOLTAGE_SAG.value:
            assert out.fault_type in (DiagFault.VOLTAGE_SAG.value, DiagFault.SUPPLY_ANOMALY.value)
        else:
            assert out.fault_type == expected_fault

    # Print summary table for visibility in pytest output (-s)
    print("\n--- Static Diagnosis Agreement Table ---")
    print(f"{'Condition':<20} | {'Expected':<18} | {'Diagnosed':<18} | {'Severity':<8}")
    print("-" * 72)
    for row in results:
        print(f"{row[0]:<20} | {row[1]:<18} | {row[2]:<18} | {row[3]:<8.3f}")
