"""app/static_analysis/channels.py — Individual channel diagnostics for static snapshots.

Emits standard ChannelVerdict objects compatible with diagnostics.fusion.fuse().
Reuses authoritative constants from existing diagnostic modules.
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np

from app.diagnostics.calibration import (
    BRB_DBC_MIN,
    ECC_DBC_MIN,
    brb_db_to_severity,
    eccentricity_db_to_severity,
)
from app.diagnostics.schema import ChannelVerdict, DiagFault, DiagSource
from app.simulation.params import INSULATION_LIMITS, MotorParams
from app.static_analysis.schemas import StaticMeasurement
from app.static_analysis.steady_state import SteadyStateResult

A_COMPLEX = np.exp(2j * math.pi / 3)


def static_supply(measurement: StaticMeasurement, params: MotorParams) -> ChannelVerdict:
    """Evaluates voltage balance, sag, and harmonic distortion from static voltages.

    Limits align with EN 50160 (vuf <= 2%, sag >= 0.90 pu, thd <= 8%).
    Severity is capped at 0.75 like the live supply channel.
    """
    v_a_ph, v_b_ph, v_c_ph = measurement.to_phase_rms_voltages()
    v_rated_ph = params.rated_voltage / math.sqrt(3.0)

    # Calculate positive and negative sequence
    if measurement.phase_angles is not None:
        pa = measurement.phase_angles
        ang_a = math.radians(pa.va_deg)
        ang_b = math.radians(pa.vb_deg)
        ang_c = math.radians(pa.vc_deg)
        va_c = v_a_ph * np.exp(1j * ang_a)
        vb_c = v_b_ph * np.exp(1j * ang_b)
        vc_c = v_c_ph * np.exp(1j * ang_c)
        v_pos = abs(va_c + A_COMPLEX * vb_c + A_COMPLEX * A_COMPLEX * vc_c) / 3.0
        v_neg = abs(va_c + A_COMPLEX * A_COMPLEX * vb_c + A_COMPLEX * vc_c) / 3.0
    else:
        # NEMA standard voltage unbalance calculation
        v_mean = (v_a_ph + v_b_ph + v_c_ph) / 3.0
        max_dev = max(abs(v_a_ph - v_mean), abs(v_b_ph - v_mean), abs(v_c_ph - v_mean))
        v_pos = v_mean
        v_neg = max_dev  # Approximation

    if v_pos < 0.05 * v_rated_ph:
        return ChannelVerdict(
            DiagSource.SUPPLY,
            DiagFault.UNKNOWN,
            0.0,
            0.0,
            False,
            {"reason": "supply de-energized (< 5% rated)"},
        )

    vuf = float(v_neg / v_pos)
    vuf_limit = 0.02
    sag_limit = 0.90
    thd_limit = 0.08

    pu = float(v_pos / v_rated_ph)
    thd = (measurement.v_thd_pct / 100.0) if measurement.v_thd_pct is not None else 0.0

    details: dict[str, Any] = {
        "vuf": round(vuf, 4),
        "vuf_percent": round(vuf * 100.0, 2),
        "v_pos_pu": round(pu, 4),
        "thd": round(thd, 4) if measurement.v_thd_pct is not None else None,
    }

    sag_excess = float((1.0 - pu) / (1.0 - sag_limit)) if pu < 1.0 else 0.0
    thd_excess = (thd / thd_limit) if measurement.v_thd_pct is not None else 0.0
    vuf_excess = vuf / vuf_limit

    excess = float(max(vuf_excess, sag_excess, thd_excess))

    if excess >= 1.0 - 1e-4:
        fault_type = (
            DiagFault.VOLTAGE_SAG
            if (sag_excess >= excess - 1e-4 and pu <= sag_limit + 1e-4)
            else DiagFault.SUPPLY_ANOMALY
        )
        conf = float(min(1.0, 0.6 + 0.2 * excess))
        # Cap severity at 0.75 like the live supply diagnostic
        sev = float(min(0.75, 0.3 + 0.15 * max(0.0, excess - 1.0)))
        return ChannelVerdict(DiagSource.SUPPLY, fault_type, conf, sev, True, details)

    return ChannelVerdict(DiagSource.SUPPLY, DiagFault.HEALTHY, 0.9, 0.0, True, details)


def static_protection(measurement: StaticMeasurement, params: MotorParams) -> ChannelVerdict:
    """Evaluates instantaneous electrical protection: overcurrent, stall, phase loss, overload."""
    ia, ib, ic = measurement.i_a, measurement.i_b, measurement.i_c
    i_rms = math.sqrt((ia**2 + ib**2 + ic**2) / 3.0)
    i_pu = i_rms / max(1e-3, params.rated_current)

    details: dict[str, Any] = {
        "i_rms": round(i_rms, 2),
        "i_pu": round(i_pu, 3),
        "ia": round(ia, 2),
        "ib": round(ib, 2),
        "ic": round(ic, 2),
        "rpm": round(measurement.speed_rpm, 1),
    }

    # 1. Instantaneous Overcurrent Protection (> 5x rated)
    if i_pu >= 5.0:
        details["trip_type"] = "instantaneous_overcurrent"
        return ChannelVerdict(DiagSource.PROTECTION, DiagFault.OVERCURRENT, 1.0, 1.0, True, details)

    # 2. Stall / Locked Rotor (Current >= 2x rated AND speed <= 25% rated)
    if i_pu >= 2.0 and measurement.speed_rpm <= 0.25 * params.rated_speed:
        details["trip_type"] = "locked_rotor_stall"
        return ChannelVerdict(DiagSource.PROTECTION, DiagFault.STALL, 0.95, 0.95, True, details)

    # 3. Phase Loss / Single-Phasing
    i_mean = (ia + ib + ic) / 3.0
    if i_mean >= 0.25 * params.rated_current:
        i_min = min(ia, ib, ic)
        i_max = max(ia, ib, ic)
        unbalance = (i_max - i_min) / max(1e-3, i_mean)
        details["current_unbalance"] = round(unbalance, 3)

        if i_min < 0.10 * i_mean or (unbalance > 1.10 and i_min < 0.15 * i_mean):
            details["trip_type"] = "phase_loss_single_phasing"
            return ChannelVerdict(DiagSource.PROTECTION, DiagFault.PHASE_LOSS, 0.95, 0.95, True, details)

    # 4. Instantaneous Overload (I > 105% rated)
    if i_pu > 1.05:
        excess = (i_pu - 1.05) / 0.50
        conf = float(min(0.95, 0.60 + 0.30 * excess))
        # Capped at 0.85 for snapshot (no time-accumulator for tripping)
        sev = float(min(0.85, 0.40 + 0.40 * excess))
        details["overload_pu"] = round(i_pu, 3)
        return ChannelVerdict(DiagSource.PROTECTION, DiagFault.OVERLOAD, conf, sev, True, details)

    return ChannelVerdict(DiagSource.PROTECTION, DiagFault.HEALTHY, 0.9, 0.0, True, details)


def static_thermal(measurement: StaticMeasurement, params: MotorParams) -> ChannelVerdict:
    """Evaluates winding temperature against insulation class limits."""
    if measurement.winding_temp_c is None:
        return ChannelVerdict(
            DiagSource.THERMAL,
            DiagFault.UNKNOWN,
            0.0,
            0.0,
            False,
            {"reason": "winding temperature not provided"},
        )

    temp_c = measurement.winding_temp_c
    ins_limits = INSULATION_LIMITS.get(params.insulation_class, INSULATION_LIMITS["F"])
    warn_c = getattr(params, "warn_c", None) or ins_limits["warn_c"]
    trip_c = getattr(params, "trip_c", None) or ins_limits["trip_c"]

    details: dict[str, Any] = {
        "winding_temp_c": round(temp_c, 1),
        "ambient_temp_c": round(measurement.ambient_temp_c, 1),
        "warn_c": round(warn_c, 1),
        "trip_c": round(trip_c, 1),
        "insulation_class": params.insulation_class,
    }

    if temp_c >= trip_c:
        details["condition"] = "thermal_trip_exceeded"
        return ChannelVerdict(DiagSource.THERMAL, DiagFault.OVERHEATING, 0.99, 0.95, True, details)

    if temp_c >= warn_c:
        sev = float(min(0.85, 0.50 + 0.35 * (temp_c - warn_c) / max(1.0, trip_c - warn_c)))
        details["condition"] = "thermal_warning_exceeded"
        return ChannelVerdict(DiagSource.THERMAL, DiagFault.OVERHEATING, 0.95, sev, True, details)

    return ChannelVerdict(DiagSource.THERMAL, DiagFault.HEALTHY, 0.9, 0.0, True, details)


def static_electrical(
    measurement: StaticMeasurement,
    params: MotorParams,
    eq_result: SteadyStateResult,
) -> ChannelVerdict:
    """Evaluates steady-state current residual, phase imbalance (ITSC), and spectral sidebands (BRB/Eccentricity)."""
    ia, ib, ic = measurement.i_a, measurement.i_b, measurement.i_c
    i_mean = (ia + ib + ic) / 3.0
    i_exp = eq_result.stator_current_mag

    # Stator current residual: measured vs analytical equivalent circuit
    r_mag = abs(i_mean - i_exp)
    fd = r_mag / max(1e-3, i_exp)

    # Current imbalance / localization (indicator of inter-turn short circuit)
    i_min = min(ia, ib, ic)
    i_max = max(ia, ib, ic)
    unbalance = (i_max - i_min) / max(1e-3, i_mean)
    fl_vals = [ia / max(1e-3, i_mean), ib / max(1e-3, i_mean), ic / max(1e-3, i_mean)]
    worst_idx = int(np.argmax(fl_vals))

    details: dict[str, Any] = {
        "measured_mean_current_a": round(i_mean, 2),
        "expected_current_a": round(i_exp, 2),
        "current_residual_a": round(r_mag, 3),
        "FD": round(fd, 4),
        "current_unbalance": round(unbalance, 4),
        "FL_worst_phase": "abc"[worst_idx],
        "FL_worst_ratio": round(fl_vals[worst_idx], 3),
    }

    # 1. Check optional spectral inputs if provided (Broken rotor bar or Eccentricity)
    if measurement.spectral is not None:
        brb_db = measurement.spectral.brb_sideband_db
        ecc_db = measurement.spectral.eccentricity_sideband_db
        details["brb_sideband_db"] = brb_db
        details["eccentricity_sideband_db"] = ecc_db

        if brb_db is not None and brb_db > BRB_DBC_MIN:
            sev = float(min(0.85, brb_db_to_severity(brb_db)))
            conf = float(min(0.95, 0.60 + 0.35 * (sev / 0.85)))
            details["spectral_fault"] = "broken_rotor_bar"
            return ChannelVerdict(DiagSource.ELECTRICAL_RESIDUAL, DiagFault.BROKEN_ROTOR_BAR, conf, sev, True, details)

        if ecc_db is not None and ecc_db > ECC_DBC_MIN:
            sev = float(min(0.85, eccentricity_db_to_severity(ecc_db)))
            conf = float(min(0.95, 0.60 + 0.35 * (sev / 0.85)))
            details["spectral_fault"] = "eccentricity"
            return ChannelVerdict(DiagSource.ELECTRICAL_RESIDUAL, DiagFault.ECCENTRICITY, conf, sev, True, details)

    # 2. Check Inter-Turn Short Circuit (ITSC): marked phase unbalance with balanced supply
    v_a_ph, v_b_ph, v_c_ph = measurement.to_phase_rms_voltages()
    v_mean_ph = (v_a_ph + v_b_ph + v_c_ph) / 3.0
    v_unbalance = (max(v_a_ph, v_b_ph, v_c_ph) - min(v_a_ph, v_b_ph, v_c_ph)) / max(1e-3, v_mean_ph)

    # If supply voltage is balanced (unbalance < 2%), current unbalance >= 5% indicates stator turn short
    if v_unbalance < 0.02 and unbalance >= 0.05:
        excess = (unbalance - 0.05) / 0.15
        conf = float(min(0.95, 0.65 + 0.30 * min(1.0, excess)))
        sev = float(min(0.85, 0.35 + 0.50 * min(1.0, excess)))
        details["fault_domain"] = "stator_winding_asymmetry"
        return ChannelVerdict(DiagSource.ELECTRICAL_RESIDUAL, DiagFault.INTERTURN_SHORT, conf, sev, True, details)

    # 3. Check general electrical residual magnitude
    if fd >= 0.05:
        # Unexpected current drawn compared to steady-state model
        sev = float(min(0.60, 0.25 + 0.35 * (fd - 0.05) / 0.10))
        conf = float(min(0.70, 0.40 + 0.30 * min(1.0, fd / 0.15)))
        return ChannelVerdict(DiagSource.ELECTRICAL_RESIDUAL, DiagFault.INDETERMINATE, conf, sev, True, details)

    # 4. Healthy electrical state
    conf = float(min(1.0, 0.70 + 0.30 * max(0.0, 1.0 - fd / 0.03)))
    return ChannelVerdict(DiagSource.ELECTRICAL_RESIDUAL, DiagFault.HEALTHY, conf, 0.0, True, details)


def static_mechanical(measurement: StaticMeasurement, params: MotorParams) -> ChannelVerdict:
    """Evaluates mechanical condition using vibration amplitudes according to ISO 10816."""
    if measurement.vibration is None:
        return ChannelVerdict(
            DiagSource.ML_CLASSIFIER,
            DiagFault.UNKNOWN,
            0.0,
            0.0,
            False,
            {"reason": "vibration measurements not provided"},
        )

    vib = measurement.vibration
    if all(x is None for x in (vib.overall_rms_mm_s, vib.peak_1x_mm_s, vib.peak_2x_mm_s, vib.bearing_defect_mm_s)):
        return ChannelVerdict(
            DiagSource.ML_CLASSIFIER,
            DiagFault.UNKNOWN,
            0.0,
            0.0,
            False,
            {"reason": "all vibration fields empty"},
        )

    details: dict[str, Any] = {
        "overall_rms_mm_s": vib.overall_rms_mm_s,
        "peak_1x_mm_s": vib.peak_1x_mm_s,
        "peak_2x_mm_s": vib.peak_2x_mm_s,
        "bearing_defect_mm_s": vib.bearing_defect_mm_s,
    }

    # 1. Bearing defect peak (envelope / defect frequency)
    if vib.bearing_defect_mm_s is not None and vib.bearing_defect_mm_s > 0.5:
        val = vib.bearing_defect_mm_s
        sev = float(min(0.85, 0.35 + 0.50 * (val - 0.5) / 1.5))
        conf = float(min(0.95, 0.70 + 0.25 * min(1.0, (val - 0.5) / 1.0)))
        return ChannelVerdict(DiagSource.ML_CLASSIFIER, DiagFault.BEARING_OUTER, conf, sev, True, details)

    # 2. Misalignment (predominant 2X running speed vibration)
    if vib.peak_2x_mm_s is not None and vib.peak_2x_mm_s > 1.5:
        p2 = vib.peak_2x_mm_s
        p1 = vib.peak_1x_mm_s or 0.0
        if p2 >= 0.8 * p1:
            sev = float(min(0.85, 0.35 + 0.50 * (p2 - 1.5) / 2.0))
            conf = float(min(0.90, 0.65 + 0.25 * min(1.0, (p2 - 1.5) / 1.5)))
            return ChannelVerdict(DiagSource.ML_CLASSIFIER, DiagFault.MISALIGNMENT, conf, sev, True, details)

    # 3. Unbalance (predominant 1X running speed vibration)
    if vib.peak_1x_mm_s is not None and vib.peak_1x_mm_s > 1.8:
        p1 = vib.peak_1x_mm_s
        sev = float(min(0.85, 0.35 + 0.50 * (p1 - 1.8) / 2.0))
        conf = float(min(0.90, 0.65 + 0.25 * min(1.0, (p1 - 1.8) / 1.5)))
        return ChannelVerdict(DiagSource.ML_CLASSIFIER, DiagFault.UNBALANCE, conf, sev, True, details)

    # 4. Overall vibration velocity (ISO 10816 Zone C > 4.5 mm/s, Zone D > 7.1 mm/s)
    if vib.overall_rms_mm_s is not None:
        v_rms = vib.overall_rms_mm_s
        if v_rms > 4.5:
            sev = float(min(0.85, 0.30 + 0.55 * (v_rms - 4.5) / 3.0))
            conf = float(min(0.80, 0.60 + 0.20 * min(1.0, (v_rms - 4.5) / 2.5)))
            return ChannelVerdict(DiagSource.ML_CLASSIFIER, DiagFault.UNBALANCE, conf, sev, True, details)
        if v_rms <= 2.3:  # ISO Zone A
            return ChannelVerdict(DiagSource.ML_CLASSIFIER, DiagFault.HEALTHY, 0.95, 0.0, True, details)

    return ChannelVerdict(DiagSource.ML_CLASSIFIER, DiagFault.HEALTHY, 0.90, 0.0, True, details)


def static_spectral(measurement: StaticMeasurement, params: MotorParams) -> ChannelVerdict:
    """Assesses optional MCSA spectral lines (broken rotor bar sideband, eccentricity sideband)."""
    if measurement.spectral is None:
        return ChannelVerdict(
            DiagSource.ELECTRICAL_RESIDUAL,
            DiagFault.UNKNOWN,
            0.0,
            0.0,
            False,
            {"reason": "spectral inputs not provided"},
        )
    return static_electrical(
        measurement,
        params,
        SteadyStateResult(
            slip=0.0,
            stator_current_mag=params.rated_current,
            rotor_current_mag=0.0,
            real_power_w=0.0,
            reactive_power_var=0.0,
            apparent_power_va=0.0,
            power_factor=1.0,
            torque_developed_nm=0.0,
            mechanical_power_w=0.0,
            z_in=0j,
        ),
    )
